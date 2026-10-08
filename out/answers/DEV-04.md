# DEV-04

**Question.** Reconstruct the care on January 19 and January 21. How many therapy contacts and patient therapy minutes occurred on each date, and how do the attendance records, clinical notes, later documents, and telehealth records affect your answer?

**Reconstruction for HG-M042**

| Date | Therapy contacts | Therapy minutes | Therapy minutes with breaks |
|---|---|---|---|
| 2026-01-19 | 2 | 90 | 105 |
| 2026-01-21 | 1 | 45 | 45 |

**January 19, 2026**

- **HG-E110 (group, attended): 60 minutes.** The roster shows 10:00 to 11:15, which is 75 minutes. The output removes a 15-minute nontherapeutic interval (10:45–11:00), leaving 60 minutes. With breaks, the encounter is 75 minutes. Arrival 10:00 is stated by BH-D102, BH-D103 and BH-D104. Departure 11:15 comes from the correction BH-D103, which replaces the value in the attendance register BH-D102. The retransmission BH-D104 repeats the pre-correction value and adds no new evidence. Supporting documents are the clinical note BH-D101, the attendance register BH-D102, the correction BH-D103 and the retransmission BH-D104.
- **HG-E111 (individual, attended): 30 minutes.** The only source is the clinical note BH-D105. Its contact interval is 11:15–11:45. No arrival or departure time is recorded, and there are no breaks, so the with-breaks figure is also 30.
- **Total for the day:** 2 contacts, 90 therapy minutes (60 + 30), and 105 minutes with breaks (75 + 30). The difference from the therapy total is the 15 nontherapeutic minutes in HG-E110.

**January 21, 2026**

- **HG-E112 (individual, attended_partial): 45 minutes.** The only source is the clinical note BH-D106. The contact intervals are 13:00–13:20 and 13:30–13:55. The nontherapeutic interval 13:20–13:30 is shown, but the output records 0 nontherapeutic minutes removed. The minutes are limited to the patient-present intervals, and the with-breaks figure equals the therapy figure.

**Effect of the record types**

- **Attendance records:** The register BH-D102 gave the original group departure time. The correction BH-D103 replaced it, so the group minutes rest on the correction, not the register.
- **Clinical notes:** BH-D101 (group), BH-D105 (individual on 19 January) and BH-D106 (individual on 21 January) are the sole sources for their encounters' service type and status. BH-D105 and BH-D106 are each the only document for their encounter.
- **Later documents:** The correction BH-D103 is the controlling later document. The retransmission BH-D104 is later but adds no change.
- **Telehealth records:** The output contains no telehealth records and no telehealth indicator for any encounter, so the output cannot show whether any contact was telehealth. The counts above are not adjusted for telehealth.

**Unresolved items**

- The output lists no unresolved fields. Every field is marked resolved, and the minutes_range value is null for both encounters, so no low and high range is given.
- The output does not address telehealth status. Settling this would require the telehealth records for HG-E110, HG-E111 and HG-E112.
