# Design doc

How the prototype is built. Companion to DECISIONS.md, which records why.

---

## 1. Ask

- Read clinical documents once. Pull out facts with the file and line they came from.
- Store them so they survive restarts and new files, and so duplicates add nothing.
- Answer questions by computing over the stored facts, in code.
- Name every conflict, correction, and gap. Never pick silently.
- Work on documents and questions not seen during build.
- Measure speed, cost, and size. Say what breaks at 500K to 1M documents.

---

## 2. Shape

Four stages, one database file.

```
documents/*.txt
      |
      v
[1] ingest    LLM reads each file, returns JSON form  -->  claims table
      |
      v
[2] resolve   rules pick one value per field, record basis  -->  resolved table
      |
      v
[3] compute   tested functions: sessions, minutes, plan check, day, timeline
      |
      v
[4] answer    LLM picks function + fills blanks; prose with citations
```

Stages 1 and 2 run once per document. Stages 3 and 4 run per question.

---

## 3. Storage: SQLite, one file

Tables:

- `documents`: `doc_id, sha256, path, raw_text, ingested_at`. Hash is the dedupe key. Raw text kept so line references can be shown.
- `claims`: `doc_id, clinic, patient, encounter, field, value, line`. One row per fact. Never updated or deleted.
- `resolved`: `clinic, patient, encounter, field, value, basis, claim_rows, status`. One row per field per encounter. `status` is `resolved` or `unresolved`. `basis` is the rule that won, in plain words. `claim_rows` lists the claims rows used.
- `runs`: `stage, started, ended, model, tokens_in, tokens_out, cost`. Benchmark log.
- `questions`: `asked_at, question, context, function, params, result_json, answer_text, provisional`. Every question and its receipt.
- `pending_queries`: generated SQL from the fallback path, awaiting review.

Indexes on `claims`: `(clinic, patient)`, `encounter`, `doc_id`.

Key is `(clinic, patient)` where patient is the MRN. Encounter is a separate column.

---

## 4. Stage 1: ingest

For each file:

1. Hash the bytes. If the hash exists in `documents`, skip. Duplicate copies add nothing.
2. Store raw text.
3. Send the full text to the model with one instruction: fill this form, JSON only, every value with its line number.
4. Parse JSON. Write one `claims` row per item. If the JSON is invalid, retry once, then mark the document `unextracted` and move on. Never silently skip.
5. Log tokens, time, and cost to `runs`.

The form:

- Fixed slots the model always looks for: `doc_id, clinic, patient_name, mrn, encounter, doc_type, service_date, start, end, arrival, departure, status, signed_by, signed_at, present, corrects_doc, copy_of, score_name, score_value, summary`.
- Open list: any other stated fact as `field, value, line`.
- All of it lands in `claims` the same way. The fixed slots are a prompt, not a schema.
- Field names are locked for the fixed slots. The JSON schema sent to the model enumerates them. Open-list facts go in a separate `extra` array so a model-invented name (`end_time`, `left_at`) cannot shadow a fixed slot (`departure`). Nothing is rejected: if the model returns a key outside the enumeration, code moves it into `extra` with `label: unmapped`, original key kept, line kept, and the document still ingests. Compute functions read fixed slots only; `extra` is for inspection and the fallback path. A recurring unmapped name is the signal to add it to the fixed slots. That is how the form grows from use.

Model settings: temperature 0, JSON output mode, one document per call. No batching in the prototype so per-document timing is clean.

The prompt carries two filled examples, one of a correction and one of a retransmitted copy, so the model sees `corrects_doc` and `copy_of` used before it meets them in the data. The examples are made up, not copied from the 31 files. A field the document does not state is omitted from the JSON, never returned as empty, 0, or null; absence is detected downstream, not invented upstream.

Re-running ingest on the same folder: 31 hash hits, zero new rows, under a second.

---

## 5. Stage 2: resolve

Reads `claims`, writes `resolved`. Rules are general; none mention a patient or a date. Applied in order, first match wins, the rule name goes into `basis`.

Field conflicts:

- A document whose `corrects_doc` names another document outranks that document for the fields it states.
- A document whose `copy_of` names another document contributes no new evidence for fields the original already states.
- A signed record outranks an unsigned draft.
- A billing charge is not evidence of attendance.
- When two signed records state different values for the same field and no rule above applies, the field is `unresolved` and both values are kept.

Encounter identity:

- Rows sharing an encounter ID describe one session, however many documents carry it.
- Two call logs under one appointment ID are one session; minutes are the sum of connected intervals.

Eligibility, read from the treatment plan rows for that patient and period:

- Service types the plan lists as counting are eligible. Types it lists as excluded are not.
- Status `no_show`, `cancelled`, `patient_absent` means zero minutes and not a therapy day.

Minutes:

- Patient-present minutes = departure minus arrival (or end minus start), minus any interval the document marks as nontherapeutic, minus any interval the patient is recorded absent.
- Where the plan does not say whether breaks count, both totals are kept: with break and without. The answer shows the range and names the gap.
- A missing time field is `not_stated`, never 0. An encounter with status attended but no resolvable minutes contributes to the day count and is listed as "minutes not stated" in the week total. Zero means the record says zero (no show, cancelled); not stated means the record is silent.

Re-resolve is cheap: it runs over one patient's claims when that patient gets a new document, or over everything on demand.

---

## 6. Stage 3: compute

Plain Python functions over `resolved`. Each takes `clinic, patient` plus what it needs, returns a dict of numbers, the rows used, and any unresolved items. No model involved.

Built first, before any model call, because it is where a prototype crashes: `intervals.py`. Parses `HH:MM–HH:MM` strings (en dash, hyphen, "to"), merges connected intervals from a split call, subtracts nontherapeutic and patient-absent intervals, returns minutes or `not_stated`. Tested on the telehealth split (20 + 25 = 45), the group break (90 − 15 = 75), partial presence (45 total, 30 patient-present), and a missing departure.

- `sessions(patient, start, end)`: count by service type, total, distinct days. Lists excluded encounters and why.
- `minutes_by_week(patient, start, end)`: Monday to Sunday weeks, minutes and hours per week and overall, with and without breaks where unsettled.
- `plan_check(patient, start, end)`: per week, goal from the plan rows in effect, days and minutes delivered, verdict `met / not_met / cannot_determine`. No plan on record for the period returns `cannot_determine` with reason "no treatment plan found."
- `consecutive_below(start, end)`: all patients, which had two or more consecutive weeks below goal, which depend on unresolved fields.
- `day(patient, date)`: every contact on that date, minutes, and every document that touched it.
- `timeline(patient, start, end)`: time-ordered `summary` and score rows, with which scores are distinct originals and which are imports or copies.
- `plan_change(patient)`: care before and after any plan change, by type and amount. Returns "no plan change on record" when there is none.

Tests: each function has a test on a small hand-built claims set that encodes one trap: correction wins, copy adds nothing, draft loses to roster, split call is one session, med visit excluded, partial presence counted correctly, missing departure reported as not stated rather than zero.

---

## 7. Stage 4: answer

Input: the question text and the running context (`patient, clinic, period` from earlier questions in the session).

1. Model reads question and context, returns JSON: `function, params, context_update`. If the question names no patient and context has one, it reuses it. If neither, it returns `function: none` and the answer asks for the patient.
2. Code runs the function.
3. Model receives the function's output only, not the documents, and writes the prose answer. It cites claim rows as `doc_id line N`. It states every unresolved item the function returned. The instruction says: narrate these rows; do not compute, infer, or add totals. For narrative questions this keeps the model from re-deriving counts the compute stage already settled.
4. Code saves question, function, params, result JSON, and answer text to `questions`.

Output to the reader: the prose. On disk: the JSON receipt.

Fallback, when the model returns `function: none` and a patient is known:

- The answer opens with: "This question does not map to a tested computation."
- The model writes one read-only SQL query against `claims` and `resolved`. Code checks it is a `SELECT`, runs it with a timeout, shows the query and the result, labels the answer `provisional, unreviewed`, and saves the query to `pending_queries`.
- An engineer promotes a good query to a function in stage 3.

---

## 8. Running it

```
python ingest.py documents/          # once; re-run safe
python resolve.py                    # once; re-run safe
python ask.py questions.json         # answers all; writes answers/
python ask.py "How many group sessions did HG-M042 attend in week 2?"
python bench.py                      # timing, tokens, cost, db size
```

Drop a new file into `documents/`, run ingest and resolve again. Only the new file is processed.

---

## 9. Benchmarks reported

Measured on the 31 documents:

- Ingest wall time, per document and total.
- Tokens in and out, cost at list price.
- Resolve time.
- Latency per question: function time and model time separately.
- Latency for the collection-wide function.
- Size of `backbone.db`.

Estimates, each with its assumption stated:

- Ingest time and cost at 500K and 1M, assuming linear scaling and the measured per-document average.
- Database size at 1M, assuming the measured rows per document and bytes per row.

---

## 10. Scaling: what breaks first and what changes

In the order they would hit.

1. **Ingest throughput.** One model call per document, sequential. At the measured per-document time, 1M documents is weeks on one thread. Code: the loop in `ingest.py`. Change: run calls in parallel with a worker pool, batch where the provider allows, and cache by hash so re-reviews cost nothing. This is the first bottleneck at a million documents.
2. **Single-writer database.** SQLite allows one writer at a time, which blocks parallel ingest. Code: the `sqlite3` connection in `db.py`. Change: Postgres. Same tables, same SQL, swap the connection string. Partition `claims` by `(clinic, patient)` so a patient's rows stay together.
3. **Collection-wide questions.** `consecutive_below` reads every patient's resolved rows. At 1M documents that is a full scan. Code: `compute.py`, `consecutive_below`. Change: keep a `weekly_summary` table updated on resolve, so the question reads one row per patient-week instead of recomputing.
4. **Resolve on re-review.** Today resolve runs per patient when a new document arrives. At scale, a changed rule means re-resolving everything. Change: version the rules; store `rule_version` on `resolved`; re-resolve lazily per patient on next read.
5. **String keys.** `HG-M042` as a key is fine to tens of millions of rows. Beyond that, a `patients` table mapping `(clinic, mrn)` to an integer id shrinks indexes. One join per query.
6. **Beyond one machine.** Shard `claims` and `resolved` by `(clinic, patient)`. Patient questions hit one shard. Collection questions fan out and merge, which is the normal cost of that question at any scale.

Not needed at 31 documents. Not built.

---

## 11. How not

Things this design deliberately does not do.

- No regex or layout-specific parsers. A new layout would yield nothing.
- No overwriting. A correction adds a row; the original stays.
- No "latest document wins." Rules decide. The Jan 26 resent copy is later than the Jan 20 correction and loses.
- No model arithmetic. Every number comes from a function over the table.
- No model access to raw documents at answer time. It sees function output only, so it cannot add facts the table does not hold.
- No generated SQL as the main path. Only as a labeled fallback, read-only, saved for review.
- No per-patient tables. One table, indexed. Collection questions are one query.
- No vector index. Nothing here needs similarity search.
- No UI, no server. Command line, as the brief allows.
- No patient-specific logic anywhere. The test for every line: would it still be right for a different patient.

---

## 12. Known limits

- Extraction accuracy is the foundation and the model will miss occasionally. Misses are logged, not hidden. Measured miss rate goes in the README.
- Function set covers the five question families in the brief. A new family goes through the fallback until promoted.
- Break handling is reported as a range when the plan is silent. The record does not settle it; the design does not pretend to.
- One clinic in the data. Multi-clinic key is in place but untested on real multi-clinic data.
