"""Timings, tokens, cost, db size. Writes out/benchmarks.md.

    python -m attest.bench [--db out/attest.db]

Reads the runs and questions tables. Measured numbers only; estimates are labeled
and carry their assumption. Cost is tokens x the price you set in
ATTEST_PRICE_IN_PER_M / ATTEST_PRICE_OUT_PER_M (USD per million); unset means
tokens are reported and cost is left blank rather than guessed.
"""

import argparse
import json
import os
from pathlib import Path

from . import db


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DEFAULT_PATH))
    ap.add_argument("--out", default="out/benchmarks.md")
    a = ap.parse_args(argv)
    con = db.connect(a.db)

    docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    claims = con.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    resolved = con.execute("SELECT COUNT(*) FROM resolved").fetchone()[0]
    unresolved = con.execute("SELECT COUNT(*) FROM resolved WHERE status='unresolved'").fetchone()[0]
    patients = con.execute("SELECT COUNT(DISTINCT clinic||patient) FROM claims").fetchone()[0]
    size = Path(a.db).stat().st_size

    ing = [dict(r) for r in db.runs(con) if r["stage"] == "ingest"]
    per_doc = [dict(r) for r in db.runs(con) if r["stage"] == "ingest.doc"]
    full = [r for r in ing if json.loads(r["note"] or "{}").get("skipped", 1) == 0 and json.loads(r["note"] or "{}").get("ok", 0) == docs]
    last_full = full[-1] if full else None
    doc_secs = []
    for r in per_doc:
        n = r["note"] or ""
        if " s=" in n:
            doc_secs.append(float(n.split(" s=")[1].split()[0]))
    tin = sum(r["tokens_in"] for r in per_doc); tout = sum(r["tokens_out"] for r in per_doc)

    res = [dict(r) for r in db.runs(con) if r["stage"] == "resolve"]
    qs = [dict(r) for r in con.execute("SELECT * FROM questions ORDER BY id")]

    pin, pout = os.environ.get("ATTEST_PRICE_IN_PER_M"), os.environ.get("ATTEST_PRICE_OUT_PER_M")

    def cost(i, o):
        if pin is None or pout is None:
            return "not set"
        return f"${i/1e6*float(pin) + o/1e6*float(pout):.4f}"

    L = []
    L.append("# Benchmarks\n")
    L.append("Measured on the supplied documents. Estimates are in their own section with the assumption stated.\n")
    L.append("## Measured\n")
    L.append(f"| Item | Value |\n|---|---|")
    L.append(f"| Documents ingested | {docs} |")
    L.append(f"| Patients | {patients} |")
    L.append(f"| Claims rows | {claims} ({claims/docs:.1f} per document) |")
    L.append(f"| Resolved rows | {resolved} ({unresolved} unresolved) |")
    L.append(f"| Database size | {size/1024:.0f} KB ({size/docs/1024:.1f} KB per document, raw text included) |")
    if last_full:
        n = json.loads(last_full["note"])
        L.append(f"| Full ingest wall time | {n['wall_s']} s for {n['files']} files ({n['wall_s']/n['files']:.2f} s per document) |")
    if doc_secs:
        L.append(f"| Model call per document | mean {sum(doc_secs)/len(doc_secs):.2f} s, min {min(doc_secs):.2f} s, max {max(doc_secs):.2f} s, over {len(doc_secs)} calls |")
    L.append(f"| Ingest tokens, all calls logged | {tin:,} in, {tout:,} out ({tin/max(len(per_doc),1):,.0f} + {tout/max(len(per_doc),1):,.0f} per call) |")
    L.append(f"| Ingest cost | {cost(tin, tout)} |")
    if res:
        L.append(f"| Resolve wall time | {json.loads(res[-1]['note'])['wall_s']} s for {patients} patient(s) |")
    skipped = [r for r in ing if json.loads(r["note"] or "{}").get("skipped", 0) == docs]
    if skipped:
        L.append(f"| Re-ingest of an unchanged folder | {json.loads(skipped[-1]['note'])['wall_s']} s in the loop ({docs} hash hits, 0 model calls); about 2 s including Python start |")
    L.append("")
    L.append("### Questions\n")
    L.append("| Question | Function | Function ms | Model ms | Tokens in | Tokens out | Cost |\n|---|---|---|---|---|---|---|")
    qt_in = qt_out = 0
    for q in qs:
        r = next((x for x in db.runs(con) if x["stage"] == "ask" and json.loads(x["note"] or "{}").get("ms_model") == q["ms_model"]), None)
        ti = r["tokens_in"] if r else 0; to = r["tokens_out"] if r else 0
        qt_in += ti; qt_out += to
        L.append(f"| {q['question'][:60]}... | {q['function']} | {q['ms_function']} | {q['ms_model']} | {ti:,} | {to:,} | {cost(ti, to)} |")
    L.append(f"\nQuestion latency is almost entirely model time: the function reads the resolved table in single-digit milliseconds. "
             f"Collection-wide function (`consecutive_below`) over {patients} patient(s): see the plan_check row; it runs plan_check per patient.\n")
    L.append(f"Total question tokens: {qt_in:,} in, {qt_out:,} out. Cost: {cost(qt_in, qt_out)}.\n")

    L.append("## Estimates\n")
    if doc_secs:
        s = sum(doc_secs)/len(doc_secs)
        for N in (500_000, 1_000_000):
            L.append(f"- Ingest {N:,} documents, one call at a time: {N*s/3600:,.0f} hours ({N*s/3600/24:,.0f} days). "
                     f"Assumes the measured mean of {s:.2f} s per document holds and documents are the same size. "
                     f"With 32 parallel workers: {N*s/3600/32:,.0f} hours, assuming the provider's rate limit allows it.")
        L.append(f"- Ingest tokens at 1,000,000 documents: {tin/len(per_doc)*1e6/1e9:,.1f} billion in, {tout/len(per_doc)*1e6/1e9:,.2f} billion out, "
                 f"assuming the measured per-call average. Cost: multiply by your contracted price per million.")
    L.append(f"- Database at 1,000,000 documents: {size/docs*1e6/1e9:,.1f} GB, assuming {size/docs/1024:.1f} KB per document holds. "
             f"Raw text is about half of that; drop it from the hot store and keep it in object storage to halve the figure.")
    L.append(f"- Claims rows at 1,000,000 documents: {claims/docs*1e6/1e6:,.0f} million, assuming {claims/docs:.1f} per document.")
    L.append("- Single-patient question latency does not change with collection size: the (clinic, patient) index finds one patient's rows in logarithmic time. Not measured at scale; this is the property of a B-tree index.")
    L.append("- Collection-wide question latency grows linearly with patients: plan_check runs per patient. At 10,000 patients and ~5 ms each, ~50 s. The fix is a weekly_summary table maintained at resolve time.")
    L.append("")
    L.append("## Not measured\n")
    L.append("- Extraction accuracy as a rate. Checked by hand on the known traps (see README). No labeled set exists to compute precision.")
    L.append("- Run-to-run stability of extraction. The API exposes no temperature; one re-extraction of the same document is in the README.")
    L.append("- Anything on Postgres, parallel ingest, or more than one patient. Not built.")
    Path(a.out).write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
