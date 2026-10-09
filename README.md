# attest

An abstraction that turns scattered documents into facts with provenance. Every answer traces to a source.

Built for the Backbone clinical-records exercise: 31 documents on one patient's month of outpatient care, written by different people and systems, overlapping and sometimes contradicting.

## How it works

```
documents/*.txt
      |
      v
[1] ingest    model reads each file once, returns a JSON form  -->  claims table
      |
      v
[2] resolve   rules pick one value per field, record the basis  -->  resolved table
      |
      v
[3] compute   tested functions: sessions, minutes, plan check, day, timeline
      |
      v
[4] answer    model picks a function and fills its blanks; prose with citations
```

- Nothing is overwritten. A correction adds a row; the original stays.
- Numbers come from code. The model reads documents at ingest and writes prose at the end. In between it does not touch the data.
- Why these choices: `DECISIONS.md`. How each stage works: `DESIGN.md`.

## Run

Python 3.10+. Use a virtual environment; a Homebrew or distro Python refuses `pip install` into itself.

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add ANTHROPIC_API_KEY

python -m attest.ingest documents/          # once; re-run skips seen files
python -m attest.resolve                    # once; re-run is safe
python -m attest.ask questions.json         # writes out/answers/
python -m attest.ask "How many group sessions did patient M017 attend in week 2?"
python -m attest.bench                      # out/benchmarks.md
python -m attest.export                     # out/*.csv
pytest
```

- The abstraction ships built (`out/attest.db`). Ask questions at once. To rebuild from scratch, delete it first.
- New documents: drop into `documents/`, run ingest and resolve. Only new files are processed.
- A question that fits no function gets a provisional answer from a generated read-only query, labeled, saved to `pending_queries` for review.
- Dollar cost: set `ATTEST_PRICE_IN_PER_M` and `ATTEST_PRICE_OUT_PER_M` (USD per million tokens) before `bench`.

## Layout

```
attest/         the package; db.py is the only file with SQL in it
tests/          38 tests: interval math, extraction, resolution rules, compute functions
documents/      the 31 supplied files
questions.json  the 5 supplied questions
out/            attest.db, claims.csv, resolved.csv, documents.csv, answers/, logs/, benchmarks.md,
                attest_nofewshot.db from the design-decision test
```

## Results

Answers in `out/answers/`: `.md` is the prose, `.json` is the function output it was written from.

- 12 therapy sessions on 11 days: 5 individual, 5 group, 2 family. 9 encounters excluded, each with its reason.
- Minutes by Monday–Sunday week: 140 / 120 / 180 / 145–155. Total 585–595 (9.75–9.92 h); 670 with break time.
- Plan goal (BH-D003 line 12): 3 days and 150 min per week. Week 1 not met (140; 155 if breaks counted). Week 2 not met. Week 3 met. Week 4 cannot be determined: two signed notes for Jan 26 give 09:00 and 09:10 start times, so 145–155 straddles 150.
- Jan 19: 2 contacts, 90 min. Departure 11:15 from correction BH-D103; BH-D104 is a retransmission of the pre-correction roster. Jan 21: 1 contact, 45 min across two video legs.
- Three distinct PHQ-9 scores: 18, 14, 10. The Jan 26 import is a copy of the Jan 16 form.

Tracing a number: `resolved.csv` has the value, the rule that won, and `claim_rows`. Those index `claims.csv`, which has document and line. `documents.csv` has the raw text.

## Benchmarks

Measured on the supplied documents (`out/benchmarks.md`):

| Item | Measured |
|---|---|
| Full ingest, 31 documents | 84.9 s, 2.74 s per document (min 1.83, max 5.02) |
| Ingest tokens | 201,920 in, 21,741 out |
| Re-ingest, unchanged folder | 0 model calls, 0.4 s |
| Resolve | 4 ms, 619 claims to 327 resolved rows, 8 unresolved |
| Question, code | 1–4 ms |
| Question, model | 5–11 s |
| Question tokens, all 5 | 22,133 in, 10,612 out |
| Database | 476 KB, 15.4 KB per document, raw text included |

- Cost at Haiku 5.5 list price on submission day ($0.10 in, $0.50 out per million): ingest $0.031, five questions $0.008.
- Estimate: 1,000,000 documents at 2.74 s each is 32 days single-threaded, about 1 day on 32 workers if rate limits allow. Assumptions stated in `benchmarks.md`.

## Design decision tested: few-shot examples in the extraction prompt

Full ingest twice, identical except for the three invented examples (`--no-fewshot`).

| | With | Without |
|---|---|---|
| Input tokens | 206K | 136K |
| Plan goal extracted | yes | no plan rows |
| Jan 19 encounter | one, correction applied | split in two; correction applied to one |
| Unresolved fields | 6 | 29 |

Learned: the model follows the shape it is shown, not the shape it is told. A 34% token saving is not worth losing the plan.

## Observed limitation and next step

Extraction varies run to run; the API exposes no temperature. Five fresh ingests gave 590 to 619 claims. Three drifts seen:

- A misread label: one run tagged a missed group as `collateral`. No number moved; the reason would have been wrong. Led to the rule that scheduling facts are decided by vote, not by the witness ladder.
- A status drift: one run marked a partner-only visit `attended`. Plan excludes it regardless; totals held.
- A malformed reply, about one document in thirty. Code repairs the two common shapes and retries once; a document that still fails is kept raw and flagged.

The five answers' numbers were the same on every run.

Next: extract each document three times, diff the fixed slots, measure per-field agreement. Low-agreement fields get a second call at ingest; disagreement goes to the resolver as a conflict.

Also: the fallback produced valid SQL on its first unseen question but queried the wrong table and returned zero rows, and said so. The provisional label is doing real work.

## First bottleneck at a million documents

The sequential model call per document, `attest/ingest.py`, `ingest_file`. 2.74 s each; a million is 32 days on one thread.

- Change: worker pool over the file list, provider batch endpoints, the existing hash cache for re-reviews.
- Next: SQLite's single writer, which parallel ingest hits at once. Postgres; the swap is confined to `db.py`.
- Full order of what breaks next: `DESIGN.md` section 10.

## Model and tooling

- Model: `claude-haiku-5-5` for extraction, routing, prose. Forced tool call with a JSON schema for the first two. No temperature setting in the API version used (anthropic SDK 1.12).
- Storage: SQLite, one file. Same schema on Postgres.
- Coding assistance: Claude (Anthropic) throughout, for design discussion, code, and this README, driven and reviewed by the author. Design decided before code; `DECISIONS.md` is the record. Grok and Gemini each reviewed the design docs once; two points adopted, two wrong and discarded.
- Runtime: about 3 minutes end to end (85 s ingest, 4 ms resolve, about 50 s for five questions).

## Known incomplete work

- One patient in the data. Multi-patient paths and `plan_change` are tested on invented fixtures, not a real second patient.
- `extra` and `unmapped` fields are stored and exported, not used by any function.
