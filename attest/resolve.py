"""Rules in order. Read claims, write resolved with basis.

    python -m attest.resolve [--db out/attest.db]

Rules are general. None names a patient, a date, or a document.
Every resolved row says which rule won and which claim rows it used.
"""

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

from . import db
from . import intervals as iv

# Source precedence for presence, status, and time fields when documents of
# different types disagree and none corrects another. Higher wins.
RANK = {"correction": 6, "clinical_note": 5, "attendance_register": 4, "measure": 4,
        "treatment_plan": 4, "scheduling_export": 3, "retransmission": 2, "admin": 2,
        "billing": 1, "draft": 0}

# Scheduling facts: what was booked. The desk, billing, and the clinician all know these equally,
# so the source ladder does not apply; every document is one vote and a correction still wins.
SCHEDULING_FIELDS = {"service_type", "service_date", "scheduled_start", "scheduled_end", "modality"}
LIST_FIELDS = {"contact_interval", "patient_present_interval", "nontherapeutic_interval",
               "counting_type", "excluded_type", "goal"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _doc_types(con):
    rows = con.execute("SELECT doc_id, value FROM claims WHERE field='doc_type' AND subject LIKE 'doc:%'").fetchall()
    return {r[0]: r[1] for r in rows}


def _doc_flags(con):
    rows = con.execute("SELECT doc_id, flags FROM documents").fetchall()
    return {r[0]: r[1] for r in rows}


def resolve_field(field, claims, doc_types):
    """claims: list of sqlite rows for one (subject, field). Returns (value, basis, rows, status)."""
    rows = [c["id"] for c in claims]
    by_val = defaultdict(list)
    for c in claims:
        by_val[c["value"]].append(c)

    if len(by_val) == 1:
        v = next(iter(by_val))
        docs = sorted({c["doc_id"] for c in claims})
        basis = f"stated by {', '.join(docs)}" if len(docs) > 1 else f"stated by {docs[0]}"
        return v, basis, rows, "resolved"

    # Rule 1: a correction outranks every other document for the fields it states about this subject.
    corr = [c for c in claims if doc_types.get(c["doc_id"]) == "correction"]
    if corr:
        cv = {c["value"] for c in corr}
        if len(cv) == 1:
            losers = sorted({c["doc_id"] for c in claims if c["doc_id"] not in {x["doc_id"] for x in corr}})
            copies = [d for d in losers if doc_types.get(d) == "retransmission"]
            basis = f"correction {corr[0]['doc_id']} replaces {', '.join(d for d in losers if d not in copies)}"
            if copies:
                basis += f"; {', '.join(copies)} is a retransmission of the pre-correction value, no new evidence"
            return corr[0]["value"], basis, rows, "resolved"

    # Rule 2: for scheduling facts every document is one vote. Majority wins; a tie is unresolved.
    if field in SCHEDULING_FIELDS:
        votes = defaultdict(set)
        for c in claims:
            votes[c["value"]].add(c["doc_id"])
        order = sorted(votes, key=lambda v: len(votes[v]), reverse=True)
        if len(votes[order[0]]) > len(votes[order[1]]):
            v = order[0]
            others = "; ".join(f"{', '.join(sorted(votes[o]))} said {o}" for o in order[1:])
            return v, f"{len(votes[v])} of {len({c['doc_id'] for c in claims})} documents say {v} ({', '.join(sorted(votes[v]))}); {others}", rows, "resolved"
        alts = "; ".join(f"{c['doc_id']} says {c['value']} (line {c['line']})" for c in claims)
        return None, f"documents disagree on a scheduling fact, not settled by the record: {alts}", rows, "unresolved"

    # Rule 3: for presence and time fields, the stronger source type wins (RANK).
    ranked = sorted(claims, key=lambda c: RANK.get(doc_types.get(c["doc_id"], "admin"), 2), reverse=True)
    top_rank = RANK.get(doc_types.get(ranked[0]["doc_id"], "admin"), 2)
    top = [c for c in ranked if RANK.get(doc_types.get(c["doc_id"], "admin"), 2) == top_rank]
    tv = {c["value"] for c in top}
    if len(tv) == 1:
        winner = top[0]
        losers = [c for c in claims if c["value"] != winner["value"]]
        parts = []
        for c in losers:
            t = doc_types.get(c["doc_id"], "unknown")
            parts.append(f"{c['doc_id']} ({t}) said {c['value']}")
        basis = (f"{doc_types.get(winner['doc_id'])} {winner['doc_id']} outranks lower sources: " + "; ".join(parts))
        return winner["value"], basis, rows, "resolved"

    # Rule 4: top-rank sources split. Lower-rank sources break the tie when they side with one value.
    # Majority of documents, not of rows; a document counts once per value.
    votes = defaultdict(set)
    for c in claims:
        votes[c["value"]].add(c["doc_id"])
    ranked_vals = sorted(tv, key=lambda v: len(votes[v]), reverse=True)
    if len(votes[ranked_vals[0]]) > len(votes[ranked_vals[1]]):
        v = ranked_vals[0]
        others = "; ".join(f"{', '.join(sorted(votes[o]))} said {o}" for o in ranked_vals[1:])
        basis = (f"top-rank sources disagree; {len(votes[v])} of {len({c['doc_id'] for c in claims})} documents say {v} "
                 f"({', '.join(sorted(votes[v]))}); {others}")
        return v, basis, rows, "resolved"

    # Rule 5: still tied: unresolved. Keep every value.
    alts = "; ".join(f"{c['doc_id']} says {c['value']} (line {c['line']})" for c in top)
    return None, f"conflict between equal sources, not settled by the record: {alts}", rows, "unresolved"


def resolve_patient(con, clinic, patient):
    doc_types = _doc_types(con)
    claims = db.claims_for_patient(con, clinic, patient)
    groups = defaultdict(list)
    extras = defaultdict(list)
    for c in claims:
        if c["subject"].startswith("doc:"):
            continue
        if c["field"].startswith("extra:") or c["field"].startswith("unmapped:"):
            extras[(c["subject"], c["field"])].append(c)
            continue
        groups[(c["subject"], c["field"])].append(c)

    out = []
    # Extra facts are informational: not resolved, not used in any calculation, kept so a
    # reconstruction can mention them (modality, call IDs, locations). Distinct values joined.
    for (subject, field), cs in sorted(extras.items()):
        vals = sorted({c["value"] for c in cs})
        out.append((clinic, patient, subject, field, " | ".join(vals),
                    f"stated by {', '.join(sorted({c['doc_id'] for c in cs}))}; informational, not used in calculations",
                    [c["id"] for c in cs], "resolved"))
    for (subject, field), cs in sorted(groups.items()):
        if field in LIST_FIELDS:
            # Lists are unions, deduped by value. Each kept value cites its rows.
            seen = {}
            for c in cs:
                seen.setdefault(c["value"], []).append(c["id"])
            for v, ids in seen.items():
                out.append((clinic, patient, subject, field, v,
                            f"stated by {', '.join(sorted({c['doc_id'] for c in cs if c['value']==v}))}", ids, "resolved"))
            continue
        if field == "summary":
            # One summary per document; keep all, keyed by doc so the timeline can order them.
            for c in cs:
                out.append((clinic, patient, subject, f"summary:{c['doc_id']}", c["value"],
                            f"stated by {c['doc_id']}", [c["id"]], "resolved"))
            continue
        v, basis, rows, status = resolve_field(field, cs, doc_types)
        out.append((clinic, patient, subject, field, v, basis, rows, status))

    # Derived: minutes per encounter, from the resolved time fields.
    out += derive_minutes(clinic, patient, out)
    # Derived: which documents describe each encounter.
    docs_by_subject = defaultdict(set)
    for c in claims:
        if not c["subject"].startswith(("doc:", "plan:", "measure:")):
            docs_by_subject[c["subject"]].add(c["doc_id"])
    for s, ds in docs_by_subject.items():
        out.append((clinic, patient, s, "documents", ",".join(sorted(ds)),
                    f"{len(ds)} document(s) describe this encounter", [], "resolved"))
    # Derived: distinct measures. A measure whose copy_of or (name, completed_on, source_form)
    # matches an earlier one is a copy, not a new assessment.
    out += derive_measures(clinic, patient, out)

    out = _collapse_lists(out)
    db.clear_resolved(con, clinic, patient)
    db.insert_resolved(con, out)
    return len(out)


def _collapse_lists(rows):
    """List fields are one row per value in memory (so derivations can cite each), but the
    resolved table keys on (subject, field). Store them as one row holding a JSON array."""
    lists = defaultdict(list)
    keep = []
    for r in rows:
        if r[3] in LIST_FIELDS:
            lists[(r[0], r[1], r[2], r[3])].append(r)
        else:
            keep.append(r)
    for (c, p, s, f), rs in lists.items():
        vals = [r[4] for r in rs]
        ids = sorted({i for r in rs for i in r[6]})
        docs = sorted({d for r in rs for d in r[5].replace("stated by ", "").split(", ")})
        keep.append((c, p, s, f, json.dumps(vals), f"stated by {', '.join(docs)}", ids, "resolved"))
    return keep


def _get(res, subject, field):
    for r in res:
        if r[2] == subject and r[3] == field:
            return r
    return None


def _list(res, subject, field):
    return [r[4] for r in res if r[2] == subject and r[3] == field]


def derive_minutes(clinic, patient, res):
    subjects = sorted({r[2] for r in res if not r[2].startswith(("plan:", "measure:"))})
    out = []
    for s in subjects:
        status = _get(res, s, "status")
        sv = status[4] if status else None
        present = iv.parse_ranges(_list(res, s, "patient_present_interval"))
        breaks = iv.parse_ranges(_list(res, s, "nontherapeutic_interval"))
        arr, dep = _get(res, s, "arrival"), _get(res, s, "departure")
        unresolved = [f for f in ("arrival", "departure", "status") if (g := _get(res, s, f)) and g[7] == "unresolved"]

        if sv in ("no_show", "patient_cancelled", "clinic_cancelled", "patient_absent"):
            out.append((clinic, patient, s, "minutes", "0", f"status {sv}: no patient-present therapy", [], "resolved"))
            out.append((clinic, patient, s, "minutes_with_breaks", "0", f"status {sv}", [], "resolved"))
            out.append((clinic, patient, s, "therapy_day", "false", f"status {sv}", [], "resolved"))
            continue

        # Contact intervals: legs from one document are one session (union).
        # Different documents giving different interval sets is a conflict, not a union.
        by_doc = _contacts_by_doc(res, s)
        sets = {tuple(sorted(v)) for v in by_doc.values()}
        contact = None
        if len(sets) == 1:
            contact = list(next(iter(sets)))
        elif len(sets) > 1:
            unresolved.append("contact_interval")

        day = "true" if sv in ("attended", "attended_partial") else ("unknown" if sv is None else "false")

        if unresolved:
            parts = []
            for f in unresolved:
                if f == "contact_interval":
                    alts = "; ".join(f"{d} says {', '.join(sorted(v))}" for d, v in sorted(by_doc.items()))
                    parts.append(f"contact intervals differ between documents: {alts}")
                else:
                    parts.append(f"{f} unresolved ({_get(res, s, f)[5]})")
            out.append((clinic, patient, s, "minutes", None, "; ".join(parts), [], "unresolved"))
            lo_hi = _range_from_contacts(by_doc, breaks, _contacts_by_doc(res, s, "patient_present_interval"))
            if lo_hi:
                out.append((clinic, patient, s, "minutes_range", f"{lo_hi[0]}-{lo_hi[1]}",
                            "min and max over the conflicting records", [], "unresolved"))
            out.append((clinic, patient, s, "therapy_day", day, f"status {sv or 'not stated'}", [], "resolved" if sv else "unresolved"))
            continue

        r = _minutes(contact, arr, dep, present, breaks)
        st = "resolved" if r["minutes"] is not None else "unresolved"
        out.append((clinic, patient, s, "minutes", None if r["minutes"] is None else str(r["minutes"]), r["basis"], [], st))
        out.append((clinic, patient, s, "minutes_with_breaks",
                    None if r["minutes_with_breaks"] is None else str(r["minutes_with_breaks"]), r["basis"], [], st))
        out.append((clinic, patient, s, "therapy_day", day, f"status {sv or 'not stated'}", [], "resolved" if sv else "unresolved"))
    return out


def _contacts_by_doc(res, s, field="contact_interval"):
    """subject -> {doc_id: [interval strings]} using the documents behind each resolved interval row."""
    out = defaultdict(list)
    for r in res:
        if r[2] == s and r[3] == field:
            docs = r[5].replace("stated by ", "").split(", ")
            for d in docs:
                out[d].append(r[4])
    return out


def _minutes(contact_strs, arr, dep, present, breaks):
    """Arrival and departure bound the patient's presence; contact intervals are clipped to that window."""
    a = iv.parse_time(arr[4]) if arr else None
    d = iv.parse_time(dep[4]) if dep else None
    contact = iv.parse_ranges(contact_strs) if contact_strs else []
    window = [(a, d)] if (a is not None and d is not None and d > a) else []
    if contact and window:
        r = iv.patient_minutes(contact=contact, present=(present or window), nontherapeutic=breaks or None)
        # With breaks counted, the patient-present time is the roster window itself (clipped by present).
        r["minutes_with_breaks"] = iv.patient_minutes(arrival=a, departure=d, present=present or None)["minutes"]
        r["basis"] = (f"contact intervals clipped to roster {iv.fmt(a)}–{iv.fmt(d)}; "
                      f"{r['minutes_with_breaks'] - r['minutes']} min break or no-contact time removed")
        return r
    if contact:
        r = iv.patient_minutes(contact=contact, present=present or None, nontherapeutic=breaks or None)
        return r
    return iv.patient_minutes(arrival=a, departure=d, present=present or None, nontherapeutic=breaks or None)


def _range_from_contacts(by_doc, breaks, present_by_doc):
    """When documents give different contact intervals, (min, max) minutes across them.
    Each document is computed on its own terms: its contact intervals, its own patient-present intervals."""
    vals = []
    for d, strs in by_doc.items():
        present = iv.parse_ranges(present_by_doc.get(d, []))
        m = _minutes(strs, None, None, present, breaks)["minutes"]
        if m is not None:
            vals.append(m)
    if len(vals) >= 2:
        return min(vals), max(vals)
    return None


def derive_measures(clinic, patient, res):
    ms = sorted({r[2] for r in res if r[2].startswith("measure:")})
    seen = {}
    out = []
    for s in ms:
        g = lambda f: (_get(res, s, f) or [None]*5)[4]
        key = (g("score_name"), g("completed_on"), g("source_form") or "")
        copy_of = g("copy_of")
        prior = seen.get(key) or seen.get((g("score_name"), g("completed_on"), ""))
        if copy_of or prior:
            basis = f"copy of {prior or copy_of}: same instrument and completion date, no new assessment"
            out.append((clinic, patient, s, "distinct", "false", basis, [], "resolved"))
        else:
            seen[key] = s
            seen[(g("score_name"), g("completed_on"), "")] = s
            out.append((clinic, patient, s, "distinct", "true", "first record of this score on this date", [], "resolved"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DEFAULT_PATH))
    ap.add_argument("--log", default="out/logs/resolve.log")
    a = ap.parse_args(argv)
    con = db.connect(a.db)
    t0, started = time.time(), _now()
    total = 0
    lines = []
    for p in db.patients(con):
        n = resolve_patient(con, p["clinic"], p["patient"])
        total += n
        lines.append(f"{p['clinic']} / {p['patient']}: {n} resolved rows")
    con.commit()
    unres = con.execute("SELECT COUNT(*) FROM resolved WHERE status='unresolved'").fetchone()[0]
    db.log_run(con, "resolve", started, _now(), None, 0, 0, 0.0,
               note=json.dumps({"rows": total, "unresolved": unres, "wall_s": round(time.time()-t0, 3)}))
    con.commit()
    msg = f"{_now()}  resolve  rows={total} unresolved={unres} wall={time.time()-t0:.3f}s\n" + "\n".join("  "+l for l in lines)
    print(msg)
    with open(a.log, "a") as f:
        f.write(msg + "\n")


if __name__ == "__main__":
    main()
