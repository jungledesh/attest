"""Prompt, JSON schema, few-shot examples. One model call per document.

The model fills a form. Code flattens the form into claims rows.
Nothing the model returns is rejected: unknown keys land in extra as unmapped.
"""

import json
import os
import time

MODEL = os.environ.get("ATTEST_MODEL", "claude-haiku-5-5")
# Current API exposes no temperature; sampling is the provider default. Stability is measured, not assumed.

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
ENCOUNTER_FIELDS = ["encounter", "service_date", "service_type", "modality", "scheduled_start", "scheduled_end",
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
                "encounter": _V, "service_date": _V, "service_type": _V, "modality": _V,
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

SYSTEM = f"""Read one clinical or administrative document. Fill the form. Return only the form.

- Every value carries the line number it came from. Lines are numbered in the input.
- Omit a field the document does not state. Never return "", 0, or null for a missing fact.
- Times as HH:MM. Ranges as HH:MM–HH:MM. Dates as YYYY-MM-DD.
- One document may describe several encounters. One encounters item per appointment. Use the document's own encounter ID when given.
- header.doc_type, one of: {", ".join(DOC_TYPES)}. A resent copy of an earlier document is "retransmission". An unsigned auto-generated note is "draft". A charge extract is "billing". Cover sheets, scheduling logs, authorization letters, import receipts are "admin".
- header.corrects_doc / header.copy_of: the other document's ID, only when the text states it. Never this document's own ID. Never a description.
- header.unsigned: "true" when no clinician signed.
- service_type, one of: {", ".join(SERVICE_TYPES)}. Medication management is "medication". Family member seen without the patient is "collateral". Professionals only, no patient, is "coordination".
- status, one of: {", ".join(STATUSES)}.
- modality: in_person, video, or telephone, when stated.
- contact_intervals: when the service ran with the patient. A dropped and rejoined call has two.
- patient_present_intervals: the part the patient was present for, when partial.
- nontherapeutic_intervals: breaks or other intervals the document says had no therapy.
- summary: two or three sentences on what happened clinically, with the stated reason for the visit. Facts only.
- plan: required for a treatment plan. min_days_per_week and min_minutes_per_week from the stated goal; counting_types and excluded_types as the plan lists them; effective_from and effective_to from the plan or episode dates. Not in extra.
- measures: required for every questionnaire score stated. One item per score. If the document says the score is copied from an earlier form, set copy_of and keep the original completion date. Not in extra.
- A status from a draft or unsigned document is still recorded as status.
- extra: any other stated fact. about: the encounter ID or "document".
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


def _as_tool_turns(pairs):
    """Few-shot pairs -> real tool_use / tool_result turns so the model mimics a tool call, not text."""
    out = []
    for i, (user, assistant) in enumerate(pairs):
        out.append({"role": "user", "content": user["content"]})
        out.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"toolu_fs{i}",
                                                       "name": TOOL["name"], "input": json.loads(assistant["content"])}]})
        out.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"toolu_fs{i}", "content": "recorded"}]})
    return out


FEWSHOT += [
    {"role": "user", "content": "1: Document ID: ZZ-D920\n2: NORTHSHORE COUNSELING | Outpatient treatment plan\n3: Patient: Sam Doe | MRN: NS-M017\n4: Episode dates: 2026-03-02 through 2026-03-27\n5: Signed: Ana Ruiz, LCSW, 2026-03-02 13:05\n6: \n7: Participation goal: at least 2 therapy days and at least 120 minutes of patient-present therapy in each Monday–Sunday week. Individual and group therapy count. Medication visits do not.\n8: \n9: Goal 1: resume a morning routine.\n10: PHQ-9 completed by patient 2026-03-02: total 16."},
    {"role": "assistant", "content": json.dumps({
        "header": {"doc_id": {"value": "ZZ-D920", "line": 1}, "clinic": {"value": "Northshore Counseling", "line": 2},
                   "patient_name": {"value": "Sam Doe", "line": 3}, "mrn": {"value": "NS-M017", "line": 3},
                   "doc_type": {"value": "treatment_plan", "line": 2}, "signed_by": {"value": "Ana Ruiz, LCSW", "line": 5},
                   "signed_at": {"value": "2026-03-02 13:05", "line": 5}},
        "encounters": [],
        "plan": {"effective_from": {"value": "2026-03-02", "line": 4}, "effective_to": {"value": "2026-03-27", "line": 4},
                 "min_days_per_week": {"value": "2", "line": 7}, "min_minutes_per_week": {"value": "120", "line": 7},
                 "counting_types": [{"value": "individual", "line": 7}, {"value": "group", "line": 7}],
                 "excluded_types": [{"value": "medication", "line": 7}],
                 "goals": [{"value": "resume a morning routine", "line": 9}]},
        "measures": [{"score_name": {"value": "PHQ-9", "line": 10}, "score_value": {"value": "16", "line": 10},
                      "completed_on": {"value": "2026-03-02", "line": 10}}],
        "extra": []})},
]

FEWSHOT_TURNS = _as_tool_turns([(FEWSHOT[0], FEWSHOT[1]), (FEWSHOT[2], FEWSHOT[3]), (FEWSHOT[4], FEWSHOT[5])])


def number_lines(text):
    return "\n".join(f"{i}: {ln}" for i, ln in enumerate(text.splitlines(), start=1))


def call_model(client, text, fewshot=True):
    """Returns (form_dict, tokens_in, tokens_out, seconds)."""
    msgs = list(FEWSHOT_TURNS) if fewshot else []
    msgs.append({"role": "user", "content": number_lines(text)})
    t0 = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=4000, system=SYSTEM,
        tools=[TOOL], tool_choice={"type": "tool", "name": "record_document"}, messages=msgs)
    dt = time.time() - t0
    form = None
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            form = block.input
            break
    if form is None:
        raise ValueError("model returned no form")
    form = _unwrap(form)
    return form, resp.usage.input_tokens, resp.usage.output_tokens, dt


def _unwrap(form):
    """If the model returned the whole form as one JSON string, parse it."""
    h = form.get("header")
    if isinstance(h, str):
        try:
            inner = json.loads(h)
            if isinstance(inner, dict) and "header" in inner:
                return inner
        except json.JSONDecodeError:
            pass
    return form


def _v(item):
    """A {value, line} item -> (value, line). Tolerates a bare string."""
    if isinstance(item, dict):
        return str(item.get("value", "")).strip(), item.get("line")
    return str(item).strip(), None


def _loads_repaired(text):
    """json.loads, and if that fails, append the closing brackets the text is missing (outside strings)
    and try once more. Repairs a reply cut off a character or two early. Returns None when still invalid."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    text = text.rstrip()
    while text and text[-1] in "]}":   # drop the trailing closers; they are re-derived below
        text = text[:-1].rstrip()
    stack, in_str, esc = [], False, False
    for ch in text:
        if in_str:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': in_str = False
            continue
        if ch == '"': in_str = True
        elif ch in "{[": stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack: stack.pop()
    fixed = text + ('"' if in_str else "") + "".join(reversed(stack))
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


def _obj(x, flags, what):
    """An item that should be a dict. A JSON string is parsed; anything else is kept as raw text."""
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        y = _loads_repaired(x)
        if isinstance(y, dict):
            return y
    flags.append(f"malformed:{what}")
    return {"unparsed": {"value": str(x), "line": None}}


def _lst(x, flags, what):
    """An item that should be a list of dicts. Tolerates: a JSON string for the list, a lone dict,
    and list elements that are themselves JSON strings (of a dict or of a list). Flattens one level."""
    if x is None:
        return []
    if isinstance(x, (dict, str)):
        x = [x]
    if not isinstance(x, list):
        flags.append(f"malformed:{what}")
        return [{"unparsed": {"value": str(x), "line": None}}]
    out = []
    for el in x:
        if isinstance(el, str):
            parsed = _loads_repaired(el)
            if parsed is None:
                flags.append(f"malformed:{what}")
                out.append({"unparsed": {"value": el, "line": None}})
                continue
            el = parsed
        if isinstance(el, list):
            out.extend(e for e in el if isinstance(e, dict))
        elif isinstance(el, dict):
            out.append(el)
        else:
            flags.append(f"malformed:{what}")
            out.append({"unparsed": {"value": str(el), "line": None}})
    return out


def flatten(form, fallback_doc_id):
    """Form -> (doc_id, clinic, patient, rows, flags). rows: (subject, field, value, line)."""
    rows, flags = [], []
    form = _obj(form, flags, "form")
    header = _obj(form.get("header", {}) or {}, flags, "header")
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

    for i, enc in enumerate(_lst(form.get("encounters"), flags, "encounters")):
        enc = _obj(enc, flags, "encounter")
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
        plan = _obj(plan, flags, "plan")
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

    for i, m in enumerate(_lst(form.get("measures"), flags, "measures")):
        m = _obj(m, flags, "measure")
        ms = f"measure:{doc_id}:{i}"
        for k, item in m.items():
            val, line = _v(item)
            if val:
                rows.append((ms, k if k in MEASURE_FIELDS else f"unmapped:{k}", val, line))

    for x in _lst(form.get("extra"), flags, "extra"):
        x = _obj(x, flags, "extra")
        about = x.get("about") or "document"
        subj = doc_subject if about == "document" else about
        rows.append((subj, f"extra:{x.get('field','')}", str(x.get("value", "")), x.get("line")))

    return doc_id, clinic, patient, rows, sorted(set(flags))
