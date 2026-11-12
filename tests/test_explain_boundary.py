"""Dependency direction: resilimes.explain must not reach the twin or the workshop.

Two checks. The static one follows every ``resilimes.*`` import, also the
indirect ones, starting from the explain package. The runtime one imports all
explain modules in a fresh interpreter and looks at ``sys.modules``.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "resilimes"
FORBIDDEN = (
    "resilimes.smt",
    "resilimes.engines",
    "resilimes.agents",
    "resilimes.kernel",
    "resilimes.domain",
    "resilimes.insight",
    "resilimes.evidence",
    "resilimes.llm",
    "resilimes.api",
    "resilimes.demo",
    "resilimes.txn",
)
EXPLAIN_MODULES = sorted(
    "resilimes.explain." + path.stem
    for path in (PKG / "explain").glob("*.py")
    if path.stem != "__init__"
)


def _file(module: str) -> Path | None:
    rel = Path(*module.split("."))
    for candidate in (ROOT / rel.with_suffix(".py"), ROOT / rel / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return {name for name in found if name.startswith("resilimes")}


def _closure(start: list[str]) -> dict[str, str]:
    """Every resilimes module reachable from ``start``, with who imported it."""
    seen: dict[str, str] = {name: "" for name in start}
    todo = list(start)
    while todo:
        module = todo.pop()
        path = _file(module)
        if path is None:
            continue
        for name in _imports(path):
            if name not in seen and _file(name) is not None:
                seen[name] = module
                todo.append(name)
    return seen


def _bad(names: list[str]) -> list[str]:
    return sorted(n for n in names if any(n == f or n.startswith(f + ".") for f in FORBIDDEN))


def test_explain_has_modules():
    assert {"resilimes.explain.schema", "resilimes.explain.lateness"} <= set(EXPLAIN_MODULES)


def test_explain_imports_stay_inside_the_boundary():
    reach = _closure(["resilimes.explain", *EXPLAIN_MODULES])
    bad = _bad(list(reach))
    assert not bad, {name: reach[name] for name in bad}


def test_explain_imports_at_runtime():
    code = (
        "import importlib, json, sys\n"
        f"for m in {EXPLAIN_MODULES!r}: importlib.import_module(m)\n"
        "print(json.dumps(sorted(k for k in sys.modules if k.startswith('resilimes'))))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    assert not _bad(loaded), _bad(loaded)


def test_common_does_not_import_upward():
    modules = ["resilimes.common." + p.stem for p in (PKG / "common").glob("*.py")]
    assert not _bad(list(_closure(modules)))
