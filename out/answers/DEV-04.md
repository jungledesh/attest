# DEV-04

**Question.** Reconstruct the care on January 19 and January 21. How many therapy contacts and patient therapy minutes occurred on each date, and how do the attendance records, clinical notes, later documents, and telehealth records affect your answer?

**Summary for HG-M042**

| Date | Therapy contacts | Therapy minutes | Minutes with breaks | Encounters |
|---|---|---|---|---|
| 2026-01-19 | 2 | 90 | 105 | HG-E110 (group, 60 min), HG-E111 (individual, 30 min) |
| 2026-01-21 | 1 | 45 | 45 | HG-E112 (individual, 45 min) |

**2026-01-19**

- **HG-E110 (group, attended):** 10:00–11:15 per the roster, with a 15-minute nontherapeutic interval (10:45–11:00) removed, giving 60 therapy minutes and 75 with breaks. Four documents describe it: clinical note BH-D101, attendance register BH-D102, correction BH-D103, and retransmission BH-D104. The correction BH-D103 replaces the register's departure time (BH-D102). BH-D104 repeats the pre-correction value and adds no new evidence, so the 11:15 departure rests on BH-D103. Arrival (10:00) is stated consistently by BH-D102, BH-D103, and BH-D104.
- **HG-E111 (individual, attended):** Contact interval 11:15–11:45, giving 30 minutes (same with breaks). Only clinical note BH-D105 describes it; no attendance register or correction is listed.

**2026-01-21**

- **HG-E112 (individual, attended_partial):** Two contact intervals, 13:00–13:20 and 13:30–13:55, total 45 minutes. Only clinical note BH-D106 describes it. The output lists a nontherapeutic interval of 13:20–13:30, but states "0 min nontherapeutic removed" and reports 45 minutes with breaks. The 10-minute gap is therefore not reflected in the with-breaks figure, and the basis wording does not match the interval listed. The output does not settle this.

**Effect of the source types**

- **Attendance records:** The register (BH-D102) gives the 11:15 departure for HG-E110, which the later correction (BH-D103) replaces. The register is therefore superseded on that field.
- **Clinical notes:** BH-D101, BH-D105, and BH-D106 supply the service type, status, and contact intervals used for the minute counts.
- **Later documents:** BH-D103 (correction) sets the final departure time. BH-D104 (retransmission) restates the pre-correction value and does not change the count.
- **Telehealth records:** None appear in the output. No telehealth effect on either date can be assessed from the output.

**Unresolved items**

- The output marks every field as resolved and gives no range for either date, so no low/high values are reported.
- The HG-E112 nontherapeutic interval (13:20–13:30) conflicts with the "0 min removed" basis and the 45-minute with-breaks figure. Settling this would require the source clinical note BH-D106 to state whether the 10-minute gap counts as a break or as nontherapeutic time.
- Telehealth records for either date are not in the output. Confirming whether any of these encounters was telehealth would require those records.
