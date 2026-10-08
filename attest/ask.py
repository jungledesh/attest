"""Context, route to function, run, narrate with citations, fallback, save receipt.

    python -m attest.ask questions.json          # answers each; writes out/answers/<id>.md and .json
    python -m attest.ask "How many group sessions did HG-M042 attend in week 2?"

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
            "start": {"type": "string", "description": "YYYY-MM-DD"},
            "end": {"type": "string", "description": "YYYY-MM-DD"},
            "dates": {"type": "array", "items": {"type": "string"}, "description": "YYYY-MM-DD list, for day; one or more"},
            "focus": {"type": "string", "description": "what the question emphasises, one line, for the writer"},
            "why_none": {"type": "string"},
        },
        "required": ["function"],
    },
}

ROUTE_SYSTEM = """You route a question about a patient's record to one tested function. You do not answer the question.

Functions:
""" + "\n".join(f"- {k}: {v}" for k, v in FUNCTIONS.items()) + """

Rules:
- Use the context for anything the question does not name: patient, clinic, period. "The review period", "the episode" mean the context period.
- Dates are YYYY-MM-DD. "January 5-30, 2026" is start 2026-01-05, end 2026-01-30.
- If the question asks about progress, symptoms, assessments, or the reason for a visit, choose timeline.
- If it asks to reconstruct specific dates, choose day and list every date asked in dates.
- If no function fits, return function none and say why in why_none.
"""

WRITE_SYSTEM = """You write the answer to a records-review question from a function's output. Rules:
- Use only the facts in the output. Do not compute, infer, or add totals. The numbers are already computed.
- Cite the evidence: for each number or claim, name the encounter and the documents behind it as given (for example HG-E110, BH-D103). Where the output includes a basis string, state it in your own short words.
- State every unresolved item the output lists, and what would settle it.
- If the output gives a low and high value, report both and say why.
- Plain, formal English. Short paragraphs or a compact table. No filler, no hedging beyond what the output marks unresolved.
- Do not restate the question.
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

    if fn == "none" or (fn not in FUNCTIONS):
        if not ctx.get("patient"):
            text = "The question names no patient and the database holds more than one. Name the patient (MRN) to continue."
            db.log_question(con, asked, question, ctx, "none", r, {}, text, False, 0, int(t_route*1000)); con.commit()
            return text, {}, ctx
        result, err = fallback_sql(client, con, question, ctx)
        head = "This question does not map to a tested computation. Provisional answer below from a generated, read-only query; unreviewed.\n\n"
        if err:
            text = head + f"The generated query failed: {err}\n\nQuery:\n{result['sql']}"
        else:
            prose, u2, t_w = write(client, question, result, r.get("why_none"))
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
