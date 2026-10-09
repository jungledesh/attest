# Design doc

How the prototype is built. Companion to DECISIONS.md, which records why. Updated after the build to match the code.

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

- `documents`: `doc_id, sha256, path, raw_text, ingested_at, flags`. Hash is the first dedupe key. A second file with the same `doc_id` but a different hash (a copy with a changed byte) is stored, flagged `duplicate_doc_id`, and treated by resolution as the same source, so its claims never double-count. Raw text kept so line references can be shown.
- `claims`: `doc_id, clinic, patient, subject, field, value, line`. One row per fact. Never updated or deleted. `subject` is what the fact is about: an encounter ID (`HG-E110`), a plan (`plan:BH-D003`), or a measure (`measure:BH-D013`).
- `resolved`: `clinic, patient, subject, field, value, basis, claim_rows, status`. One row per field per subject. `status` is `resolved` or `unresolved`. `basis` is the rule that won, in plain words. `claim_rows` lists the claims rows used.
- `runs`: `stage, started, ended, model, tokens_in, tokens_out, cost`. Benchmark log.
- `questions`: `asked_at, question, context, function, params, result_json, answer_text, provisional`. Every question and its receipt.
- `pending_queries`: generated SQL from the fallback path, awaiting review.

Indexes on `claims`: `(clinic, patient)`, `subject`, `doc_id`.

Key is `(clinic, patient)` where patient is the MRN. Subject is a separate column.

---

## 4. Stage 1: ingest

For each file:

1. Hash the bytes. If the hash exists in `documents`, skip. Duplicate copies add nothing.
2. Store raw text.
3. Send the full text to the model with one instruction: fill this form, JSON only, every value with its line number.
4. Parse the form. A section returned as a JSON string is parsed; a reply cut off a character early has its missing closing brackets re-derived; a list wrapped in a list is unwrapped. If a section is still malformed, call the model once more. If both attempts are malformed, keep the raw text as an `unparsed` claim and flag the document. If the call itself fails twice, mark the document `unextracted`. Never silently skip.
5. Log tokens, time, and cost to `runs`.

The form. One document can describe many encounters (a desk export lists nine; an attendance register lists four), so the form is a header plus a list.

- Header, once per document: `doc_id, clinic, patient_name, mrn, doc_type, signed_by, signed_at, corrects_doc, copy_of`.
  `doc_type` is one of: `clinical_note, attendance_register, scheduling_export, correction, retransmission, treatment_plan, measure, billing, draft, admin`.
- `encounters`, a list, one item per appointment the document describes: `encounter, service_date, service_type, modality, scheduled_start, scheduled_end, arrival, departure, contact_intervals, patient_present_intervals, nontherapeutic_intervals, status, patient_present, summary`.
  `service_type` is one of: `individual, group, family, medication, collateral, coordination, other`.
  `status` is one of: `attended, attended_partial, no_show, patient_cancelled, clinic_cancelled, patient_absent`.
  Interval fields are lists of `HH:MM–HH:MM` strings, each with its line. A split video call has two `contact_intervals`. A group break is one `nontherapeutic_intervals` entry. A family session where the patient joins late has a `patient_present_intervals` entry shorter than the session.
- `plan`, present only in a treatment plan: `effective_from, effective_to, min_days_per_week, min_minutes_per_week, counting_types, excluded_types, goals`.
- `measures`, a list: `score_name, score_value, completed_on, source_form, copy_of`.
- `extra`: any other stated fact as `field, value, line`.
- Every value carries the line it came from.
- All of it lands in `claims` the same way. The fixed slots are a prompt, not a schema.
- Field names are locked for the fixed slots. The JSON schema sent to the model enumerates them. Open-list facts go in a separate `extra` array so a model-invented name (`end_time`, `left_at`) cannot shadow a fixed slot (`departure`). Nothing is rejected: if the model returns a key outside the enumeration, code moves it into `extra` with `label: unmapped`, original key kept, line kept, and the document still ingests. Compute functions read fixed slots only; `extra` is for inspection and the fallback path. A recurring unmapped name is the signal to add it to the fixed slots. That is how the form grows from use.

Model settings: `claude-haiku-5-5`, forced tool call with the JSON schema, one document per call. The API version used (anthropic SDK 1.12) exposes no temperature parameter, so sampling is the provider default and run-to-run stability is measured, not assumed. No batching in the prototype so per-document timing is clean.

The prompt carries three filled examples as real tool-call turns: a correction, a multi-encounter attendance register, and a treatment plan with a score. The model sees `corrects_doc`, a multi-item `encounters` list, and filled `plan` and `measures` sections before it meets them in the data. Examples written as plain text made the model return the form as a string; as tool calls it does not. The examples are made up, not copied from the 31 files. A field the document does not state is omitted from the JSON, never returned as empty, 0, or null; absence is detected downstream, not invented upstream.

Re-running ingest on the same folder: 31 hash hits, zero new rows, under a second.

---

## 5. Stage 2: resolve

Reads `claims`, writes `resolved`. Rules are general; none mention a patient or a date. Applied in order, first match wins, the rule name goes into `basis`.

Field conflicts:

- A document whose `corrects_doc` names another document outranks that document for the fields it states.
- A document whose `copy_of` names another document contributes no new evidence for fields the original already states.
- Scheduling facts (`service_type, service_date, scheduled_start, scheduled_end, modality`): what was booked. The desk, billing, and the clinician know these equally, so every document is one vote. Majority wins; a tie is `unresolved`.
- Presence and time fields (`status, arrival, departure, patient_present`): who witnessed the patient. Source precedence when documents of different types disagree and none corrects another: `clinical_note` > `attendance_register` > `scheduling_export` > `retransmission` > `billing` > `draft`. A desk export marking an appointment "completed" loses to a clinician's note saying the patient was absent. The basis names both documents.
- When top-rank sources disagree, lower-rank sources break the tie if they side with one value. Majority of documents. The basis says "2 of 3 documents say X."
- Still tied: `unresolved`, both values kept.

Encounter identity:

- Rows sharing an encounter ID describe one session, however many documents carry it.
- Two call logs under one appointment ID are one session; minutes are the sum of connected intervals. Intervals from one document are legs of one session (union). Different documents giving different interval sets is a conflict: minutes `unresolved`, with a `minutes_range` from each document computed on its own terms.

Eligibility, read from the treatment plan rows for that patient and period:

- Service types the plan lists as counting are eligible. Types it lists as excluded are not.
- Status `no_show`, `cancelled`, `patient_absent` means zero minutes and not a therapy day.

Minutes:

- Patient-present minutes = contact intervals clipped to the roster window (arrival to departure) when both exist, else whichever exists; minus any interval marked nontherapeutic; minus any interval the patient is recorded absent. `minutes_with_breaks` is the same without the nontherapeutic subtraction.
- Where the plan does not say whether breaks count, both totals are kept: with break and without. The answer shows the range and names the gap.
- A missing time field is `not_stated`, never 0. An encounter with status attended but no resolvable minutes contributes to the day count and is listed as "minutes not stated" in the week total. Zero means the record says zero (no show, cancelled); not stated means the record is silent.

List fields (`contact_interval`, `counting_type`, ...) are stored as one resolved row holding a JSON array, since the table keys on (subject, field). `extra` facts pass through as informational rows, not used in any calculation, so a reconstruction can mention them.

Re-resolve is cheap: it runs over one patient's claims when that patient gets a new document, or over everything on demand. Measured: 31 documents, 619 claims, 327 resolved rows, 4 ms.

---

## 6. Stage 3: compute

Plain Python functions over `resolved`. Each takes `clinic, patient` plus what it needs, returns a dict of numbers, the rows used, and any unresolved items. No model involved.

Built first, before any model call, because it is where a prototype crashes: `intervals.py`. Parses `HH:MM–HH:MM` strings (en dash, hyphen, "to"), merges connected intervals from a split call, subtracts nontherapeutic and patient-absent intervals, returns minutes or `not_stated`. Tested on the telehealth split (20 + 25 = 45), the group break (90 − 15 = 75), partial presence (45 total, 30 patient-present), and a missing departure.

- Eligibility, in order: a no-show or cancelled status excludes first; then the plan's excluded types; then types the plan does not count; then a missing or unsettled type. Status is checked before type so a missed group is reported as missed, not as the wrong type.
- `sessions(patient, start, end)`: count by service type, total, distinct days. Lists excluded encounters and why, and for each counted encounter every document that describes it, so a reviewer sees that four documents describe one Jan 19 group and not four groups.
- `minutes_by_week(patient, start, end)`: Monday to Sunday weeks, minutes and hours per week and overall, with and without breaks where unsettled. Each week lists its encounters and the documents behind them.
- `plan_check(patient, start, end)`: per week, goal from the plan rows in effect, days and minutes delivered, verdict `met / not_met / cannot_determine`. No plan on record for the period returns `cannot_determine` with reason "no treatment plan found."
- `consecutive_below(start, end)`: all patients, which had two or more consecutive weeks below goal, which depend on unresolved fields.
- `day(patient, date)`: every contact on that date, minutes, and every document that touched it.
- `timeline(patient, start, end)`: time-ordered `summary` and score rows, with which scores are distinct originals and which are imports or copies.
- `plan_change(patient)`: care before and after any plan change, by type and amount. Returns "no plan change on record" when there is none.

Tests: each function has a test on a small hand-built claims set that encodes one trap: correction wins, copy adds nothing, draft loses to roster, split call is one session, med visit excluded, partial presence counted correctly, missing departure reported as not stated rather than zero.

---

## 7. Stage 4: answer

Input: the question text and the running context (`patient, clinic, period` from earlier questions in the session).

1. Model reads question and context, returns JSON: `function, patient, dates, named_patient`. If the question names no patient and context has one, it reuses it. If neither, the answer asks for the patient. If the question names a patient that matches no MRN or name in the record, the answer says so and stops; the one-patient default is never applied to an unknown name.
   Context defaults: when the database holds exactly one patient, that patient and their plan dates are the default period. More than one patient: no default.
2. Code runs the function.
3. Model receives the function's output only, not the documents, and writes the prose answer in three fixed sections: **Answer** (the numbers or verdicts in one to three sentences), **Evidence** (one line per item with its encounter and documents), **Unresolved** (only what the output flagged, and what would settle it). It cites encounter and document IDs as given. The instruction says: use only facts in the output; do not compute, infer, or add totals; no filler. Code-written replies (unknown patient, no patient named) use the same three sections.
4. Code saves question, function, params, result JSON, and answer text to `questions`.

Output to the reader: the prose. On disk: the JSON receipt.

Fallback, when the model returns `function: none` and a patient is known:

- The answer opens with: "This question does not map to a tested computation."
- The model writes one read-only SQL query against `claims` and `resolved`. Code checks it is a single `SELECT` (a `WITH` clause allowed) with no write keywords, runs it with a timeout, shows the query and the result, labels the answer **Provisional**, and saves the query to `pending_queries`.
- Observed: on its first unseen question the model queried `resolved` for a document-level field that lives only in `claims`, returned zero rows, and said so. The label is doing real work; a reviewer fixes the table and promotes the query.
- An engineer promotes a good query to a function in stage 3.

---

## 8. Running it

```
python -m attest.ingest documents/   # once; re-run safe
python -m attest.resolve             # once; re-run safe
python -m attest.ask questions.json  # answers all; writes out/answers/
python -m attest.ask "How many group sessions did patient M017 attend in week 2?"
python -m attest.bench               # timing, tokens, cost, db size
python -m attest.export              # claims, resolved, documents as CSV
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

The one design decision tested, as the brief asks: extraction with and without the three few-shot examples in the prompt, both runs on the 31 files into separate databases. Result: without examples, 34% fewer input tokens, no plan rows at all, the Jan 19 encounter split into two subjects, 29 unresolved fields against 6. Full table in the README.

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

- Extraction varies run to run and the API exposes no temperature. Five fresh ingests gave 590 to 619 claims; the five answers' numbers held on every run; labels on excluded encounters and `extra` wording drifted. Details and the next step in the README.
- Function set covers the five question families in the brief. A new family goes through the fallback until promoted.
- Break handling is reported as a range when the plan is silent. The record does not settle it; the design does not pretend to.
- One clinic in the data. Multi-clinic key is in place but untested on real multi-clinic data.
