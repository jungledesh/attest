"""Tests for extract.flatten. No model call."""

from attest.extract import flatten


def test_unknown_key_routes_to_unmapped_not_dropped():
    form = {"header": {"doc_id": {"value": "X-1", "line": 1}, "mrn": {"value": "M1", "line": 2},
                       "clinic": {"value": "C", "line": 1}, "doc_type": {"value": "clinical_note", "line": 1}},
            "encounters": [{"encounter": {"value": "E-1", "line": 3},
                            "end_time": {"value": "11:15", "line": 4}}],
            "extra": []}
    doc_id, clinic, patient, rows, flags = flatten(form, "fallback")
    assert (doc_id, clinic, patient) == ("X-1", "C", "M1")
    assert ("E-1", "unmapped:end_time", "11:15", 4) in rows
    assert "unmapped:end_time" in flags


def test_intervals_become_one_row_each_with_own_line():
    form = {"header": {"doc_id": {"value": "X-2", "line": 1}, "mrn": {"value": "M1", "line": 1},
                       "clinic": {"value": "C", "line": 1}, "doc_type": {"value": "clinical_note", "line": 1}},
            "encounters": [{"encounter": {"value": "E-2", "line": 2},
                            "contact_intervals": [{"value": "13:00–13:20", "line": 5},
                                                  {"value": "13:30–13:55", "line": 5}]}],
            "extra": []}
    _, _, _, rows, _ = flatten(form, "f")
    ci = [r for r in rows if r[1] == "contact_interval"]
    assert len(ci) == 2 and ci[0][2] == "13:00–13:20"


def test_missing_mrn_is_flagged():
    form = {"header": {"doc_id": {"value": "X-3", "line": 1}, "doc_type": {"value": "admin", "line": 1}},
            "encounters": [], "extra": []}
    _, _, patient, _, flags = flatten(form, "f")
    assert patient == "unknown" and "no_mrn" in flags


def test_plan_and_measure_subjects():
    form = {"header": {"doc_id": {"value": "P-1", "line": 1}, "mrn": {"value": "M1", "line": 1},
                       "clinic": {"value": "C", "line": 1}, "doc_type": {"value": "treatment_plan", "line": 1}},
            "encounters": [],
            "plan": {"min_minutes_per_week": {"value": "150", "line": 9},
                     "counting_types": [{"value": "group", "line": 10}, {"value": "individual", "line": 10}]},
            "measures": [{"score_name": {"value": "PHQ-9", "line": 12}, "score_value": {"value": "18", "line": 12}}],
            "extra": []}
    _, _, _, rows, _ = flatten(form, "f")
    assert ("plan:P-1", "min_minutes_per_week", "150", 9) in rows
    assert ("plan:P-1", "counting_type", "group", 10) in rows
    assert ("measure:P-1:0", "score_value", "18", 12) in rows
