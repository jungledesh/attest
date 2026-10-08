# DEV-01

**Question.** For January 5–30, 2026, how many therapy sessions did Rowan attend, by service type and in total, and on how many distinct days? Provide a reviewable abstraction with source support and explain records that could lead to duplicate or ineligible counts.

**Summary (as given by the function output)**

| Measure | Value |
|---|---|
| Patient | HG-M042, Harbor Grove Behavioral Health |
| Window | 2026-01-05 to 2026-01-30 |
| Total counted sessions | 12 |
| Individual | 5 |
| Group | 5 |
| Family | 2 |
| Distinct service days | 11 |

The by-type counts (5 + 5 + 2) match the total of 12. The 12 sessions fall on 11 distinct days because 2026-01-19 has two sessions (HG-E110 group and HG-E111 individual).

**Counted sessions (all status attended or attended_partial)**

| Encounter | Date | Type | Status | Minutes | Source documents |
|---|---|---|---|---|---|
| HG-E101 | 01-05 | Individual | attended | 50 | BH-D002, BH-D006 |
| HG-E102 | 01-06 | Group | attended | 45 | BH-D004, BH-D005, BH-D006 |
| HG-E104 | 01-09 | Family | attended | 45 | BH-D006, BH-D007, BH-D008 |
| HG-E105 | 01-12 | Group | attended | 75 | BH-D005, BH-D006, BH-D009 |
| HG-E107 | 01-14 | Individual | attended | 45 | BH-D006, BH-D011 |
| HG-E110 | 01-19 | Group | attended | 60 | BH-D101–BH-D104 |
| HG-E111 | 01-19 | Individual | attended | 30 | BH-D105 |
| HG-E112 | 01-21 | Individual | attended_partial | 45 | BH-D106 |
| HG-E113 | 01-22 | Group | attended_partial | 45 | BH-D107, BH-D108 |
| HG-E115 | 01-26 | Individual | attended | null (see unresolved) | BH-D110, BH-D111 |
| HG-E118 | 01-29 | Group | attended | 75 | BH-D107, BH-D108 |
| HG-E119 | 01-30 | Family | attended_partial | 30 | BH-D113 |

**Excluded records (not counted)**

- Status-based exclusions: HG-E103 (01-08, no_show, BH-D006, BH-D015); HG-E108 (01-15, clinic_cancelled, BH-D006, BH-D016); HG-E116 (01-27, no_show, BH-D108, BH-D112); HG-E117 (01-28, patient_cancelled, BH-D108).
- Service-type exclusions under the treatment plan (plan BH-D003): medication (HG-E106 on 01-13, BH-D006, BH-D010; HG-E120 on 01-30, BH-D114); collateral (HG-E109 on 01-16, BH-D006, BH-D012); coordination (HG-E114 on 01-23, BH-D109; enc:BH-D115:0 on 01-30, BH-D115).

**Unresolved item**

- HG-E115 (01-26, individual, attended): the duration is not fixed. BH-D110 gives 09:00–09:50 and BH-D111 gives 09:10–09:50. The output reports a range of 40–50 minutes. The low end (40) follows BH-D111 and the high end (50) follows BH-D110. The session is counted in the total of 12 regardless of duration, but its minutes remain a range. The reviewer should confirm the correct contact interval against the source record for this session.

**Records that could lead to duplicate or ineligible counts**

1. Shared documents across encounters. BH-D006 supports nine encounters, including both counted and excluded ones (HG-E101, E102, E104, E105, E107, E103, E106, E108, E109). The output does not state what BH-D006 contains. If it is a roster or summary, it should not be treated as independent evidence of each session.
2. Same document pair on two dates. BH-D107 and BH-D108 support both HG-E113 (01-22) and HG-E118 (01-29). Confirm that these are two separate sessions and not one record carried onto two dates. BH-D108 also supports excluded HG-E116 and HG-E117.
3. BH-D005 supports both HG-E102 (01-06) and HG-E105 (01-12). Confirm the two dates are separate sessions.
4. Two sessions on one day. HG-E110 and HG-E111 both fall on 01-19. They have different service types and documents, so both are counted, but the reviewer should confirm they are distinct contacts.
5. Partial attendance. HG-E112, HG-E113 and HG-E119 are counted with status attended_partial. The output does not state a rule for partial attendance, so the reviewer should decide whether these meet the eligibility standard.
6. Coordination record from BH-D115. The subject ID "enc:BH-D115:0" is a document-derived identifier rather than a patient encounter ID. It is excluded here, but it should be checked against any other record of the same 01-30 contact to rule out double counting.
