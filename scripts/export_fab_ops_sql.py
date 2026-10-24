"""Write data/sql/fab_ops_seed.sql: one recorded SMT2020 run as datasource fab_ops.

    python scripts/export_fab_ops_sql.py            # seed 1, 12 h, policy resilimes
    python scripts/export_fab_ops_sql.py --hours 24 --seed 2 --out /tmp/ops.sql

Deterministic: the same arguments write the same bytes (LF line ends).
scripts/zetaris_setup.sh loads the file when it exists.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from resilimes.evidence.fab_ops import ops_rows, ops_sql, run_id  # noqa: E402
from resilimes.evidence.toolkit import HOUR, record_run  # noqa: E402
from resilimes.smt.fab import load_fab  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--hours", type=float, default=12.0)
    parser.add_argument("--policy", default="resilimes")
    parser.add_argument("--out", default=str(ROOT / "data" / "sql" / "fab_ops_seed.sql"))
    args = parser.parse_args(argv)
    fab = load_fab()
    run = record_run(fab, seed=args.seed, horizon=args.hours * HOUR, policy=args.policy)
    tables = ops_rows(run)
    header = [
        "fab_ops seed: one recorded SMT2020 run (scripts/export_fab_ops_sql.py).",
        f"run_id={run_id(run)} seed={args.seed} hours={args.hours:g} policy={args.policy}",
        "Routed to database fab_ops / datasource fab_ops by scripts/zetaris_setup.sh.",
    ]
    text = ops_sql(tables, header)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(text.encode("utf-8"))
    counts = " ".join(f"{name}={len(rows)}" for name, rows in tables.items())
    print(f"wrote {out} bytes={len(text.encode('utf-8'))} {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
