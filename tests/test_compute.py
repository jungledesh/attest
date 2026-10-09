"""Tests for compute. Hand-built claims through resolve, then the functions. No model."""

import json
from datetime import date

from attest import db
from attest.resolve import resolve_patient
from attest import compute as c

C, P = "Clinic", "M1"


def _db():
    con = db.connect(":memory:")
    docs = [("PLAN", "treatment_plan"), ("N1", "clinical_note"), ("N2", "clinical_note"), ("R", "attendance_register"),
            ("MED", "clinical_note"), ("A", "clinical_note"), ("B", "clinical_note")]
    for d, t in docs:
        db.insert_document(con, d, f"sha-{d}", f"{d}.txt", "", "now")
        db.insert_claims(con, [(d, C, P, f"doc:{d}", "doc_type", t, 1)])
    cl = [
        ("PLAN", "plan:PLAN", "effective_from", "2026-01-05", 6), ("PLAN", "plan:PLAN", "effective_to", "2026-01-18", 6),
        ("PLAN", "plan:PLAN", "min_days_per_week", "2", 12), ("PLAN", "plan:PLAN", "min_minutes_per_week", "100", 12),
        ("PLAN", "plan:PLAN", "counting_type", "individual", 12), ("PLAN", "plan:PLAN", "counting_type", "group", 12),
        ("PLAN", "plan:PLAN", "excluded_type", "medication", 12),
        # week 1: individual 50 + group 45 = 95, 2 days -> not met
        ("N1", "E1", "service_date", "2026-01-05", 3), ("N1", "E1", "service_type", "individual", 3),
        ("N1", "E1", "contact_interval", "09:00–09:50", 5), ("N1", "E1", "status", "attended", 5),
        ("N2", "E2", "service_date", "2026-01-06", 3), ("N2", "E2", "service_type", "group", 3),
        ("N2", "E2", "contact_interval", "10:00–11:30", 5), ("N2", "E2", "nontherapeutic_interval", "10:45–11:00", 6),
        ("R", "E2", "arrival", "10:15", 4), ("R", "E2", "departure", "11:15", 4), ("R", "E2", "status", "attended", 4),
        ("MED", "E3", "service_date", "2026-01-07", 3), ("MED", "E3", "service_type", "medication", 3),
        ("MED", "E3", "contact_interval", "09:00–09:25", 4), ("MED", "E3", "status", "attended", 4),
        # week 2: one individual with conflicting notes 40-50 + group 75 -> 115-125, straddles nothing (goal 100) -> met
        ("A", "E4", "service_date", "2026-01-12", 3), ("A", "E4", "service_type", "individual", 3),
        ("A", "E4", "contact_interval", "09:00–09:50", 5), ("A", "E4", "status", "attended", 5),
        ("B", "E4", "contact_interval", "09:10–09:50", 5), ("B", "E4", "status", "attended", 5),
        ("N2", "E5", "service_date", "2026-01-13", 9), ("N2", "E5", "service_type", "group", 9),
        ("R", "E5", "arrival", "10:00", 8), ("R", "E5", "departure", "11:15", 8), ("R", "E5", "status", "attended", 8),
    ]
    db.insert_claims(con, [(d, C, P, s, f, v, l) for d, s, f, v, l in cl])
    resolve_patient(con, C, P)
    return con


def test_sessions_counts_types_days_and_excludes_medication():
    s = c.sessions(_db(), C, P, date(2026, 1, 5), date(2026, 1, 18))
    assert s["total"] == 4 and s["by_type"] == {"individual": 2, "group": 2} and s["distinct_days"] == 4
    assert any(e["service_type"] == "medication" and "excluded" in e["why"] for e in s["excluded"])
    assert any(m["subject"] == "E4" and m["documents"] == ["A", "B"] for m in s["multi_document"])


def test_minutes_by_week_with_range_for_conflict():
    m = c.minutes_by_week(_db(), C, P, date(2026, 1, 5), date(2026, 1, 18))
    w1, w2 = m["weeks"]
    assert (w1["minutes_low"], w1["minutes_high"], w1["minutes_with_breaks"]) == (95, 95, 110)
    assert (w2["minutes_low"], w2["minutes_high"]) == (115, 125)
    assert m["total_minutes_low"] == 210 and m["total_minutes_high"] == 220


def test_plan_check_verdicts_and_break_flip():
    p = c.plan_check(_db(), C, P, date(2026, 1, 5), date(2026, 1, 18))
    w1, w2 = p["weeks"]
    assert w1["verdict"] == "not_met" and w1["if_breaks_counted"] is not None
    assert w2["verdict"] == "met"


def test_plan_check_without_plan_is_cannot_determine():
    con = db.connect(":memory:")
    db.insert_document(con, "N", "sha", "n.txt", "", "now")
    db.insert_claims(con, [("N", C, P, "doc:N", "doc_type", "clinical_note", 1),
                           ("N", C, P, "E1", "service_date", "2026-02-02", 2), ("N", C, P, "E1", "service_type", "individual", 2),
                           ("N", C, P, "E1", "contact_interval", "09:00–09:45", 3), ("N", C, P, "E1", "status", "attended", 3)])
    resolve_patient(con, C, P)
    p = c.plan_check(con, C, P, date(2026, 2, 2), date(2026, 2, 8))
    assert p["weeks"][0]["verdict"] == "cannot_determine" and "no treatment plan" in p["weeks"][0]["reason"]


def test_day_and_consecutive_below():
    con = _db()
    d = c.day(con, C, P, date(2026, 1, 6))
    assert d["therapy_contacts"] == 1 and d["therapy_minutes"] == 45 and d["therapy_minutes_with_breaks"] == 60
    cb = c.consecutive_below(con, date(2026, 1, 5), date(2026, 1, 18))
    assert cb["patients_checked"] == 1 and cb["below"] == []


def test_timeline_progress_is_computed_not_judged():
    con = db.connect(":memory:")
    for d in ("A", "B", "C"):
        db.insert_document(con, d, f"sha-{d}", f"{d}.txt", "", "now")
        db.insert_claims(con, [(d, C, P, f"doc:{d}", "doc_type", "measure", 1)])
    db.insert_claims(con, [
        ("A", C, P, "measure:A:0", "score_name", "PHQ-9", 2), ("A", C, P, "measure:A:0", "score_value", "18", 2),
        ("A", C, P, "measure:A:0", "completed_on", "2026-01-05", 2),
        ("B", C, P, "measure:B:0", "score_name", "PHQ-9", 2), ("B", C, P, "measure:B:0", "score_value", "10", 2),
        ("B", C, P, "measure:B:0", "completed_on", "2026-01-30", 2),
        ("C", C, P, "measure:C:0", "score_name", "PHQ-9", 2), ("C", C, P, "measure:C:0", "score_value", "18", 2),
        ("C", C, P, "measure:C:0", "completed_on", "2026-01-05", 2), ("C", C, P, "measure:C:0", "copy_of", "A", 3)])
    resolve_patient(con, C, P)
    pr = c.timeline(con, C, P)["progress"]
    t = pr["trends"][0]
    assert (t["first"], t["last"], t["change"], t["direction"], t["n_distinct"]) == (18, 10, -8, "decreased", 2)
    assert any("copies" in x for x in pr["supported"])
    assert any("only instrument" in x for x in pr["not_supported"])
