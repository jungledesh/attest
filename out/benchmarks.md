# Benchmarks

Measured on the supplied documents. Estimates are in their own section with the assumption stated.

## Measured

| Item | Value |
|---|---|
| Documents ingested | 31 |
| Patients | 1 |
| Claims rows | 619 (20.0 per document) |
| Resolved rows | 327 (8 unresolved) |
| Database size | 476 KB (15.4 KB per document, raw text included) |
| Full ingest wall time | 84.88 s for 31 files (2.74 s per document) |
| Model call per document | mean 2.74 s, min 1.83 s, max 5.02 s, over 31 calls |
| Ingest tokens, all calls logged | 201,920 in, 21,741 out (6,514 + 701 per call) |
| Ingest cost | $0.0311 |
| Resolve wall time | 0.004 s for 1 patient(s) |

### Questions

| Question | Function | Function ms | Model ms | Tokens in | Tokens out | Cost |
|---|---|---|---|---|---|---|
| For January 5–30, 2026, how many therapy sessions did Rowan ... | sessions | 2 | 10147 | 3,912 | 2,321 | $0.0016 |
| How many therapy minutes and hours did Rowan actually receiv... | minutes_by_week | 1 | 9681 | 4,214 | 2,275 | $0.0016 |
| For each week, did the delivered therapy meet the goal docum... | plan_check | 5 | 8282 | 3,229 | 1,773 | $0.0012 |
| Reconstruct the care on January 19 and January 21. How many ... | day | 4 | 7467 | 3,996 | 1,734 | $0.0013 |
| Summarize the documented symptom course during the episode a... | timeline | 1 | 11491 | 6,270 | 2,646 | $0.0019 |
| How many group sessions did tara attend in week 2?... | none | 0 | 1422 | 0 | 0 | $0.0000 |
| How many group sessions did perry  attend in week 2?... | none | 0 | 1285 | 0 | 0 | $0.0000 |
| Which clinicians signed documents for this patient, and how ... | fallback_sql | 0 | 1475 | 0 | 0 | $0.0000 |
| For January 5–30, 2026, how many therapy sessions did Rowan ... | sessions | 1 | 10806 | 3,901 | 2,505 | $0.0016 |
| How many therapy minutes and hours did Rowan actually receiv... | minutes_by_week | 1 | 9910 | 4,214 | 2,373 | $0.0016 |
| For each week, did the delivered therapy meet the goal docum... | plan_check | 1 | 7100 | 3,234 | 1,714 | $0.0012 |
| Reconstruct the care on January 19 and January 21. How many ... | day | 4 | 6649 | 4,010 | 1,600 | $0.0012 |
| Summarize the documented symptom course during the episode a... | timeline | 2 | 9254 | 6,606 | 2,225 | $0.0018 |
| Which clinicians signed documents for this patient, and how ... | fallback_sql | 0 | 1555 | 0 | 0 | $0.0000 |
| For January 5–30, 2026, how many therapy sessions did Rowan ... | sessions | 1 | 9595 | 3,938 | 2,291 | $0.0015 |
| How many therapy minutes and hours did Rowan actually receiv... | minutes_by_week | 2 | 10962 | 4,247 | 2,649 | $0.0017 |
| For each week, did the delivered therapy meet the goal docum... | plan_check | 3 | 9958 | 3,261 | 1,719 | $0.0012 |
| Reconstruct the care on January 19 and January 21. How many ... | day | 4 | 4971 | 4,045 | 1,190 | $0.0010 |
| Summarize the documented symptom course during the episode a... | timeline | 2 | 10686 | 6,642 | 2,763 | $0.0020 |

Question latency is almost entirely model time: the function reads the resolved table in single-digit milliseconds. Collection-wide function (`consecutive_below`) over 1 patient(s): see the plan_check row; it runs plan_check per patient.

Total question tokens: 65,719 in, 31,778 out. Cost: $0.0225.

## Estimates

- Ingest 500,000 documents, one call at a time: 380 hours (16 days). Assumes the measured mean of 2.74 s per document holds and documents are the same size. With 32 parallel workers: 12 hours, assuming the provider's rate limit allows it.
- Ingest 1,000,000 documents, one call at a time: 760 hours (32 days). Assumes the measured mean of 2.74 s per document holds and documents are the same size. With 32 parallel workers: 24 hours, assuming the provider's rate limit allows it.
- Ingest tokens at 1,000,000 documents: 6.5 billion in, 0.70 billion out, assuming the measured per-call average. Cost: multiply by your contracted price per million.
- Database at 1,000,000 documents: 15.7 GB, assuming 15.4 KB per document holds. Raw text is about half of that; drop it from the hot store and keep it in object storage to halve the figure.
- Claims rows at 1,000,000 documents: 20 million, assuming 20.0 per document.
- Single-patient question latency does not change with collection size: the (clinic, patient) index finds one patient's rows in logarithmic time. Not measured at scale; this is the property of a B-tree index.
- Collection-wide question latency grows linearly with patients: plan_check runs per patient. At 10,000 patients and ~5 ms each, ~50 s. The fix is a weekly_summary table maintained at resolve time.

## Not measured

- Extraction accuracy as a rate. Checked by hand on the known traps (see README). No labeled set exists to compute precision.
- Run-to-run stability of extraction. The API exposes no temperature; one re-extraction of the same document is in the README.
- Anything on Postgres, parallel ingest, or more than one patient. Not built.
