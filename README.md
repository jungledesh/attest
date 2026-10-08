# attest

An abstraction that turns scattered documents into facts with provenance. Every answer traces to a source.

Built for the Backbone clinical-records exercise. The documents are one patient's month of outpatient behavioral health care, written by different people and systems, overlapping and sometimes contradicting. The code reads them once, keeps every claim with its file and line, resolves conflicts by stated rule, and answers questions by computing over the result.

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

Nothing is overwritten. A correction adds a row; the original stays. Numbers come from code, never from the model. The model reads documents at ingest and writes prose at the end. In between it does not touch the data.

Why these choices: `DECISIONS.md`. How each stage works: `DESIGN.md`.

## Run

```
pip install -r requirements.txt
cp .env.example .env            # add ANTHROPIC_API_KEY

python -m attest.ingest documents/          # once; re-run is safe, skips seen files
python -m attest.resolve                    # once; re-run is safe
python -m attest.ask questions.json         # answers all; writes out/answers/
python -m attest.ask "How many group sessions did HG-M042 attend in week 2?"
python -m attest.bench                      # timing, tokens, db size -> out/benchmarks.md
pytest
```

New documents: drop them in `documents/`, run ingest and resolve again. Only new files are processed. A new question that fits no function gets a labeled, provisional answer from a generated read-only query, saved to `pending_queries` for review.

## Layout

```
attest/         the package; db.py is the only file with SQL in it
tests/          30 tests: interval math, extraction flattening, resolution rules, compute functions
documents/      the 31 supplied files
questions.json  the 5 supplied questions
out/            the abstraction (attest.db, claims.csv, resolved.csv, documents.csv),
                answers (out/answers/DEV-0x.md prose + .json receipt), logs, benchmarks.md,
                and attest_nofewshot.db from the design-decision test
```

## Results

Answers: `out/answers/`. Each `.md` is the prose; the matching `.json` is the function output it was written from, so every number can be checked against the rows.

Headline numbers, computed in `attest/compute.py` from `out/attest.db`:

- 12 therapy sessions on 11 distinct days (5 individual, 5 group, 2 family). 9 encounters excluded and listed with the reason: 2 medication, 1 collateral, 2 coordination, 2 no-show, 1 clinic cancellation, 1 patient cancellation.
- Minutes by Monday–Sunday week: 140 / 120 / 180 / 145–155. Total 585–595 (9.75–9.92 h). With break time counted: 670.
- Plan goal (BH-D003 line 12): 3 therapy days and 150 minutes per week. Week 1 not met (140; met if breaks counted, 155). Week 2 not met (2 days, 120). Week 3 met (180). Week 4 cannot be determined: 145–155 straddles 150 because two signed notes for Jan 26 give different start times (BH-D110 09:00, BH-D111 09:10).
- Jan 19: 2 contacts, 90 minutes. Departure 11:15 from correction BH-D103, which replaces roster BH-D102; BH-D104 (received Jan 26) is a retransmission of the pre-correction roster and adds nothing. Jan 21: 1 contact, 45 minutes across two video legs under one appointment.
- Three distinct PHQ-9 scores: 18 (Jan 5), 14 (Jan 16), 10 (Jan 30). The Jan 26 import (BH-D014) is a copy of the Jan 16 form, not a fourth assessment.

Tracing a number: `out/resolved.csv` has the value, the rule that won in plain words, and `claim_rows`. Those IDs index `out/claims.csv`, which has the document and line. `out/documents.csv` has the raw text.

## Benchmarks

Measured, from `out/benchmarks.md`:

| Item | Measured |
|---|---|
| Full ingest, 31 documents | 81.0 s wall, 2.61 s per document (min 1.89, max 4.80) |
| Ingest tokens | 206,074 in, 21,649 out (6,648 + 698 per document) |
| Re-ingest, unchanged folder | 0 model calls; about 2 s including Python start |
| Resolve | 15 ms for 1 patient, 590 claims -> 296 resolved rows, 6 unresolved |
| Question, function part | 2–4 ms each |
| Question, model part | 8–14 s each (route 1 s + prose 7–13 s) |
| Question tokens, all 5 | 21,711 in, 11,116 out |
| Database | 380 KB, 12.3 KB per document, raw text included |

Cost: tokens are logged per call in the `runs` table. `bench.py` multiplies by `ATTEST_PRICE_IN_PER_M` / `ATTEST_PRICE_OUT_PER_M` when set. Not set here, so no dollar figure is claimed; at any current Haiku-class price the full run is well under one dollar.

Estimates, each with its assumption, are in `out/benchmarks.md`. The main one: 1,000,000 documents at the measured 2.61 s each is 30 days of model calls single-threaded, about 1 day with 32 parallel workers if the provider's rate limit allows.

## One design decision tested: few-shot examples in the extraction prompt

Ran the full ingest twice into separate databases, identical except for the three made-up examples in the prompt (`--no-fewshot`).

| | With examples | Without |
|---|---|---|
| Input tokens | 206K | 136K (34% fewer) |
| Treatment plan goal extracted | yes (150 min, 3 days, counting types) | no plan rows at all |
| Jan 19 encounter identity | one subject, correction applied, 60 min | two subjects for the same encounter; correction applied to one, the other kept 11:30 and 90 min |
| Jan 16 presence | patient_absent (clinical note wins) | attended |
| Unresolved fields | 6 | 29 |

Learned: the model follows the shape it is shown, not the shape it is told. Without an example of a multi-encounter register it invents encounter IDs; without an example of a filled `plan` section it puts the goal in `extra`. The 34% token saving is not worth losing the plan. Earlier in the build, examples written as plain text instead of real tool calls made the model return the whole form as a string, which is the same lesson.

## Observed limitation and what to investigate next

Extraction is not byte-stable. Extracting BH-D106 twice gave 20 and 22 claim rows; 16 identical. The differences were in `extra` and `summary` wording, plus one run adding `arrival 13:00` and `departure 13:55` for a video visit (the first and last call times). The core fields that drive the numbers agreed, and the minutes came out 45 both times. But a drift like that arrival/departure pair could change a `minutes_with_breaks` figure on another document.

The API in use exposes no temperature parameter, so this cannot be pinned by setting.

Next: extract every document three times, diff the fixed-slot claims, and measure a per-field agreement rate. Fields under some threshold get a second opinion at ingest (two calls, keep agreement, flag disagreement as a claim conflict for the resolver). That turns an unmeasured risk into a number and a rule.

A second limitation: the fallback path produced valid SQL on its first unseen question but queried `resolved` for a field that lives only in `claims`, so it returned zero rows and said so. The label "provisional, unreviewed" is doing real work. The fix is to promote reviewed queries to functions, which is the designed loop.

## First bottleneck at a million documents

The model call per document in `attest/ingest.py`, `ingest_file`, called sequentially from `main`. Measured 2.61 s per document; a million documents is 30 days on one thread. Change: a worker pool over the file list (the hash check and the insert are already per-document and independent), provider batch endpoints where available, and the existing hash cache so re-reviews cost nothing. The second bottleneck is SQLite's single writer, which parallel ingest hits immediately; the swap to Postgres is confined to `attest/db.py`. The full order of what breaks next, with the code location and the change for each, is `DESIGN.md` section 10.

## Model and tooling

- Model: `claude-haiku-5-5` for extraction, routing, and prose. Forced tool call with a JSON schema for extraction and routing; free text for prose. No temperature setting is exposed by the API version used (anthropic SDK 1.12), so sampling is the provider default.
- Storage: SQLite, one file. Same schema and SQL on Postgres; the connection lives in `db.py`.
- Coding assistance: Claude (Anthropic) was used throughout for design discussion, code, and this README, driven and reviewed by the author. The design was decided in conversation before any code was written; `DECISIONS.md` is that record. Grok and Gemini were each asked once to review the design docs; two of their points (few-shot examples, strict field names) were adopted, two (that the dataset had 7 files and no treatment plan) were wrong and discarded.
- Runtime: about 3 minutes end to end on the supplied data (81 s ingest, 15 ms resolve, about 60 s for five questions, mostly model time).

## Known incomplete work

- One patient in the data. Multi-patient code paths (`consecutive_below`, the `(clinic, patient)` key) are built and tested on hand-made data, not on a real second patient.
- `plan_change` returns "no plan change on record" for this dataset; the before/after computation is written but exercised only in tests.
- Cost in dollars is not computed without price env vars, by choice.
- `extra` and `unmapped` fields are stored and exported but not used by any function.
