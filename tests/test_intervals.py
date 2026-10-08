"""Tests for intervals. Each test is one trap from the documents."""

from attest.intervals import (parse_time, parse_range, parse_ranges, merge,
                              subtract, total, patient_minutes)


def test_parse_time():
    assert parse_time("11:15") == 675
    assert parse_time("9:00") == 540
    assert parse_time(None) is None
    assert parse_time("noon") is None
    assert parse_time("25:00") is None


def test_parse_range_dashes():
    assert parse_range("10:00–11:30") == (600, 690)
    assert parse_range("10:00-11:30") == (600, 690)
    assert parse_range("10:00 to 11:30") == (600, 690)
    assert parse_range("Patient contact: 11:15–11:45 | Completed") == (675, 705)
    assert parse_range("11:30–10:00") is None
    assert parse_range("") is None


def test_merge_touching_and_overlap():
    assert merge([(0, 10), (10, 20)]) == [(0, 20)]
    assert merge([(0, 15), (10, 20)]) == [(0, 20)]
    assert merge([(0, 5), (10, 20)]) == [(0, 5), (10, 20)]


def test_subtract_hole_in_middle():
    assert subtract([(600, 690)], [(645, 660)]) == [(600, 645), (660, 690)]
    assert total(subtract([(600, 690)], [(645, 660)])) == 75


def test_split_video_call_is_one_session():
    # Jan 21: 13:00–13:20 and 13:30–13:55, dropped 13:20–13:30
    legs = parse_ranges(["13:00–13:20", "13:30–13:55"])
    r = patient_minutes(contact=legs)
    assert r["minutes"] == 45
    assert r["minutes_with_breaks"] == 45


def test_group_break_removed():
    # Jan 12: 10:00–11:30 attended full, break 10:40–10:55
    r = patient_minutes(arrival=parse_time("10:00"), departure=parse_time("11:30"),
                        nontherapeutic=parse_ranges(["10:40–10:55"]))
    assert r["minutes"] == 75
    assert r["minutes_with_breaks"] == 90


def test_corrected_departure_and_break():
    # Jan 19: arrival 10:00, corrected departure 11:15, break 10:45–11:00
    r = patient_minutes(arrival=600, departure=675,
                        nontherapeutic=[(645, 660)])
    assert r["minutes"] == 60
    assert r["minutes_with_breaks"] == 75


def test_late_arrival_misses_part_of_break():
    # Jan 22: arrived 10:30, left 11:30, break 10:45–11:00
    r = patient_minutes(arrival=630, departure=690, nontherapeutic=[(645, 660)])
    assert r["minutes"] == 45


def test_partial_presence_family_session():
    # Jan 30: session 13:00–13:45, patient present 13:15–13:45
    r = patient_minutes(contact=[(780, 825)], present=[(795, 825)])
    assert r["minutes"] == 30
    assert r["minutes_with_breaks"] == 30


def test_missing_departure_is_not_stated_not_zero():
    r = patient_minutes(arrival=600, departure=None)
    assert r["minutes"] is None
    assert r["minutes_with_breaks"] is None
    assert "not stated" in r["basis"]


def test_no_inputs_is_not_stated():
    r = patient_minutes()
    assert r["minutes"] is None
