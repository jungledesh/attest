"""Tested functions over resolved. Returns numbers, rows used, unresolved items. No model.

Every function takes (con, clinic, patient, ...) and returns a dict. Each value that
matters carries the subject it came from so the answer can cite claim rows.
"""

from collections import defaultdict
from datetime import date, timedelta

from . import db

INELIGIBLE_STATUS = {"no_show", "patient_cancelled", "clinic_cancelled", "patient_absent"}


def _d(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _load(con, clinic, patient):
    """resolved rows -> {subject: {field: row}}; summaries kept as list."""
    enc = defaultdict(dict)
    for r in db.resolved_for_patient(con, clinic, patient):
        enc[r["subject"]][r["field"]] = dict(r)
    return enc


def _val(e, f):
    r = e.get(f)
    return r["value"] if r else None


def plan_rules(enc):
    """Plan subjects -> list of {from, to, min_days, min_minutes, counting, excluded, subject}."""
    out = []
    for s, e in enc.items():
        if not s.startswith("plan:"):
            continue
        out.append({"subject": s,
                    "from": _d(_val(e, "effective_from")), "to": _d(_val(e, "effective_to")),
                    "min_days": _int(_val(e, "min_days_per_week")),
                    "min_minutes": _int(_val(e, "min_minutes_per_week")),
                    "counting": set(_list_vals(e, "counting_type")),
                    "excluded": set(_list_vals(e, "excluded_type"))})
    return out


def _list_vals(e, field):
    """List fields are stored as one row holding a JSON array."""
    import json
    v = _val(e, field)
    if not v:
        return []
    try:
        x = json.loads(v)
        return x if isinstance(x, list) else [v]
    except (TypeError, ValueError):
        return [v]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _load_full(con, clinic, patient):
    enc = defaultdict(lambda: {"_lists": defaultdict(list)})
    for r in db.resolved_for_patient(con, clinic, patient):
        d = dict(r)
        e = enc[d["subject"]]
        e["_lists"][d["field"]].append(d["value"])
        e[d["field"]] = d
    return enc


def plan_in_effect(plans, day):
    for p in plans:
        if (p["from"] is None or day >= p["from"]) and (p["to"] is None or day <= p["to"]):
            return p
    return None


def _doc_types(con):
    return {r[0]: r[1] for r in con.execute("SELECT doc_id, value FROM claims WHERE field='doc_type' AND subject LIKE 'doc:%'")}


def encounters(con, clinic, patient, start=None, end=None):
    """Every encounter with its resolved facts, filtered to the date range."""
    enc = _load_full(con, clinic, patient)
    plans = plan_rules(enc)
    dtypes = _doc_types(con)
    out = []
    for s, e in enc.items():
        if s.startswith(("plan:", "measure:", "doc:")):
            continue
        day = _d(_val(e, "service_date"))
        if day is None:
            continue
        if start and day < start or end and day > end:
            continue
        stype = _val(e, "service_type")
        status = _val(e, "status")
        plan = plan_in_effect(plans, day)
        eligible, why = True, "counts toward plan"
        if status in INELIGIBLE_STATUS:
            eligible, why = False, f"status {status}"
        elif plan and stype in plan["excluded"]:
            eligible, why = False, f"{stype} is excluded by the treatment plan ({plan['subject']})"
        elif plan and plan["counting"] and stype not in plan["counting"]:
            eligible, why = False, f"{stype} is not a counting type in the treatment plan ({plan['subject']})"
        elif stype is None:
            eligible, why = False, "service type not stated or not settled"
        elif status is None and _val(e, "minutes") in (None, "0"):
            eligible, why = False, "no attendance or minutes stated"
        m = e.get("minutes", {})
        out.append({
            "subject": s, "date": day.isoformat(), "service_type": stype, "status": status,
            "minutes": _int(m.get("value")), "minutes_status": m.get("status"), "minutes_basis": m.get("basis"),
            "minutes_with_breaks": _int(_val(e, "minutes_with_breaks")),
            "minutes_range": _val(e, "minutes_range"),
            "therapy_day": _val(e, "therapy_day"),
            "eligible": eligible, "why": why,
            "documents": (_val(e, "documents") or "").split(",") if _val(e, "documents") else [],
            "document_types": {d: dtypes.get(d) for d in ((_val(e, "documents") or "").split(",") if _val(e, "documents") else [])},
            "modality": _val(e, "modality"),
            "arrival": _val(e, "arrival"), "departure": _val(e, "departure"),
            "contact_intervals": _list_vals(e, "contact_interval"),
            "patient_present_intervals": _list_vals(e, "patient_present_interval"),
            "nontherapeutic_intervals": _list_vals(e, "nontherapeutic_interval"),
            "other_facts": {f.split(":", 1)[1]: r["value"] for f, r in e.items()
                            if isinstance(r, dict) and f.startswith("extra:")},
            "departure_basis": (e.get("departure") or {}).get("basis"),
            "status_basis": (e.get("status") or {}).get("basis"),
            "fields": {f: {"value": r["value"], "basis": r["basis"], "status": r["status"], "claim_rows": r["claim_rows"]}
                       for f, r in e.items() if f not in ("_lists",) and isinstance(r, dict)
                       and f in ("arrival", "departure", "status", "service_type", "minutes", "minutes_range", "documents")},
        })
    out.sort(key=lambda x: (x["date"], x["subject"]))
    return out


def sessions(con, clinic, patient, start, end):
    encs = encounters(con, clinic, patient, start, end)
    counted = [e for e in encs if e["eligible"]]
    by_type = defaultdict(int)
    for e in counted:
        by_type[e["service_type"]] += 1
    return {"patient": patient, "clinic": clinic, "start": start.isoformat(), "end": end.isoformat(),
            "total": len(counted), "by_type": dict(by_type),
            "distinct_days": len({e["date"] for e in counted}),
            "counted": [{k: e[k] for k in ("subject", "date", "service_type", "status", "minutes", "documents")} for e in counted],
            "excluded": [{k: e[k] for k in ("subject", "date", "service_type", "status", "why", "documents")} for e in encs if not e["eligible"]],
            "multi_document": [{"subject": e["subject"], "date": e["date"], "documents": e["documents"]} for e in counted if len(e["documents"]) > 1],
            "unresolved": [{"subject": e["subject"], "date": e["date"], "basis": e["minutes_basis"], "range": e["minutes_range"]}
                           for e in counted if e["minutes_status"] == "unresolved"]}


def _week_start(d):
    return d - timedelta(days=d.weekday())


def minutes_by_week(con, clinic, patient, start, end):
    encs = [e for e in encounters(con, clinic, patient, start, end) if e["eligible"]]
    weeks = defaultdict(lambda: {"minutes_low": 0, "minutes_high": 0, "minutes_with_breaks": 0, "days": set(),
                                 "encounters": [], "documents": set(), "unresolved": [], "not_stated": []})
    for e in encs:
        wk = _week_start(_d(e["date"]))
        w = weeks[wk]
        w["encounters"].append(e["subject"])
        w["documents"].update(e["documents"])
        if e["therapy_day"] == "true":
            w["days"].add(e["date"])
        if e["minutes"] is not None:
            w["minutes_low"] += e["minutes"]; w["minutes_high"] += e["minutes"]
            w["minutes_with_breaks"] += e["minutes_with_breaks"] or e["minutes"]
        elif e["minutes_range"]:
            lo, hi = (int(x) for x in e["minutes_range"].split("-"))
            w["minutes_low"] += lo; w["minutes_high"] += hi; w["minutes_with_breaks"] += hi
            w["unresolved"].append({"subject": e["subject"], "date": e["date"], "range": e["minutes_range"], "basis": e["minutes_basis"]})
        else:
            w["not_stated"].append({"subject": e["subject"], "date": e["date"], "basis": e["minutes_basis"]})
    rows = []
    for wk in sorted(weeks):
        w = weeks[wk]
        rows.append({"week_start": wk.isoformat(), "week_end": (wk + timedelta(days=6)).isoformat(),
                     "therapy_days": len(w["days"]), "minutes_low": w["minutes_low"], "minutes_high": w["minutes_high"],
                     "minutes_with_breaks": w["minutes_with_breaks"],
                     "hours_low": round(w["minutes_low"] / 60, 2), "hours_high": round(w["minutes_high"] / 60, 2),
                     "encounters": w["encounters"], "documents": sorted(w["documents"]),
                     "unresolved": w["unresolved"], "not_stated": w["not_stated"]})
    tot_lo = sum(r["minutes_low"] for r in rows); tot_hi = sum(r["minutes_high"] for r in rows)
    return {"patient": patient, "start": start.isoformat(), "end": end.isoformat(), "weeks": rows,
            "total_minutes_low": tot_lo, "total_minutes_high": tot_hi,
            "total_hours_low": round(tot_lo / 60, 2), "total_hours_high": round(tot_hi / 60, 2),
            "total_minutes_with_breaks": sum(r["minutes_with_breaks"] for r in rows),
            "break_note": "minutes exclude intervals the documents mark as nontherapeutic; minutes_with_breaks keeps them. The plan says 'patient-present therapy' and does not say which to use.",
            "per_encounter": [{k: e[k] for k in ("subject", "date", "service_type", "minutes", "minutes_with_breaks", "minutes_range", "minutes_basis", "documents")} for e in encs]}


def plan_check(con, clinic, patient, start, end):
    enc = _load_full(con, clinic, patient)
    plans = plan_rules(enc)
    mbw = minutes_by_week(con, clinic, patient, start, end)
    out = []
    for w in mbw["weeks"]:
        plan = plan_in_effect(plans, _d(w["week_start"])) or plan_in_effect(plans, _d(w["week_end"]))
        if not plan:
            out.append({**w, "goal": None, "verdict": "cannot_determine", "reason": "no treatment plan found for this week"})
            continue
        goal = {"min_days": plan["min_days"], "min_minutes": plan["min_minutes"], "subject": plan["subject"]}
        days_ok = plan["min_days"] is None or w["therapy_days"] >= plan["min_days"]
        if w["not_stated"]:
            verdict, reason = "cannot_determine", f"{len(w['not_stated'])} attended encounter(s) with minutes not stated"
        elif plan["min_minutes"] is None:
            verdict, reason = ("met" if days_ok else "not_met"), "plan states days only"
        elif w["minutes_low"] >= plan["min_minutes"] and days_ok:
            verdict, reason = "met", f"{w['therapy_days']} days, {w['minutes_low']} min (low bound) vs goal {plan['min_days']} days, {plan['min_minutes']} min"
        elif w["minutes_high"] < plan["min_minutes"] or not days_ok:
            verdict, reason = "not_met", f"{w['therapy_days']} days, {w['minutes_high']} min (high bound) vs goal {plan['min_days']} days, {plan['min_minutes']} min"
        else:
            verdict, reason = "cannot_determine", f"minutes {w['minutes_low']}-{w['minutes_high']} straddle the {plan['min_minutes']} goal; unresolved: {w['unresolved']}"
        # break interpretation can flip the verdict
        flip = None
        if plan["min_minutes"] is not None and verdict == "not_met" and w["minutes_with_breaks"] >= plan["min_minutes"] and days_ok:
            flip = f"met if break time counted ({w['minutes_with_breaks']} min)"
        out.append({**w, "goal": goal, "verdict": verdict, "reason": reason, "if_breaks_counted": flip})
    return {"patient": patient, "start": start.isoformat(), "end": end.isoformat(), "weeks": out,
            "plans": [{"subject": p["subject"], "from": p["from"].isoformat() if p["from"] else None,
                       "to": p["to"].isoformat() if p["to"] else None, "min_days": p["min_days"], "min_minutes": p["min_minutes"],
                       "counting": sorted(p["counting"]), "excluded": sorted(p["excluded"])} for p in plans]}


def consecutive_below(con, start, end):
    """All patients: two or more consecutive weeks below goal, and who depends on unresolved fields."""
    out = {"below": [], "depends_on_unresolved": [], "no_plan": [], "patients_checked": 0}
    for p in db.patients(con):
        out["patients_checked"] += 1
        pc = plan_check(con, p["clinic"], p["patient"], start, end)
        if not pc["plans"]:
            out["no_plan"].append(p["patient"]); continue
        run, maybe = 0, 0
        hit, maybe_hit = False, False
        for w in pc["weeks"]:
            if w["verdict"] == "not_met":
                run += 1; maybe += 1
            elif w["verdict"] == "cannot_determine":
                run = 0; maybe += 1
            else:
                run = 0; maybe = 0
            hit |= run >= 2; maybe_hit |= maybe >= 2
        if hit:
            out["below"].append({"clinic": p["clinic"], "patient": p["patient"],
                                 "weeks": [(w["week_start"], w["verdict"]) for w in pc["weeks"]]})
        elif maybe_hit:
            out["depends_on_unresolved"].append({"clinic": p["clinic"], "patient": p["patient"],
                                                 "weeks": [(w["week_start"], w["verdict"], w["reason"]) for w in pc["weeks"]]})
    return out


def day(con, clinic, patient, d):
    encs = encounters(con, clinic, patient, d, d)
    contacts = [e for e in encs if e["eligible"]]
    mins = [e["minutes"] for e in contacts]
    total = sum(m for m in mins if m is not None)
    return {"patient": patient, "date": d.isoformat(), "therapy_contacts": len(contacts),
            "therapy_minutes": total if all(m is not None for m in mins) else None,
            "therapy_minutes_with_breaks": sum((e["minutes_with_breaks"] or 0) for e in contacts),
            "encounters": encs}


def timeline(con, clinic, patient, start=None, end=None):
    enc = _load_full(con, clinic, patient)
    items = []
    for s, e in enc.items():
        if s.startswith("measure:"):
            items.append({"kind": "measure", "date": _val(e, "completed_on"), "subject": s,
                          "score_name": _val(e, "score_name"), "score_value": _val(e, "score_value"),
                          "distinct": _val(e, "distinct"), "basis": e.get("distinct", {}).get("basis"),
                          "source_form": _val(e, "source_form")})
        elif not s.startswith(("plan:", "doc:")):
            d0 = _val(e, "service_date")
            for f, r in e.items():
                if f.startswith("summary:"):
                    items.append({"kind": "summary", "date": d0, "subject": s, "doc": f.split(":", 1)[1],
                                  "service_type": _val(e, "service_type"), "status": _val(e, "status"), "text": r["value"]})
    items = [i for i in items if i["date"] and (not start or _d(i["date"]) >= start) and (not end or _d(i["date"]) <= end)]
    items.sort(key=lambda i: (i["date"], i["kind"] != "measure", i["subject"]))
    distinct = [i for i in items if i["kind"] == "measure" and i["distinct"] == "true"]
    copied = [i for i in items if i["kind"] == "measure" and i["distinct"] != "true"]
    return {"patient": patient, "items": items, "distinct_measures": distinct, "copied_measures": copied,
            "progress": _progress(distinct, copied, items)}


def _progress(distinct, copied, items):
    """What the record supports about progress, and what it cannot. Computed, not judged."""
    supported, not_supported = [], []
    by_name = defaultdict(list)
    for m in distinct:
        try:
            by_name[m["score_name"]].append((m["date"], int(m["score_value"]), m["subject"]))
        except (TypeError, ValueError):
            pass
    trends = []
    for name, pts in by_name.items():
        pts.sort()
        if len(pts) >= 2:
            first, last = pts[0], pts[-1]
            days = (_d(last[0]) - _d(first[0])).days
            direction = "decreased" if last[1] < first[1] else "increased" if last[1] > first[1] else "unchanged"
            trends.append({"instrument": name, "n_distinct": len(pts), "first": first[1], "first_date": first[0],
                           "last": last[1], "last_date": last[0], "change": last[1] - first[1], "days": days,
                           "direction": direction, "subjects": [p[2] for p in pts]})
            supported.append(f"{name} {direction} from {first[1]} ({first[0]}) to {last[1]} ({last[0]}) across "
                             f"{len(pts)} distinct assessments over {days} days")
        else:
            not_supported.append(f"a trend for {name}: only {len(pts)} distinct assessment on record")
    if copied:
        supported.append(f"{len(copied)} measure record(s) are copies of an earlier form and are not counted as new assessments")
    summaries = [i for i in items if i["kind"] == "summary"]
    if summaries:
        supported.append(f"{len(summaries)} clinical summaries describe the course in words; these are clinician accounts, not measurements")
    if len(by_name) == 1:
        not_supported.append(f"change in any domain other than what {next(iter(by_name))} measures: it is the only instrument on record")
    if not by_name:
        not_supported.append("any measured change: no questionnaire scores on record")
    not_supported.append("item-level or symptom-specific change: only total scores are recorded")
    not_supported.append("a cause for any change: the record does not link scores to specific interventions")
    return {"trends": trends, "supported": supported, "not_supported": not_supported}


def plan_change(con, clinic, patient):
    enc = _load_full(con, clinic, patient)
    plans = sorted(plan_rules(enc), key=lambda p: p["from"] or date.min)
    if len(plans) < 2:
        return {"patient": patient, "plans": len(plans), "change": None,
                "note": "no plan change on record" if plans else "no treatment plan on record"}
    cut = plans[1]["from"]
    before = sessions(con, clinic, patient, plans[0]["from"] or date.min, cut - timedelta(days=1))
    after = sessions(con, clinic, patient, cut, plans[-1]["to"] or date.max)
    return {"patient": patient, "plans": len(plans), "change": cut.isoformat(), "before": before, "after": after}
