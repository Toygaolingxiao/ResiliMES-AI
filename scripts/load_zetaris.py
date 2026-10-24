#!/usr/bin/env python3
"""Obsolete Zetaris SQL-editor loader.

The owner's bundle does not create the plant with Lightning DDL. Postgres
lives in the fab-mes container, and Zetaris only registers datasources.
Run scripts/zetaris_setup.sh instead.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("scripts/load_zetaris.py is obsolete.")
    print("Reload Postgres and the three datasources with:")
    print("  bash scripts/zetaris_setup.sh [seed.sql]")
    print("From Windows:")
    print("  wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh")
    print("The recipe is docs/ZETARIS.md. Nothing was sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
