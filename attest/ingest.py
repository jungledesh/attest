"""Hash, skip seen, extract, write claims, log the run.

    python -m attest.ingest documents/ [--db out/attest.db] [--no-fewshot]

Re-running on the same folder is safe: files whose bytes were seen are skipped.
A file with a known doc_id but different bytes is ingested and flagged duplicate_doc_id.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db
from . import extract

PRICE_IN = os.environ.get("ATTEST_PRICE_IN_PER_M")    # USD per 1M input tokens, optional
PRICE_OUT = os.environ.get("ATTEST_PRICE_OUT_PER_M")  # USD per 1M output tokens, optional


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cost(tin, tout):
    if PRICE_IN is None or PRICE_OUT is None:
        return 0.0
    return tin / 1e6 * float(PRICE_IN) + tout / 1e6 * float(PRICE_OUT)


def _client():
    from dotenv import load_dotenv
    load_dotenv()
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add the key.")
    return anthropic.Anthropic()


def ingest_file(con, client, path, fewshot, log):
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if db.has_hash(con, sha):
        log(f"skip   {path.name}  (seen)")
        return {"status": "skipped"}
    text = raw.decode("utf-8", errors="replace")

    form, tin, tout, dt = None, 0, 0, 0.0
    err = None
    for attempt in (1, 2):
        try:
            form, tin, tout, dt = extract.call_model(client, text, fewshot=fewshot)
            break
        except Exception as e:  # invalid form, API error
            err = f"{type(e).__name__}: {e}"
            log(f"retry  {path.name}  attempt {attempt} failed: {err}")
    if form is None:
        guess = text.splitlines()[0].replace("Document ID:", "").strip() if text else path.stem
        db.insert_document(con, guess, sha, path, text, _now(), flags="unextracted")
        db.log_run(con, "ingest.doc", _now(), _now(), extract.MODEL, tin, tout, _cost(tin, tout),
                   note=f"{path.name} unextracted: {err}")
        con.commit()
        log(f"FAIL   {path.name}  marked unextracted")
        return {"status": "unextracted"}

    doc_id, clinic, patient, rows, flags = extract.flatten(form, path.stem)
    if db.doc_ids_with_other_hash(con, doc_id, sha):
        flags.append("duplicate_doc_id")
    db.insert_document(con, doc_id, sha, path, text, _now(), flags=",".join(flags))
    db.insert_claims(con, [(doc_id, clinic, patient, s, f, v, l) for s, f, v, l in rows])
    db.log_run(con, "ingest.doc", _now(), _now(), extract.MODEL, tin, tout, _cost(tin, tout),
               note=f"{path.name} {doc_id} rows={len(rows)} s={dt:.2f}")
    con.commit()
    log(f"ok     {path.name}  {doc_id}  {len(rows)} claims  {tin}+{tout} tok  {dt:.1f}s"
        + (f"  flags={','.join(flags)}" if flags else ""))
    return {"status": "ok", "doc_id": doc_id, "rows": len(rows), "tin": tin, "tout": tout, "s": dt}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--db", default=str(db.DEFAULT_PATH))
    ap.add_argument("--no-fewshot", action="store_true")
    ap.add_argument("--log", default="out/logs/ingest.log")
    a = ap.parse_args(argv)

    Path(a.log).parent.mkdir(parents=True, exist_ok=True)
    logf = open(a.log, "a")

    def log(msg):
        line = f"{_now()}  {msg}"
        print(line); logf.write(line + "\n"); logf.flush()

    con = db.connect(a.db)
    client = _client()
    files = sorted(p for p in Path(a.folder).iterdir() if p.is_file() and not p.name.startswith("."))
    log(f"start  {len(files)} files  model={extract.MODEL}  fewshot={not a.no_fewshot}  db={a.db}")
    t0 = time.time()
    started = _now()
    stats = {"ok": 0, "skipped": 0, "unextracted": 0, "rows": 0, "tin": 0, "tout": 0}
    for p in files:
        r = ingest_file(con, client, p, fewshot=not a.no_fewshot, log=log)
        stats[r["status"]] += 1
        stats["rows"] += r.get("rows", 0); stats["tin"] += r.get("tin", 0); stats["tout"] += r.get("tout", 0)
    wall = time.time() - t0
    db.log_run(con, "ingest", started, _now(), extract.MODEL, stats["tin"], stats["tout"],
               _cost(stats["tin"], stats["tout"]),
               note=json.dumps({**stats, "files": len(files), "wall_s": round(wall, 2),
                                "fewshot": not a.no_fewshot}))
    con.commit()
    log(f"done   ok={stats['ok']} skipped={stats['skipped']} unextracted={stats['unextracted']} "
        f"claims={stats['rows']} tokens={stats['tin']}+{stats['tout']} wall={wall:.1f}s")


if __name__ == "__main__":
    main()
