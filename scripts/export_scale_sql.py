#!/usr/bin/env python3
"""Write data/sql/scale_seed.sql and data/zetaris/scale/*.csv from the seeded fab."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from resilimes.data.scale_export import render_scale_csv, render_scale_sql  # noqa: E402
from resilimes.data.sql_export import TABLES  # noqa: E402


def main() -> int:
    sql_path = ROOT / "data" / "sql" / "scale_seed.sql"
    csv_dir = ROOT / "data" / "zetaris" / "scale"
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)
    sql_path.write_text(render_scale_sql(), encoding="utf-8")
    for name in TABLES:
        (csv_dir / f"{name}.csv").write_text(render_scale_csv(name), encoding="utf-8")
    print(f"Wrote {sql_path}")
    print(f"Wrote {len(TABLES)} CSV files in {csv_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
