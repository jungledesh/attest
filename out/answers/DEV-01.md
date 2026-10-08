# DEV-01

**Question.** For January 5–30, 2026, how many therapy sessions did Rowan attend, by service type and in total, and on how many distinct days? Provide a reviewable abstraction with source support and explain records that could lead to duplicate or ineligible counts.

**Result for HG-M042, Harbor Grove Behavioral Health, January 5–30, 2026**

| Service type | Sessions counted | Encounters |
|---|---|---|
| Individual | 5 | HG-E101, HG-E107, HG-E111, HG-E112, HG-E115 |
| Group | 5 | HG-E102, HG-E105, HG-E110, HG-E113, HG-E118 |
| Family | 2 | HG-E104, HG-E119 |
| **Total** | **12** | |

The 12 counted entries across 11 distinct dates. The type counts (5 + 5 + 2) match the total of 12. Distinct days are 11 because HG-E110 (group) and HG-E111 (individual) both fall on 2026-01-19, so that day holds two sessions.

**Basis for inclusion.** Each counted encounter has status "attended" or "attended_partial" and a service type the treatment plan counts (BH-D003). The output counts partial attendance as attended. Partial-attendance sessions are HG-E112 (BH-D106), HG-E113 (BH-D107, BH-D108) and HG-E119 (BH-D113).

**Multi-document encounters (counted once each).** Nine encounters are supported by more than one document: HG-E101, HG-E102, HG-E104, HG-E105, HG-E107, HG-E110, HG-E113, HG-E115 and HG-E118. HG-E110 has four supporting documents (BH-D101 to BH-D104). Each was counted once in the total, so the documents do not add to the count.

**Possible duplicate pattern to check.** HG-E113 (2026-01-22) and HG-E118 (2026-01-29) cite the same two documents, BH-D107 and BH-D108. They are different subjects on different dates, so the output counts them separately. A reviewer should confirm that BH-D107 and BH-D108 each record two distinct sessions and are not one record reused.

**Excluded records (not counted).**
- Status-based exclusions: HG-E103 (no_show, BH-D015), HG-E116 (no_show, BH-D112), HG-E108 (clinic_cancelled, BH-D016), HG-E117 (patient_cancelled, BH-D108).
- Service-type exclusions under the treatment plan (BH-D003): HG-E106 and HG-E120 (medication, both attended), HG-E109 (collateral, status patient_absent), HG-E114 (coordination, attended), and enc:BH-D115:0 (other, attended, 2026-01-30).

Attended encounters excluded by service type (HG-E106, HG-E114, HG-E120, enc:BH-D115:0) would change the total if the plan's service-type list were different. The output's list is the basis for the count.

**Unresolved item.**
- **HG-E115 (2026-01-26, individual, counted).** The contact times differ between documents. BH-D110 gives 09:00–09:50, which is 50 minutes. BH-D111 gives 09:10–09:50, which is 40 minutes. The output reports minutes as null and gives a range of 40–50. The session is counted in the total of 12 under either time, so the count does not change. The duration is unresolved. It would be settled by checking the contact start and end times against the primary session record or the clinician's note for that date.
