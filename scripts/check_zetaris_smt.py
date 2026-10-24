#!/usr/bin/env python3
"""Check that the SMT2020 master data in Zetaris matches data/smt2020.

Reads every smt_* table through the Zetaris REST SQL editor (settings from .env),
prints per-table row counts and row hashes next to the local files, then builds
the fab both ways and compares the fab digest. Prints no URL, key or org id.

    python scripts/check_zetaris_smt.py
    exit 0 = PARITY OK, 1 = mismatch or read failure, 2 = Zetaris not configured
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from resilimes.config import ConfigError, Settings, load_settings  # noqa: E402
from resilimes.data.smt2020_sql import ZetarisRows, parity_report  # noqa: E402
from resilimes.smt.fab import _build, _load, fab_digest  # noqa: E402


def check(settings: Settings, run: Callable[..., dict[str, Any]] | None = None) -> int:
    reader = ZetarisRows(
        run,
        schema=settings.zetaris_schema,
        sources=settings.zetaris_table_sources,
        timeout_s=settings.zetaris_timeout_s,
    )
    try:
        report = parity_report(reader, ROOT / "data" / "smt2020")
        via_zetaris = fab_digest(_build(reader))
    except Exception as exc:  # report the failure class and message, never settings
        print(f"Zetaris read failed: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    via_files = fab_digest(_load(str(ROOT / "data" / "smt2020")))
    print(f"{'table':<14} {'datasource':<10} {'zetaris':>8} {'files':>8}  {'row hash':<16}  ok")
    for item in report["tables"]:
        print(
            f"{item['table']:<14} {item['datasource']:<10} {item['zetaris_rows']:>8} "
            f"{item['file_rows']:>8}  {item['zetaris_hash']:<16}  "
            f"{'yes' if item['ok'] else 'NO'}"
        )
    total_z = sum(item["zetaris_rows"] for item in report["tables"])
    total_f = sum(item["file_rows"] for item in report["tables"])
    print(f"{'total':<25} {total_z:>8} {total_f:>8}")
    print(f"rows hash   zetaris {report['zetaris_hash'][:16]}  files {report['file_hash'][:16]}")
    print(f"fab digest  zetaris {via_zetaris[:16]}  files {via_files[:16]}")
    print(f"queries {len(reader.records)}")
    ok = bool(report["ok"]) and via_zetaris == via_files
    print("PARITY OK" if ok else "PARITY FAIL")
    return 0 if ok else 1


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 2
    if not settings.zetaris_configured:
        print("Zetaris is not configured: set ZETARIS_REST_URL, ZETARIS_ORG_ID, ZETARIS_API_KEY.")
        return 2
    return check(settings)


if __name__ == "__main__":
    raise SystemExit(main())
