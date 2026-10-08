# Benchmarks

Measured on the supplied documents. Estimates are in their own section with the assumption stated.

## Measured

| Item | Value |
|---|---|
| Documents ingested | 31 |
| Patients | 1 |
| Claims rows | 590 (19.0 per document) |
| Resolved rows | 296 (6 unresolved) |
| Database size | 380 KB (12.3 KB per document, raw text included) |
| Full ingest wall time | 80.99 s for 31 files (2.61 s per document) |
| Model call per document | mean 2.61 s, min 1.89 s, max 4.80 s, over 31 calls |
| Ingest tokens, all calls logged | 206,074 in, 21,649 out (6,648 + 698 per call) |
| Ingest cost | not set |
| Resolve wall time | 0.015 s for 1 patient(s) |
| Re-ingest of an unchanged folder | 0.0 s in the loop (31 hash hits, 0 model calls); about 2 s including Python start |

### Questions

| Question | Function | Function ms | Model ms | Tokens in | Tokens out | Cost |
|---|---|---|---|---|---|---|
| For January 5–30, 2026, how many therapy sessions did Rowan ... | sessions | 2 | 10059 | 3,873 | 2,217 | not set |
| How many therapy minutes and hours did Rowan actually receiv... | minutes_by_week | 2 | 11461 | 3,895 | 2,053 | not set |
| For each week, did the delivered therapy meet the goal docum... | plan_check | 4 | 8143 | 2,971 | 1,711 | not set |
| Reconstruct the care on January 19 and January 21. How many ... | day | 3 | 8193 | 3,659 | 1,859 | not set |
| Summarize the documented symptom course during the episode a... | timeline | 2 | 13994 | 7,313 | 3,276 | not set |

Question latency is almost entirely model time: the function reads the resolved table in single-digit milliseconds. Collection-wide function (`consecutive_below`) over 1 patient(s): see the plan_check row; it runs plan_check per patient.

Total question tokens: 21,711 in, 11,116 out. Cost: not set.

## Estimates

- Ingest 500,000 documents, one call at a time: 362 hours (15 days). Assumes the measured mean of 2.61 s per document holds and documents are the same size. With 32 parallel workers: 11 hours, assuming the provider's rate limit allows it.
- Ingest 1,000,000 documents, one call at a time: 724 hours (30 days). Assumes the measured mean of 2.61 s per document holds and documents are the same size. With 32 parallel workers: 23 hours, assuming the provider's rate limit allows it.
- Ingest tokens at 1,000,000 documents: 6.6 billion in, 0.70 billion out, assuming the measured per-call average. Cost: multiply by your contracted price per million.
- Database at 1,000,000 documents: 12.6 GB, assuming 12.3 KB per document holds. Raw text is about half of that; drop it from the hot store and keep it in object storage to halve the figure.
- Claims rows at 1,000,000 documents: 19 million, assuming 19.0 per document.
- Single-patient question latency does not change with collection size: the (clinic, patient) index finds one patient's rows in logarithmic time. Not measured at scale; this is the property of a B-tree index.
- Collection-wide question latency grows linearly with patients: plan_check runs per patient. At 10,000 patients and ~5 ms each, ~50 s. The fix is a weekly_summary table maintained at resolve time.

## Not measured

- Extraction accuracy as a rate. Checked by hand on the known traps (see README). No labeled set exists to compute precision.
- Run-to-run stability of extraction. The API exposes no temperature; one re-extraction of the same document is in the README.
- Anything on Postgres, parallel ingest, or more than one patient. Not built.
