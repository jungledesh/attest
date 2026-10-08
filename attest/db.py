"""Schema, connection, indexes. The only file that knows SQL.

Swap SQLite for Postgres here and nothing else changes.
"""

import json
import sqlite3
from pathlib import Path

DEFAULT_PATH = Path("out/attest.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT NOT NULL,
    sha256      TEXT NOT NULL UNIQUE,
    path        TEXT NOT NULL,
    raw_text    TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    flags       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS documents_doc_id ON documents(doc_id);

CREATE TABLE IF NOT EXISTS claims (
    id       INTEGER PRIMARY KEY,
    doc_id   TEXT NOT NULL,
    clinic   TEXT NOT NULL,
    patient  TEXT NOT NULL,
    subject  TEXT NOT NULL,
    field    TEXT NOT NULL,
    value    TEXT NOT NULL,
    line     INTEGER
);
CREATE INDEX IF NOT EXISTS claims_patient ON claims(clinic, patient);
CREATE INDEX IF NOT EXISTS claims_subject ON claims(subject);
CREATE INDEX IF NOT EXISTS claims_doc     ON claims(doc_id);

CREATE TABLE IF NOT EXISTS resolved (
    clinic     TEXT NOT NULL,
    patient    TEXT NOT NULL,
    subject    TEXT NOT NULL,
    field      TEXT NOT NULL,
    value      TEXT,
    basis      TEXT NOT NULL,
    claim_rows TEXT NOT NULL,
    status     TEXT NOT NULL,
    PRIMARY KEY (clinic, patient, subject, field)
);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY,
    stage      TEXT NOT NULL,
    started    TEXT NOT NULL,
    ended      TEXT NOT NULL,
    model      TEXT,
    tokens_in  INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd   REAL DEFAULT 0,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY,
    asked_at    TEXT NOT NULL,
    question    TEXT NOT NULL,
    context     TEXT,
    function    TEXT,
    params      TEXT,
    result_json TEXT,
    answer_text TEXT,
    provisional INTEGER NOT NULL DEFAULT 0,
    ms_function INTEGER,
    ms_model    INTEGER
);

CREATE TABLE IF NOT EXISTS pending_queries (
    id        INTEGER PRIMARY KEY,
    asked_at  TEXT NOT NULL,
    question  TEXT NOT NULL,
    sql       TEXT NOT NULL,
    reviewed  INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path=DEFAULT_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


# documents

def has_hash(con, sha):
    return con.execute("SELECT 1 FROM documents WHERE sha256=?", (sha,)).fetchone() is not None


def doc_ids_with_other_hash(con, doc_id, sha):
    rows = con.execute("SELECT sha256 FROM documents WHERE doc_id=? AND sha256<>?",
                       (doc_id, sha)).fetchall()
    return [r[0] for r in rows]


def insert_document(con, doc_id, sha, path, raw_text, ingested_at, flags=""):
    con.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                (doc_id, sha, str(path), raw_text, ingested_at, flags))


def document_lines(con, doc_id):
    row = con.execute("SELECT raw_text FROM documents WHERE doc_id=? LIMIT 1", (doc_id,)).fetchone()
    return row[0].splitlines() if row else []


# claims

def insert_claims(con, rows):
    """rows: iterable of (doc_id, clinic, patient, subject, field, value, line)."""
    con.executemany("INSERT INTO claims (doc_id,clinic,patient,subject,field,value,line) "
                    "VALUES (?,?,?,?,?,?,?)", rows)


def claims_for_patient(con, clinic, patient):
    return con.execute("SELECT * FROM claims WHERE clinic=? AND patient=? ORDER BY subject, field, id",
                       (clinic, patient)).fetchall()


def claims_for_subject(con, subject):
    return con.execute("SELECT * FROM claims WHERE subject=? ORDER BY field, id", (subject,)).fetchall()


def patients(con):
    return con.execute("SELECT DISTINCT clinic, patient FROM claims ORDER BY clinic, patient").fetchall()


def doc_meta(con, doc_id):
    """Header claims for a document, as a dict field -> value."""
    rows = con.execute("SELECT field, value FROM claims WHERE doc_id=? AND subject LIKE 'doc:%'",
                       (doc_id,)).fetchall()
    return {r[0]: r[1] for r in rows}


# resolved

def clear_resolved(con, clinic=None, patient=None):
    if clinic and patient:
        con.execute("DELETE FROM resolved WHERE clinic=? AND patient=?", (clinic, patient))
    else:
        con.execute("DELETE FROM resolved")


def insert_resolved(con, rows):
    """rows: iterable of (clinic, patient, subject, field, value, basis, claim_rows(list), status)."""
    con.executemany("INSERT OR REPLACE INTO resolved VALUES (?,?,?,?,?,?,?,?)",
                    [(c, p, s, f, v, b, json.dumps(cr), st) for c, p, s, f, v, b, cr, st in rows])


def resolved_for_patient(con, clinic, patient):
    return con.execute("SELECT * FROM resolved WHERE clinic=? AND patient=? ORDER BY subject, field",
                       (clinic, patient)).fetchall()


def resolved_all(con):
    return con.execute("SELECT * FROM resolved ORDER BY clinic, patient, subject, field").fetchall()


# runs, questions, pending

def log_run(con, stage, started, ended, model=None, tokens_in=0, tokens_out=0, cost=0.0, note=None):
    con.execute("INSERT INTO runs (stage,started,ended,model,tokens_in,tokens_out,cost_usd,note) "
                "VALUES (?,?,?,?,?,?,?,?)", (stage, started, ended, model, tokens_in, tokens_out, cost, note))


def runs(con):
    return con.execute("SELECT * FROM runs ORDER BY id").fetchall()


def log_question(con, asked_at, question, context, function, params, result_json,
                 answer_text, provisional, ms_function, ms_model):
    con.execute("INSERT INTO questions (asked_at,question,context,function,params,result_json,"
                "answer_text,provisional,ms_function,ms_model) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (asked_at, question, json.dumps(context), function, json.dumps(params),
                 json.dumps(result_json), answer_text, int(provisional), ms_function, ms_model))


def log_pending_query(con, asked_at, question, sql):
    con.execute("INSERT INTO pending_queries (asked_at,question,sql) VALUES (?,?,?)",
                (asked_at, question, sql))


def read_only_select(con, sql, timeout_ms=5000):
    """Run a SELECT and nothing else. Used by the fallback path."""
    s = sql.strip().rstrip(";").strip()
    if not s.lower().startswith("select") or ";" in s:
        raise ValueError("only a single SELECT is allowed")
    con.execute(f"PRAGMA busy_timeout={int(timeout_ms)}")
    cur = con.execute(s)
    cols = [d[0] for d in cur.description]
    return cols, [tuple(r) for r in cur.fetchmany(500)]


def export_csv(con, table, path):
    import csv
    rows = con.execute(f"SELECT * FROM {table}").fetchall()
    if not rows:
        return 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys())
        w.writerows([tuple(r) for r in rows])
    return len(rows)
