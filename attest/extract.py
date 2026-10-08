"""Prompt, JSON schema, few-shot examples. One model call per document.

The model fills a form. Code flattens the form into claims rows.
Nothing the model returns is rejected: unknown keys land in extra as unmapped.
"""

import json
import os
import time

MODEL = os.environ.get("ATTEST_MODEL", "claude-haiku-5-5")
TEMPERATURE = 0

DOC_TYPES = ["clinical_note", "attendance_register", "scheduling_export", "correction",
             "retransmission", "treatment_plan", "measure", "billing", "draft", "admin"]
SERVICE_TYPES = ["individual", "group", "family", "medication", "collateral", "coordination", "other"]
STATUSES = ["attended", "attended_partial", "no_show", "patient_cancelled", "clinic_cancelled",
            "patient_absent", "scheduled"]

_V = {"type": "object", "properties": {"value": {"type": "string"}, "line": {"type": "integer"}},
      "required": ["value", "line"]}
_VL = {"type": "array", "items": _V}

HEADER_FIELDS = ["doc_id", "clinic", "patient_name", "mrn", "doc_type", "signed_by", "signed_at",
                 "corrects_doc", "copy_of", "unsigned"]
ENCOUNTER_FIELDS = ["encounter", "service_date", "service_type", "scheduled_start", "scheduled_end",
                    "arrival", "departure", "contact_intervals", "patient_present_intervals",
                    "nontherapeutic_intervals", "status", "patient_present", "summary"]
PLAN_FIELDS = ["effective_from", "effective_to", "min_days_per_week", "min_minutes_per_week",
               "counting_types", "excluded_types", "goals"]
MEASURE_FIELDS = ["score_name", "score_value", "completed_on", "source_form", "copy_of"]

SCHEMA = {
    "type": "object",
    "properties": {
        "header": {"type": "object", "properties": {k: _V for k in HEADER_FIELDS},
                   "required": ["doc_id", "doc_type"]},
        "encounters": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "encounter": _V, "service_date": _V, "service_type": _V,
                "scheduled_start": _V, "scheduled_end": _V, "arrival": _V, "departure": _V,
                "contact_intervals": _VL, "patient_present_intervals": _VL,
                "nontherapeutic_intervals": _VL,
                "status": _V, "patient_present": _V, "summary": _V,
            }}},
        "plan": {"type": "object", "properties": {
            "effective_from": _V, "effective_to": _V, "min_days_per_week": _V,
            "min_minutes_per_week": _V, "counting_types": _VL, "excluded_types": _VL, "goals": _VL}},
        "measures": {"type": "array", "items": {"type": "object",
                     "properties": {k: _V for k in MEASURE_FIELDS}}},
        "extra": {"type": "array", "items": {"type": "object", "properties": {
            "field": {"type": "string"}, "value": {"type": "string"}, "line": {"type": "integer"},
            "about": {"type": "string"}}, "required": ["field", "value", "line"]}},
    },
    "required": ["header", "encounters", "extra"],
}

SYSTEM = f"""You read one clinical or administrative document and fill a form. You return only the form.

Rules:
- Every value carries the line number it came from. Lines are numbered in the input.
- Omit any field the document does not state. Never return empty strings, 0, or null for a missing fact.
- Copy times as HH:MM. Copy ranges as HH:MM–HH:MM. Copy dates as YYYY-MM-DD.
- One document may describe several encounters (a schedule export, an attendance register). Return one encounters item per appointment the document describes. Use the document's encounter ID (for example HG-E110) when it gives one.
- header.doc_type is one of: {", ".join(DOC_TYPES)}. A correction document is "correction". A resent or retransmitted copy of an earlier document is "retransmission". An unsigned auto-generated note or a billing extract is "draft" or "billing". A cover sheet, scheduling log, authorization letter, or import receipt is "admin".
- header.corrects_doc: the document ID this one corrects, when it says so. header.copy_of: the document ID this one is a copy or retransmission of, when it says so.
- header.unsigned: "true" when the document has no clinician signature.
- service_type is one of: {", ".join(SERVICE_TYPES)}. Medication management is "medication". A contact with a family member where the patient was absent is "collateral". A call between professionals with no patient is "coordination".
- status is one of: {", ".join(STATUSES)}.
- contact_intervals: the intervals the service actually ran with the patient (a video call that dropped and rejoined has two).
- patient_present_intervals: when the patient was present for only part of the service, the part they were present for.
- nontherapeutic_intervals: breaks or other intervals the document says had no therapy.
- summary: two or three sentences on what the document says happened clinically for this encounter, including the stated reason for the visit if given. Facts only, no interpretation.
- plan: only for a treatment plan. counting_types and excluded_types list the service types the plan says do or do not count toward its goal.
- measures: any questionnaire score the document states. If the document says the score is copied or imported from an earlier form, set copy_of to that form or document and keep the original completion date.
- extra: any other stated fact that does not fit a slot. about: the encounter ID or "document".
"""

FEWSHOT = [
    {"role": "user", "content": "1: Document ID: ZZ-D900\n2: NORTHSHORE COUNSELING\n3: Attendance correction | Entered March 3, 2026\n4: Patient: Sam Doe | MRN: NS-M017\n5: Applies to group encounter NS-E410, service date March 2, 2026\n6: \n7: Correction: Patient departure for NS-E410 is 14:20, replacing the original roster value of 14:30.\n8: The original roster ZZ-D899 retained the scheduled closing time.\n9: \n10: Electronically signed: Ana Ruiz, LCSW | March 3, 2026, 09:12"},
    {"role": "assistant", "content": json.dumps({
        "header": {"doc_id": {"value": "ZZ-D900", "line": 1}, "clinic": {"value": "Northshore Counseling", "line": 2},
                   "patient_name": {"value": "Sam Doe", "line": 4}, "mrn": {"value": "NS-M017", "line": 4},
                   "doc_type": {"value": "correction", "line": 3}, "corrects_doc": {"value": "ZZ-D899", "line": 8},
                   "signed_by": {"value": "Ana Ruiz, LCSW", "line": 10}, "signed_at": {"value": "2026-03-03 09:12", "line": 10}},
        "encounters": [{"encounter": {"value": "NS-E410", "line": 5}, "service_date": {"value": "2026-03-02", "line": 5},
                        "service_type": {"value": "group", "line": 5}, "departure": {"value": "14:20", "line": 7}}],
        "extra": []})},
    {"role": "user", "content": "1: Document ID: ZZ-D910\n2: NORTHSHORE COUNSELING | Attendance register extract\n3: Patient: Sam Doe | MRN: NS-M017\n4: \n5: Date | Encounter | Service | Scheduled | Arrived | Departed | Disposition\n6: 2026-03-09 | NS-E412 | Skills group | 10:00–11:30 | 10:10 | 11:30 | Attended\n7: 2026-03-11 | NS-E413 | Individual | 13:00–13:45 | — | — | No show\n8: \n9: March 9 note: group break 10:45–11:00 with no therapy.\n10: Prepared by desk staff, March 12, 2026."},
    {"role": "assistant", "content": json.dumps({
        "header": {"doc_id": {"value": "ZZ-D910", "line": 1}, "clinic": {"value": "Northshore Counseling", "line": 2},
                   "patient_name": {"value": "Sam Doe", "line": 3}, "mrn": {"value": "NS-M017", "line": 3},
                   "doc_type": {"value": "attendance_register", "line": 2}, "unsigned": {"value": "true", "line": 10}},
        "encounters": [
            {"encounter": {"value": "NS-E412", "line": 6}, "service_date": {"value": "2026-03-09", "line": 6},
             "service_type": {"value": "group", "line": 6}, "scheduled_start": {"value": "10:00", "line": 6},
             "scheduled_end": {"value": "11:30", "line": 6}, "arrival": {"value": "10:10", "line": 6},
             "departure": {"value": "11:30", "line": 6}, "status": {"value": "attended", "line": 6},
             "nontherapeutic_intervals": [{"value": "10:45–11:00", "line": 9}]},
            {"encounter": {"value": "NS-E413", "line": 7}, "service_date": {"value": "2026-03-11", "line": 7},
             "service_type": {"value": "individual", "line": 7}, "scheduled_start": {"value": "13:00", "line": 7},
             "scheduled_end": {"value": "13:45", "line": 7}, "status": {"value": "no_show", "line": 7}}],
        "extra": []})},
]

TOOL = {"name": "record_document", "description": "Record the filled form for this document.",
        "input_schema": SCHEMA}


def number_lines(text):
    return "\n".join(f"{i}: {ln}" for i, ln in enumerate(text.splitlines(), start=1))


def call_model(client, text, fewshot=True):
    """Returns (form_dict, tokens_in, tokens_out, seconds)."""
    msgs = list(FEWSHOT) if fewshot else []
    msgs.append({"role": "user", "content": number_lines(text)})
    t0 = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=4000, temperature=TEMPERATURE, system=SYSTEM,
        tools=[TOOL], tool_choice={"type": "tool", "name": "record_document"}, messages=msgs)
    dt = time.time() - t0
    form = None
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            form = block.input
            break
    if form is None:
        raise ValueError("model returned no form")
    return form, resp.usage.input_tokens, resp.usage.output_tokens, dt


def _v(item):
    """A {value, line} item -> (value, line). Tolerates a bare string."""
    if isinstance(item, dict):
        return str(item.get("value", "")).strip(), item.get("line")
    return str(item).strip(), None


def flatten(form, fallback_doc_id):
    """Form -> (doc_id, clinic, patient, rows, flags). rows: (subject, field, value, line)."""
    rows, flags = [], []
    header = form.get("header", {}) or {}
    doc_id = _v(header.get("doc_id"))[0] if header.get("doc_id") else fallback_doc_id
    clinic = _v(header.get("clinic"))[0] if header.get("clinic") else "unknown"
    patient = _v(header.get("mrn"))[0] if header.get("mrn") else "unknown"
    if patient == "unknown":
        flags.append("no_mrn")
    doc_subject = f"doc:{doc_id}"

    for k, item in header.items():
        val, line = _v(item)
        if not val:
            continue
        if k in HEADER_FIELDS:
            rows.append((doc_subject, k, val, line))
        else:
            rows.append((doc_subject, f"unmapped:{k}", val, line)); flags.append(f"unmapped:{k}")

    for i, enc in enumerate(form.get("encounters", []) or []):
        eid = _v(enc.get("encounter"))[0] if enc.get("encounter") else f"enc:{doc_id}:{i}"
        for k, item in enc.items():
            if k in ("contact_intervals", "patient_present_intervals", "nontherapeutic_intervals",) and isinstance(item, list):
                for it in item:
                    val, line = _v(it)
                    if val:
                        rows.append((eid, k[:-1], val, line))  # contact_interval, one row each
                continue
            val, line = _v(item)
            if not val:
                continue
            if k in ENCOUNTER_FIELDS:
                rows.append((eid, k, val, line))
            else:
                rows.append((eid, f"unmapped:{k}", val, line)); flags.append(f"unmapped:{k}")

    plan = form.get("plan") or {}
    if plan:
        ps = f"plan:{doc_id}"
        for k, item in plan.items():
            if isinstance(item, list):
                for it in item:
                    val, line = _v(it)
                    if val:
                        rows.append((ps, k[:-1] if k.endswith("s") else k, val, line))
                continue
            val, line = _v(item)
            if val:
                rows.append((ps, k if k in PLAN_FIELDS else f"unmapped:{k}", val, line))

    for i, m in enumerate(form.get("measures", []) or []):
        ms = f"measure:{doc_id}:{i}"
        for k, item in m.items():
            val, line = _v(item)
            if val:
                rows.append((ms, k if k in MEASURE_FIELDS else f"unmapped:{k}", val, line))

    for x in form.get("extra", []) or []:
        about = x.get("about") or "document"
        subj = doc_subject if about == "document" else about
        rows.append((subj, f"extra:{x.get('field','')}", str(x.get("value", "")), x.get("line")))

    return doc_id, clinic, patient, rows, sorted(set(flags))
