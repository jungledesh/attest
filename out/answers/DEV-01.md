# DEV-01

**Question.** For January 5–30, 2026, how many therapy sessions did Rowan attend, by service type and in total, and on how many distinct days? Provide a reviewable abstraction with source support and explain records that could lead to duplicate or ineligible counts.

**Answer**

Rowan attended 12 counted therapy sessions from January 5 to 30, 2026: 5 individual, 5 group, and 2 family. The sessions fall on 11 distinct days. The count for HG-E115 (January 26) is unresolved because the source documents give different contact intervals.

**Evidence**

Counted sessions (patient HG-M042):

| Encounter | Date | Type | Status | Documents |
|---|---|---|---|---|
| HG-E101 | 2026-01-05 | individual | attended | BH-D002, BH-D006 |
| HG-E102 | 2026-01-06 | group | attended | BH-D004, BH-D005, BH-D006 |
| HG-E104 | 2026-01-09 | family | attended | BH-D006, BH-D007, BH-D008 |
| HG-E105 | 2026-01-12 | group | attended | BH-D005, BH-D006, BH-D009 |
| HG-E107 | 2026-01-14 | individual | attended | BH-D006, BH-D011 |
| HG-E110 | 2026-01-19 | group | attended | BH-D101, BH-D102, BH-D103, BH-D104 |
| HG-E111 | 2026-01-19 | individual | attended | BH-D105 |
| HG-E112 | 2026-01-21 | individual | attended_partial | BH-D106 |
| HG-E113 | 2026-01-22 | group | attended | BH-D107, BH-D108 |
| HG-E115 | 2026-01-26 | individual | attended | BH-D110, BH-D111 |
| HG-E118 | 2026-01-29 | group | attended | BH-D107, BH-D108 |
| HG-E119 | 2026-01-30 | family | attended_partial | BH-D113 |

Excluded records (not counted):

- HG-E103, 2026-01-08, individual: no_show (BH-D006, BH-D015).
- HG-E106, 2026-01-13, medication: excluded by treatment plan BH-D003 (BH-D006, BH-D010).
- HG-E108, 2026-01-15, group: clinic_cancelled (BH-D006, BH-D016).
- HG-E109, 2026-01-16, collateral: excluded by treatment plan BH-D003 (BH-D006, BH-D012).
- HG-E114, 2026-01-23, coordination: excluded by treatment plan BH-D003 (BH-D109).
- HG-E116, 2026-01-27, group: no_show (BH-D108, BH-D112).
- HG-E117, 2026-01-28, individual: patient_cancelled (BH-D108).
- HG-E120, 2026-01-30, medication: excluded by treatment plan BH-D003 (BH-D114).

Duplicate risk:

- Nine counted sessions are supported by more than one document. Each is listed once in the count.
- January 19 has two counted sessions (HG-E110 and HG-E111), which is why 12 sessions give 11 distinct days.
- BH-D006 supports five counted sessions and four excluded records. BH-D107 and BH-D108 each support both HG-E113 and HG-E118. BH-D108 also supports the excluded HG-E116 and HG-E117.
- Two counted sessions have status attended_partial (HG-E112, HG-E119). They are counted under the output's rules.

**Unresolved**

- HG-E115 (2026-01-26): contact intervals differ between documents. BH-D110 gives 09:00–09:50. BH-D111 gives 09:10–09:50. The output gives a range of 40–50 minutes. The low end is from BH-D111 and the high end is from BH-D110. The session is counted in the total of 12 either way. The minutes value would be settled by the source schedule or the contact record that set the start time.
