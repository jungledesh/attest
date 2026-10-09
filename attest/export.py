"""Write claims, resolved, documents to CSV in out/, for review without SQLite.

    python -m attest.export [--db out/attest.db]
"""

import argparse
from pathlib import Path

from . import db


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DEFAULT_PATH))
    a = ap.parse_args(argv)
    con = db.connect(a.db)
    out = Path(a.db).parent
    for t in ("claims", "resolved", "documents"):
        n = db.export_csv(con, t, out / f"{t}.csv")
        print(f"{t}: {n} rows -> {out / f'{t}.csv'}")


if __name__ == "__main__":
    main()
