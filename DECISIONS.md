# Decision doc

Notes from the design phase, with the decisions added during the build in section 8.

---

## 1. What and why

- Task in one line: read 31 clinical text files once, pull out facts with their source line, store them so they survive restarts and new files, answer questions by computing over the stored facts, name every conflict and gap.
- Not a RAG exercise. Brief, FAQ: "think beyond a standard vector-search-and-answer pipeline."
- Numbers must come from code, not from a model reading text. Brief, section 2: "Calculate numerical answers in code from the abstraction."
- Every number must trace to a file and line. Brief, FAQ: "trace its contents back to their sources."
- Must work on documents and questions we have not seen. Brief, FAQ: "accommodate related unseen questions and additional documents without manually encoding this patient's facts or answers."
- After submission there is a 30-min call where they run new documents and new questions through the code live. Brief, section 4.
- The documents are built to trap naive counting: same session in 2 to 4 files, a correction that overrides a roster, a stale copy resent a week later, a draft note and a billing charge for a session the patient missed, one video session split into two call logs, one PHQ-9 score imported twice.

---

## 2. How: three decisions

Split the problem into three independent choices.

- D1. How to turn a document into facts.
- D2. How to store the facts.
- D3. How to answer a question from the stored facts.

---

## 3. D1: document to facts

### Options

- Regex / hand-written parsers.
- LLM reads the whole document, fills a fixed form.
- Hybrid: regex for headers, LLM for prose.

### Removed

- Regex. One pattern per field per layout. 10 fields x 6 layouts here = 60 patterns, and a new layout in the design call yields zero fields. Breaks systematically on anything unseen. Build cost is high for four hours.
- Hybrid. Rests on the assumption that headers are always formatted the same way. True for these 31 files, false in general. YAGNI until an LLM miss on a header is measured.

### Chosen

- LLM reads the entire document and returns one filled form. Same form every document.
- Form = instruction to the model: always look for a fixed set of fields (patient, MRN, clinic, date, encounter, document type, times, status, who signed, corrections, scores) plus "anything else the document states."
- Every field returned with the line number it came from. That is the audit trail.
- A `summary` field holds a short prose account of what happened. Needed for narrative questions (DEV-05).
- New fields in unseen documents land as new field names, no code change. If a new field later matters for a question, add a function that reads it.
- Accepted tradeoff: the LLM will miss or misread occasionally. Regex would too, but systematically. Misses are measurable; we log them.

### Why it fits the brief

- Any model allowed. FAQ: "Choose the tools you think best fit the problem."
- Model use expected. Section 3: "Include model names and settings... approximate runtime and model cost."
- Abstraction "derived from the documents," format "up to you," must be traceable. FAQ on clinical abstraction. Line-referenced rows satisfy all three.

---

## 4. D2: storing facts

### Options

- One row per encounter, overwrite on conflict.
- One row per claim, never overwrite, separate resolution step.
- Graph database (documents, encounters, people as nodes; corrects / duplicates as edges).
- Raw text plus embeddings, no structure.

### Removed

- Overwrite. Roster says departure 11:30, correction says 11:15, we edit the cell. The 11:30 is gone. Auditor asks "what did the original say" and we have nothing. Fails tracing and fails "a later document does not automatically override an earlier one."
- Graph. Most expressive, heaviest to set up. The questions are sums over date ranges, not path queries. Overkill for four hours.
- Raw text plus embeddings. Nothing structured, so every question re-reads and re-reasons. No reuse across questions or runs, nothing to inspect, nothing to audit. Fails three requirements at once.

### Chosen: claims table, key-value shape, never overwritten

One table. Seven columns, every row:

```
doc | clinic | patient | subject | field | value | line
```

- `subject` is what the fact is about: an encounter ID, or `plan:<doc>` or `measure:<doc>` for facts with no encounter. Renamed from `encounter` during build for that reason.
- `field` is the name of the fact, `value` is the fact. A roster contributes rows with field=arrival, field=departure. A PHQ-9 review contributes field=phq9_score. A plan contributes field=min_minutes_per_week. Different document shapes become different field names in the same two columns. The shape lives in the data, not the schema. This is how one table takes any document, including ones we have not seen.
- `summary` is just another field. Not a separate column.
- Nothing is ever deleted or edited. A correction adds a row; it does not change the roster's row.

Example, the Jan 19 departure field, three documents, three rows:

```
BH-D102 roster       | departure | 11:30 | line 9
BH-D103 correction   | departure | 11:15 | line 7
BH-D104 resent copy  | departure | 11:30 | line 15
```

### Resolution step

- Separate pass reads claims and writes one resolved value per field, with the rule that won and the rows it used.
- Rules are general, none mention a patient: a correction outranks the document it names; a retransmission adds no evidence; a signed record outranks an unsigned draft; a billing charge is not attendance; two notes with the same encounter ID are one session; services the plan excludes (medication, collateral, coordination) do not count toward the plan.
- When no rule settles a conflict, the field is marked unresolved. Downstream math produces a range or "cannot be determined." Nothing is silently picked.
- Resolution output for the example: `departure = 11:15; basis: D103 corrects D102; D104 is a retransmission of D102 carrying the pre-correction value, no new evidence.` The user sees that sentence.

### Key: (clinic, MRN), not name

- MRN = Medical Record Number, the clinic's patient ID. Unique within a clinic by design. Names repeat and get misspelled.
- Assumption: MRN is unique within a clinic, not across clinics. Two hospitals could both have an M042. So the key is (clinic, MRN). Costs one column now, avoids a collision later. Added now rather than deferred because it makes the scaling story honest.
- Subject (encounter) is a separate column, not part of the patient key. It identifies which visit a row is about and changes per appointment. The `HG-` prefix on both is the clinic's initials, which is a naming coincidence, not a relationship.

### Indexes

- Three: `(clinic, patient)`, `encounter`, `doc`. One per question shape: everything about a patient, everything about one appointment, everything one file said.
- Three indexes is modest. Inserts slow slightly, disk grows ~30%. Routine.
- String keys for now. `HG-M042` is 7 bytes. A B-tree stores the sorted string; no hashing. At 8M rows the difference versus integer keys is tens of MB. Standard fix if it ever matters: a `patients` table mapping (clinic, MRN) to an integer id. One join per query. Not built today; one sentence in the README scaling section.

### One table vs one table per patient

Considered a table per patient: small tables, LLM targets the right one by name.

Rejected. Reasoning from first principles against 1M documents:

- Size does not make a lookup slow when indexed. Estimate: 1M docs x ~8 claims = 8M rows. One patient = ~250 rows. Index on `(clinic, patient)` is a sorted tree; finding one patient is ~log2(8M) = 23 comparisons, then read ~250 rows. The other 7,999,750 rows are never touched. Single-patient latency is the same at 31 docs and 1M docs.
- Collection-wide questions are in the brief ("which patients had two consecutive weeks below requirements"). One table: one query, group by patient. 10,000 per-patient tables: 10,000 queries stitched in code.
- Maintenance: add one field to the form, change one table versus 10,000. Backups, indexes, migrations multiply.
- The LLM's job gets harder, not easier: it needs a name-to-table map before it can query. With one table it fills `patient = X` and the index does the rest.
- Per-patient split is a real technique, but databases do it internally (partitioning) without changing the query. If needed, it is a config change, not a design change.

### Scaling beyond one machine

- Shard the one table by `(clinic, patient)`. All of a patient's rows land on one shard, so patient questions still hit one place. Collection-wide questions fan out and merge, which is the normal cost of that question at any scale.
- Not built. Named in the README as the change at 500K+ along with the part of the code it touches.

### Numbers

- 31 docs x ~8 facts = ~250 rows. Estimate; replace with the measured count after first ingest.
- Re-ingest: hash each file; seen hash is skipped. Duplicate copies of a document add zero rows. Brief: "Duplicate copies of a document should not change clinical results."

### Why it fits the brief

- Trace to source: every row has doc and line.
- Conflicts and corrections: all versions kept; resolution records the basis; unresolved stays unresolved.
- "A later document does not automatically override an earlier one": rules decide, not timestamps. The Jan 26 resent copy is later than the Jan 20 correction and loses.
- Reuse across questions and runs: table on disk; all questions read it; restart loads it; new file adds rows only.
- Unseen documents: new fields are new rows, no schema change.
- Collection-wide questions: one table, one query.

---

## 5. D3: answering questions

### Options

- Fixed functions, one per question.
- LLM maps the question to a function and fills its parameters; code runs it.
- LLM writes SQL per question.
- LLM with tools, reasons freely until satisfied.

### Removed

- Fixed functions with no parameters. A new question shape needs new code; a new patient needs new code. Fails "related unseen questions."
- LLM writes SQL as the primary path. Flexible, but the join across claims, resolution, plan rules, and week boundaries is the hard part, and the model rewrites it per question. A subtle join error gives a confident wrong number with no test behind it. Fails "reproducible calculations."
- LLM with tools reasoning freely. Slowest, most expensive, non-deterministic numbers, re-does work per question. Fails reuse and reproducibility.

### Chosen: LLM maps to tested functions; generated SQL as a labeled fallback

- A small set of functions, written and tested once, each with blanks: patient, date range, field. Examples: sessions by type, minutes by week, plan check by week, reconstruct one day, timeline of observations.
- The LLM reads the question and conversation context (later questions say "the review period" and "the episode" without naming Rowan), picks the function, fills the blanks. Code runs it. Same function, same rows, same number every run.
- The LLM then writes the prose answer from the function output and cites the claim rows and resolution basis. It never does arithmetic and never resolves a conflict.
- Flexibility comes from the blanks. New patient, new range, new week = different blanks, same tested arithmetic.

### Fallback when no function fits

- Say so plainly: "This question does not map to a computation I can run."
- Then: LLM writes a read-only SQL query against the claims table, run it, show the answer labeled provisional and unreviewed, show the query so a reviewer can check it, and save the query to a review list for promotion to a tested function.
- Two guardrails: read-only, cannot write or alter; the label and the SQL appear every time.
- Honest about scope and still useful. Fits "handling of uncertainty" in the evaluation criteria and "repeated reviews" in the overview, since the function set grows from use.
- First thing to drop if time runs out; the plain "does not map" message is the floor.

### Why it fits the brief

- "Calculate numerical answers in code from the abstraction": functions we wrote, reading the table.
- "Reproducible calculations": same function, same rows, same number.
- "Related unseen questions": parameters cover new patients, ranges, weeks, plans.
- "Without manually encoding patient facts": functions hold logic only.
- FAQ: "You do not need to build a universal clinical review system." The limit (a wholly new question type) is permitted, and the fallback covers it honestly.

---

## 6. One-line architecture

LLM reads each document once into a claims table; rules resolve conflicts and record why; tested functions compute; LLM picks the function and writes the words; anything outside the functions gets a labeled, read-only, generated query.

---

## 7. Open items

- Storage engine: SQLite vs Postgres.
- Model and settings for extraction and answering.
- Build order for the four hours.

---

## 8. Decisions made during the build

Each came from a measured failure, each is general.

- Few-shot examples as real tool-call turns, not text. Text examples made the model return the whole form as a string.
- Three examples, not two: a plan with a score was added after the model put plan goals and PHQ scores in `extra`.
- Repair before retry. A reply cut one character short or a list wrapped in a list is fixed in code; only a still-malformed section costs a second model call.
- Scheduling facts by vote, presence by witness ladder. A register misread a service type and outranked a draft that had it right. What was booked is known equally by every source; who was there is not.
- Lower-rank sources break ties between equal notes. Two clinical notes disagreed on a type; the scheduling export agreed with one. Majority of documents.
- Intervals from one document are legs of one session; from different documents, a conflict. Two notes for one session were being unioned into the longer one.
- No temperature knob in the API. Stability measured across four runs instead of assumed: answer numbers stable, labels on excluded encounters not.
- Unknown patient name is refused, not defaulted. The one-patient default applied to any name until a question about a nonexistent patient got a real answer.
- Answer in three fixed sections. Free-form prose from the writer was dense and padded; Answer / Evidence / Unresolved is the same information in a third of the space.
