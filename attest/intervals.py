"""Time math. Parse, merge, subtract HH:MM intervals. No DB, no model.

An interval is a pair of minutes since midnight, (start, end), end exclusive.
Every function here is pure. A value the record does not state is None, never 0.
"""

import re

_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*(?:–|—|-|to)\s*(\d{1,2}):(\d{2})")
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")

NOT_STATED = None


def parse_time(text):
    """'11:15' -> 675. Returns None when the text is not a clock time."""
    if text is None:
        return None
    m = _TIME.match(str(text))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def parse_range(text):
    """'10:00–11:30' -> (600, 690). Accepts en dash, em dash, hyphen, 'to'.
    Returns None when the text is not a range or the range is reversed."""
    if text is None:
        return None
    m = _RANGE.search(str(text))
    if not m:
        return None
    a = int(m.group(1)) * 60 + int(m.group(2))
    b = int(m.group(3)) * 60 + int(m.group(4))
    if b <= a:
        return None
    return (a, b)


def parse_ranges(texts):
    """List of range strings -> list of (start, end). Skips unparseable items."""
    out = []
    for t in texts or []:
        r = parse_range(t)
        if r:
            out.append(r)
    return out


def merge(intervals):
    """Union of intervals. Overlapping or touching intervals become one."""
    if not intervals:
        return []
    s = sorted(intervals)
    out = [list(s[0])]
    for a, b in s[1:]:
        if a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(x) for x in out]


def subtract(intervals, holes):
    """Remove every hole from every interval. Returns the remaining pieces."""
    pieces = merge(intervals)
    for ha, hb in merge(holes):
        nxt = []
        for a, b in pieces:
            if hb <= a or ha >= b:
                nxt.append((a, b))
                continue
            if a < ha:
                nxt.append((a, ha))
            if hb < b:
                nxt.append((hb, b))
        pieces = nxt
    return pieces


def total(intervals):
    """Sum of interval lengths in minutes."""
    return sum(b - a for a, b in merge(intervals))


def fmt(m):
    """675 -> '11:15'."""
    return f"{m // 60:02d}:{m % 60:02d}"


def patient_minutes(contact=None, arrival=None, departure=None,
                    present=None, nontherapeutic=None):
    """Patient-present therapy minutes for one encounter.

    contact:        list of (start, end) the service ran, e.g. two video call legs
    arrival/departure: single clock times from a roster, used when contact is empty
    present:        list of (start, end) the patient was in the room, if partial
    nontherapeutic: list of (start, end) with no therapy, e.g. a group break

    Returns a dict:
      minutes          int, or None when the record does not state enough to compute
      minutes_with_breaks  int, same but without subtracting nontherapeutic time
      basis            one line saying what was used
    """
    base = list(contact or [])
    used = "contact intervals"
    if not base:
        if arrival is None or departure is None:
            return {"minutes": NOT_STATED, "minutes_with_breaks": NOT_STATED,
                    "basis": "arrival or departure not stated"}
        if departure <= arrival:
            return {"minutes": NOT_STATED, "minutes_with_breaks": NOT_STATED,
                    "basis": "departure not after arrival"}
        base = [(arrival, departure)]
        used = f"roster {fmt(arrival)}–{fmt(departure)}"

    if present:
        base = [p for p in _intersect(base, present)]
        used += "; limited to patient-present intervals"

    with_breaks = total(base)
    without = total(subtract(base, nontherapeutic or []))
    if nontherapeutic:
        used += f"; {with_breaks - without} min nontherapeutic removed"
    return {"minutes": without, "minutes_with_breaks": with_breaks, "basis": used}


def _intersect(xs, ys):
    out = []
    for a, b in merge(xs):
        for c, d in merge(ys):
            lo, hi = max(a, c), min(b, d)
            if lo < hi:
                out.append((lo, hi))
    return merge(out)
