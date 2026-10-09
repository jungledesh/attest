"""Context, route to function, run, narrate with citations, fallback, save receipt.

    python -m attest.ask questions.json          # answers each; writes out/answers/<id>.md and .json
    python -m attest.ask "How many group sessions did patient M017 attend in week 2?"

The model picks a function and fills its blanks. Code runs it. The model then writes
prose from the function output only. It never sees the documents and never does math.
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import db
from . import compute
from .extract import MODEL

FUNCTIONS = {
    "sessions": "count of therapy sessions by type and total, distinct days, excluded and duplicate records. params: start, end",
    "minutes_by_week": "therapy minutes and hours overall and per Monday-Sunday week, with unresolved items. params: start, end",
    "plan_check": "per week: treatment plan goal, days and minutes delivered, met / not_met / cannot_determine. params: start, end",
    "consecutive_below": "all patients: who had two or more consecutive weeks below the plan goal, and who depends on unresolved fields. params: start, end",
    "day": "reconstruct one date: contacts, minutes, every document that touched it. params: date",
    "timeline": "time-ordered clinical summaries and questionnaire scores, distinct vs copied. params: start, end (optional)",
    "plan_change": "care before and after a treatment-plan change. params: none",
}

ROUTE_TOOL = {
    "name": "route",
    "description": "Pick the one function that answers the question and fill its parameters.",
    "input_schema": {
        "type": "object",
        "properties": {
            "function": {"type": "string", "enum": list(FUNCTIONS) + ["none"]},
            "patient": {"type": "string", "description": "MRN, from the question or the context"},
            "named_patient": {"type": "string", "description": "the patient name or ID exactly as the question wrote it, if it names one; omit if the question names nobody"},
            "start": {"type": "string", "description": "YYYY-MM-DD"},
            "end": {"type": "string", "description": "YYYY-MM-DD"},
            "dates": {"type": "array", "items": {"type": "string"}, "description": "YYYY-MM-DD list, for day; one or more"},
            "focus": {"type": "string", "description": "what the question emphasises, one line, for the writer"},
            "why_none": {"type": "string"},
        },
        "required": ["function"],
    },
}

ROUTE_SYSTEM = """Route a question about a patient's record to one function. Do not answer it.

Functions:
""" + "\n".join(f"- {k}: {v}" for k, v in FUNCTIONS.items()) + """

- Take patient, clinic, and period from the context when the question does not name them. "The review period" and "the episode" mean the context period.
- Dates as YYYY-MM-DD.
- Progress, symptoms, assessments, or the reason for a visit: timeline.
- Reconstruct specific dates: day, with every date asked in dates.
- Nothing fits: function none, with why_none.
"""

WRITE_SYSTEM = """Write the answer to a records-review question from a function's output.

Three sections, these headings, this order: **Answer**, **Evidence**, **Unresolved**.
- Answer: one to three sentences with the numbers or verdicts.
- Evidence: a compact table or list, one line per item, each number with its encounter and documents.
- Unresolved: only items the output marks unresolved or gives as a range. What differs, between which documents, what would settle it. "None." if none.

- Use only facts in the output. Do not compute, infer, or add totals.
- Cite encounter and document IDs as the output gives them. Put a basis string in a few plain words.
- A low and high value: report both and say why in one clause.
- Short sentences. Formal. No filler, no hedging, no remarks about the output, no restating the question, no closing summary.
- If the output has `supported` and `not_supported` lists, state both under Answer, each as a short list.
- Omit what the question did not ask and the output did not flag.
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client():
    from dotenv import load_dotenv
    load_dotenv(".env")
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set.")
    return anthropic.Anthropic()


def _patient_names(con):
    """[(patient_row, name)] from the mrn and patient_name header claims."""
    out = []
    for p in db.patients(con):
        row = con.execute("SELECT value FROM claims WHERE clinic=? AND patient=? AND field='patient_name' LIMIT 1",
                          (p["clinic"], p["patient"])).fetchone()
        out.append((p, row[0] if row else "name not stated"))
    return out


def _patient_known(con, text):
    """True when the text matches a known MRN or any word of a known patient name, case-insensitive."""
    t = text.lower()
    for p, name in _patient_names(con):
        if p["patient"].lower() in t or t in p["patient"].lower():
            return True
        for w in name.lower().replace(",", " ").split():
            if len(w) > 2 and (w in t or t in w):
                return True
    return False


def default_context(con):
    """One patient in the database means that patient is the default. Period from the plan if present."""
    ps = db.patients(con)
    ctx = {}
    if len(ps) == 1:
        ctx["clinic"], ctx["patient"] = ps[0]["clinic"], ps[0]["patient"]
        for r in db.resolved_for_patient(con, ctx["clinic"], ctx["patient"]):
            if r["subject"].startswith("plan:") and r["field"] == "effective_from":
                ctx["start"] = r["value"]
            if r["subject"].startswith("plan:") and r["field"] == "effective_to":
                ctx["end"] = r["value"]
    return ctx


def route(client, question, ctx):
    t0 = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=1500, system=ROUTE_SYSTEM, tools=[ROUTE_TOOL],
        tool_choice={"type": "tool", "name": "route"},
        messages=[{"role": "user", "content": f"Context: {json.dumps(ctx)}\n\nQuestion: {question}"}])
    out = next(b.input for b in resp.content if b.type == "tool_use")
    return out, resp.usage, time.time() - t0


def run_function(con, name, params, ctx):
    clinic = ctx.get("clinic")
    patient = params.get("patient") or ctx.get("patient")
    if not clinic and patient:
        row = con.execute("SELECT clinic FROM claims WHERE patient=? LIMIT 1", (patient,)).fetchone()
        clinic = row[0] if row else None
    start = date.fromisoformat(params.get("start") or ctx.get("start") or "1900-01-01")
    end = date.fromisoformat(params.get("end") or ctx.get("end") or "2999-12-31")
    if name == "consecutive_below":
        return compute.consecutive_below(con, start, end)
    if name == "plan_change":
        return compute.plan_change(con, clinic, patient)
    if name == "day":
        ds = params.get("dates") or ([params["date"]] if params.get("date") else [])
        days = [compute.day(con, clinic, patient, date.fromisoformat(x)) for x in ds]
        return {"patient": patient, "dates": days} if len(days) != 1 else days[0]
    if name == "timeline":
        return compute.timeline(con, clinic, patient, start if params.get("start") or ctx.get("start") else None,
                                end if params.get("end") or ctx.get("end") else None)
    fn = getattr(compute, name)
    return fn(con, clinic, patient, start, end)


def write(client, question, result, focus):
    t0 = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=6000, system=WRITE_SYSTEM,
        messages=[{"role": "user", "content": f"Question: {question}\nFocus: {focus or ''}\n\nFunction output (JSON):\n{json.dumps(result, default=str)}"}])
    return "".join(b.text for b in resp.content if b.type == "text"), resp.usage, time.time() - t0


def fallback_sql(client, con, question, ctx):
    """No function fits. Model writes one read-only SELECT; code runs it; answer is labeled provisional."""
    schema = ("claims(id, doc_id, clinic, patient, subject, field, value, line): every fact as stated, one row each. "
              "Document-level fields (doc_type, signed_by, signed_at, mrn, patient_name) exist only in claims, with subject 'doc:<doc_id>'. "
              "Encounter fields (service_date, service_type, status, arrival, departure, contact_interval, summary) have subject = encounter ID. "
              "resolved(clinic, patient, subject, field, value, basis, claim_rows, status): one value per (subject, field) after conflict rules; "
              "adds minutes, minutes_with_breaks, therapy_day, documents per encounter. "
              "Plan fields have subject 'plan:<doc_id>'; scores have subject 'measure:<doc_id>:<n>'.")
    resp = client.messages.create(
        model=MODEL, max_tokens=1500,
        system="Write one SQLite SELECT that answers the question against this schema. Return only the SQL.\n" + schema,
        messages=[{"role": "user", "content": f"Context: {json.dumps(ctx)}\nQuestion: {question}"}])
    sql = "".join(b.text for b in resp.content if b.type == "text").strip()
    if "```" in sql:
        sql = sql.split("```")[1]
        if sql.lower().startswith("sql"):
            sql = sql[3:]
    sql = sql.strip()
    try:
        cols, rows = db.read_only_select(con, sql)
        result = {"sql": sql, "columns": cols, "rows": rows[:50]}
        err = None
    except Exception as e:
        result, err = {"sql": sql}, str(e)
    db.log_pending_query(con, _now(), question, sql)
    return result, err


def answer(con, client, question, ctx, log):
    asked = _now()
    r, u1, t_route = route(client, question, ctx)
    fn = r.get("function", "none")
    for k in ("patient", "start", "end"):
        if r.get(k):
            ctx[k] = r[k]
    tokens = {"in": u1.input_tokens, "out": u1.output_tokens}
    log(f"route  {fn}  params={ {k: r.get(k) for k in ('patient','start','end','dates')} }  {t_route:.2f}s")

    named = (r.get("named_patient") or "").strip()
    if named and not _patient_known(con, named):
        text = f"**Answer**\n\nNo patient in the record matches \"{named}\".\n\n**Evidence**\n\nNone.\n\n**Unresolved**\n\nNone."
        db.log_question(con, asked, question, ctx, "none", r, {}, text, False, 0, int(t_route*1000)); con.commit()
        return text, {}, ctx

    if fn == "none" or (fn not in FUNCTIONS):
        if not ctx.get("patient"):
            text = "**Answer**\n\nThe question names no patient and the record holds more than one. Name the patient to continue.\n\n**Evidence**\n\nNone.\n\n**Unresolved**\n\nNone."
            db.log_question(con, asked, question, ctx, "none", r, {}, text, False, 0, int(t_route*1000)); con.commit()
            return text, {}, ctx
        result, err = fallback_sql(client, con, question, ctx)
        head = "**Provisional.** This question does not map to a tested computation. The answer below comes from a generated, read-only query and is unreviewed.\n\n"
        if err:
            text = head + f"The generated query failed: {err}\n\nQuery:\n{result['sql']}"
        else:
            note = ("Provisional query. " + ("It returned zero rows: say the query may be wrong, not that the fact is absent. "
                    if not result.get("rows") else "Results are unreviewed. ") + (r.get("why_none") or ""))
            prose, u2, t_w = write(client, question, result, note)
            tokens["in"] += u2.input_tokens; tokens["out"] += u2.output_tokens
            text = head + prose + f"\n\nQuery (saved for review):\n```sql\n{result['sql']}\n```"
        db.log_question(con, asked, question, ctx, "fallback_sql", r, result, text, True, 0, int(t_route*1000)); con.commit()
        return text, result, ctx

    t0 = time.time()
    result = run_function(con, fn, r, ctx)
    t_fn = time.time() - t0
    prose, u2, t_w = write(client, question, result, r.get("focus"))
    tokens["in"] += u2.input_tokens; tokens["out"] += u2.output_tokens
    log(f"answer {fn}  function={t_fn*1000:.0f}ms  model={(t_route+t_w)*1000:.0f}ms  tokens={tokens['in']}+{tokens['out']}")
    db.log_question(con, asked, question, ctx, fn, r, result, prose, False, int(t_fn*1000), int((t_route+t_w)*1000))
    db.log_run(con, "ask", asked, _now(), MODEL, tokens["in"], tokens["out"], 0.0, note=json.dumps({"function": fn, "ms_function": int(t_fn*1000), "ms_model": int((t_route+t_w)*1000)}))
    con.commit()
    return prose, result, ctx


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("question", help="a question, or a path to a questions.json")
    ap.add_argument("--db", default=str(db.DEFAULT_PATH))
    ap.add_argument("--out", default="out/answers")
    ap.add_argument("--log", default="out/logs/ask.log")
    a = ap.parse_args(argv)
    Path(a.out).mkdir(parents=True, exist_ok=True); Path(a.log).parent.mkdir(parents=True, exist_ok=True)
    logf = open(a.log, "a")

    def log(m):
        line = f"{_now()}  {m}"; print(line); logf.write(line + "\n"); logf.flush()

    con = db.connect(a.db)
    client = _client()
    ctx = default_context(con)
    log(f"start  model={MODEL}  context={ctx}")

    if a.question.endswith(".json") and Path(a.question).exists():
        qs = json.load(open(a.question))
    else:
        qs = [{"id": "Q", "question": a.question}]

    for q in qs:
        log(f"Q {q['id']}: {q['question'][:90]}")
        text, result, ctx = answer(con, client, q["question"], ctx, log)
        (Path(a.out) / f"{q['id']}.md").write_text(f"# {q['id']}\n\n**Question.** {q['question']}\n\n{text}\n")
        (Path(a.out) / f"{q['id']}.json").write_text(json.dumps({"question": q["question"], "context": ctx, "result": result}, indent=1, default=str))
        print("\n" + text + "\n")


if __name__ == "__main__":
    main()
