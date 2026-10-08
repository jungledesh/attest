# attest

An abstraction that turns scattered documents into facts with provenance. Every answer traces to a source.

Built for the Backbone clinical-records. The documents are one patient's month of outpatient behavioral health care, written by different people and systems, overlapping and sometimes contradicting. The code reads them once, keeps every claim with its file and line, resolves conflicts by stated rule, and answers questions by computing over the result.

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
python -m attest.bench                      # timing, tokens, cost, db size
pytest
```

New documents: drop them in `documents/`, run ingest and resolve again. Only new files are processed.

## Layout

```
attest/         the package; db.py is the only file with SQL in it
tests/          interval math, resolution rules, compute functions
documents/      the 31 supplied files
questions.json  the 5 supplied questions
out/            the abstraction (attest.db, csv exports), answers, logs, benchmarks
```

## Results

Filled after the first run.

- Answers to DEV-01 through DEV-05: `out/answers/`
- Abstraction: `out/attest.db`, `out/claims.csv`, `out/resolved.csv`
- Logs: `out/logs/`
- Benchmarks: `out/benchmarks.md`

## One design decision tested

Filled after the run. Extraction with and without few-shot examples in the prompt, measured on the known traps.

## Observed limitation and what to investigate next

Filled after the run.

## First bottleneck at a million documents

One model call per document, sequential, in `attest/ingest.py`. At the measured per-document time, a million documents is weeks on one thread. Change: parallel workers, provider batching, cache by hash so re-reviews cost nothing. Full ordering of what breaks next: `DESIGN.md`, section 10.

## Model and tooling

- Extraction, routing, prose: Claude Haiku 5.5, temperature 0, JSON output.
- Storage: SQLite, one file. Postgres at scale, same schema.
- Coding assistance: Claude (Anthropic), used for design discussion and code. Design decisions were made by the author and are recorded in `DECISIONS.md`.
- Runtime and cost: filled after the run, in `out/benchmarks.md`.
