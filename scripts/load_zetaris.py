#!/usr/bin/env python3
"""Load data/sql/seed.sql into Zetaris, one statement per request.

Usage:
  python scripts/load_zetaris.py            # print the plan
  python scripts/load_zetaris.py --execute  # requires ZETARIS_* in .env
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402


def statements(sql: str) -> list[str]:
    chunks: list[str] = []
    for raw in sql.split(";"):
        lines = [
            line for line in raw.splitlines() if line.strip() and not line.strip().startswith("--")
        ]
        statement = "\n".join(lines).strip()
        if statement:
            chunks.append(statement)
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Load the ResiliMES seed into Zetaris")
    parser.add_argument("--execute", action="store_true", help="POST each statement")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    sql = (ROOT / "data" / "sql" / "seed.sql").read_text(encoding="utf-8")
    batch = statements(sql)
    print(f"{len(batch)} statements in data/sql/seed.sql")
    if not args.execute:
        print("Dry run. Re-run with --execute after ZETARIS_REST_URL, ZETARIS_ORG_ID,")
        print("and ZETARIS_API_KEY are set. Nothing was sent.")
        return 0
    from agent.tools_zetaris import run_sql

    for index, statement in enumerate(batch, start=1):
        preview = statement.splitlines()[0][:80]
        print(f"[{index}/{len(batch)}] {preview}")
        run_sql(statement)
    print("Load finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
