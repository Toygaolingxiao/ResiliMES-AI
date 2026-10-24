#!/usr/bin/env python3
"""Write data/sql/smt2020_seed.sql: the SMT2020 files as raw tables for Zetaris.

Load it with scripts/zetaris_setup.sh (the default seeds include it).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from resilimes.data.smt2020_sql import render_smt_sql  # noqa: E402


def main() -> int:
    out = ROOT / "data" / "sql" / "smt2020_seed.sql"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_smt_sql(ROOT / "data" / "smt2020"), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
