"""Tests for resolve. Hand-built claims, one trap each. No model, in-memory DB."""

from attest import db
from attest.resolve import resolve_patient

C, P = "Clinic", "M1"


def _setup(docs, claims):
    con = db.connect(":memory:")
    for doc_id, doc_type in docs:
        db.insert_document(con, doc_id, f"sha-{doc_id}", f"{doc_id}.txt", "", "now")
        db.insert_claims(con, [(doc_id, C, P, f"doc:{doc_id}", "doc_type", doc_type, 1)])
    db.insert_claims(con, [(d, C, P, s, f, v, l) for d, s, f, v, l in claims])
    resolve_patient(con, C, P)
    return {(r["subject"], r["field"]): dict(r) for r in db.resolved_for_patient(con, C, P)}


def test_correction_beats_roster_and_retransmission_adds_nothing():
    r = _setup([("R", "attendance_register"), ("K", "correction"), ("T", "retransmission")],
               [("R", "E1", "departure", "11:30", 9), ("K", "E1", "departure", "11:15", 7),
                ("T", "E1", "departure", "11:30", 15), ("R", "E1", "arrival", "10:00", 9),
                ("R", "E1", "status", "attended", 9)])
    dep = r[("E1", "departure")]
    assert dep["value"] == "11:15" and dep["status"] == "resolved"
    assert "correction K" in dep["basis"] and "retransmission" in dep["basis"]
    assert r[("E1", "minutes")]["value"] == "75"


def test_signed_register_beats_draft():
    r = _setup([("G", "attendance_register"), ("D", "draft")],
               [("G", "E2", "status", "no_show", 10), ("D", "E2", "status", "attended", 12)])
    st = r[("E2", "status")]
    assert st["value"] == "no_show" and "draft" in st["basis"]
    assert r[("E2", "minutes")]["value"] == "0" and r[("E2", "therapy_day")]["value"] == "false"


def test_clinical_note_beats_scheduling_export_on_presence():
    r = _setup([("X", "scheduling_export"), ("N", "clinical_note")],
               [("X", "E3", "status", "attended", 18), ("N", "E3", "status", "patient_absent", 8)])
    assert r[("E3", "status")]["value"] == "patient_absent"
    assert r[("E3", "minutes")]["value"] == "0"


def test_two_signed_notes_disagree_is_unresolved_with_range():
    r = _setup([("A", "clinical_note"), ("B", "clinical_note")],
               [("A", "E4", "contact_interval", "09:00–09:50", 7), ("B", "E4", "contact_interval", "09:10–09:50", 7),
                ("A", "E4", "status", "attended", 7), ("B", "E4", "status", "attended", 7)])
    m = r[("E4", "minutes")]
    assert m["status"] == "unresolved" and m["value"] is None
    assert r[("E4", "minutes_range")]["value"] == "40-50"
    assert r[("E4", "therapy_day")]["value"] == "true"


def test_split_call_in_one_document_is_one_session():
    r = _setup([("V", "clinical_note")],
               [("V", "E5", "contact_interval", "13:00–13:20", 17), ("V", "E5", "contact_interval", "13:30–13:55", 18),
                ("V", "E5", "status", "attended_partial", 7)])
    assert r[("E5", "minutes")]["value"] == "45"


def test_roster_window_clips_group_schedule_and_break_removed():
    r = _setup([("N", "clinical_note"), ("R", "attendance_register")],
               [("N", "E6", "contact_interval", "10:00–11:30", 5), ("N", "E6", "nontherapeutic_interval", "10:45–11:00", 8),
                ("R", "E6", "arrival", "10:15", 6), ("R", "E6", "departure", "11:15", 6), ("R", "E6", "status", "attended", 6)])
    assert r[("E6", "minutes")]["value"] == "45"
    assert r[("E6", "minutes_with_breaks")]["value"] == "60"


def test_partial_presence():
    r = _setup([("F", "clinical_note")],
               [("F", "E7", "contact_interval", "13:00–13:45", 6), ("F", "E7", "patient_present_interval", "13:15–13:45", 7),
                ("F", "E7", "status", "attended_partial", 7)])
    assert r[("E7", "minutes")]["value"] == "30"


def test_missing_departure_is_not_stated():
    r = _setup([("R", "attendance_register")],
               [("R", "E8", "arrival", "10:00", 6), ("R", "E8", "status", "attended", 6)])
    m = r[("E8", "minutes")]
    assert m["value"] is None and m["status"] == "unresolved" and "not stated" in m["basis"]
    assert r[("E8", "therapy_day")]["value"] == "true"


def test_measure_copy_is_not_distinct():
    r = _setup([("Q", "measure"), ("I", "admin")],
               [("Q", "measure:Q:0", "score_name", "PHQ-9", 8), ("Q", "measure:Q:0", "score_value", "14", 8),
                ("Q", "measure:Q:0", "completed_on", "2026-01-16", 7), ("Q", "measure:Q:0", "source_form", "F1", 6),
                ("I", "measure:I:0", "score_name", "PHQ-9", 13), ("I", "measure:I:0", "score_value", "14", 13),
                ("I", "measure:I:0", "completed_on", "2026-01-16", 13), ("I", "measure:I:0", "copy_of", "F1", 17)])
    assert r[("measure:Q:0", "distinct")]["value"] == "true"
    assert r[("measure:I:0", "distinct")]["value"] == "false"


def test_documents_per_encounter_listed():
    r = _setup([("A", "clinical_note"), ("B", "clinical_note")],
               [("A", "E9", "status", "attended", 1), ("B", "E9", "status", "attended", 1)])
    assert r[("E9", "documents")]["value"] == "A,B"


def test_lower_rank_source_breaks_tie_between_equal_notes():
    r = _setup([("A", "clinical_note"), ("B", "clinical_note"), ("X", "scheduling_export")],
               [("A", "E10", "service_type", "group", 4), ("B", "E10", "service_type", "family", 8),
                ("X", "E10", "service_type", "family", 18), ("A", "E10", "status", "attended", 5)])
    st = r[("E10", "service_type")]
    assert st["value"] == "family" and st["status"] == "resolved" and "2 of 3" in st["basis"]


def test_still_tied_stays_unresolved():
    r = _setup([("A", "clinical_note"), ("B", "clinical_note")],
               [("A", "E11", "service_type", "group", 4), ("B", "E11", "service_type", "family", 8)])
    assert r[("E11", "service_type")]["status"] == "unresolved"


def test_conflict_range_uses_each_documents_own_present_interval():
    r = _setup([("A", "clinical_note"), ("B", "clinical_note")],
               [("A", "E12", "contact_interval", "09:00–09:50", 7), ("B", "E12", "contact_interval", "09:10–09:50", 7),
                ("B", "E12", "patient_present_interval", "09:10–09:50", 7),
                ("A", "E12", "status", "attended", 7), ("B", "E12", "status", "attended", 7)])
    assert r[("E12", "minutes_range")]["value"] == "40-50"


def test_scheduling_fact_is_one_vote_per_document_not_ladder():
    # register misreads the type; draft has it right; 1:1 tie stays unresolved instead of ladder-picking the register
    r = _setup([("G", "attendance_register"), ("D", "draft")],
               [("G", "E13", "service_type", "collateral", 16), ("D", "E13", "service_type", "group", 10),
                ("G", "E13", "status", "no_show", 10), ("D", "E13", "status", "attended", 12)])
    assert r[("E13", "service_type")]["status"] == "unresolved"
    assert r[("E13", "status")]["value"] == "no_show"          # presence still follows the ladder


def test_scheduling_fact_majority_wins_across_ranks():
    r = _setup([("G", "attendance_register"), ("D", "draft"), ("X", "scheduling_export")],
               [("G", "E14", "service_type", "collateral", 16), ("D", "E14", "service_type", "group", 10),
                ("X", "E14", "service_type", "group", 18)])
    assert r[("E14", "service_type")]["value"] == "group"
