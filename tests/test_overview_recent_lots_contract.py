"""Wave H④: invalid lots must not stay in recently viewed.

``openLot`` used to prepend the name before the lot API call, so a 404
left a chip in ``S.recentLots``. Recent names are now written only after
a successful fetch, and removed on not-found.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERVIEW_JS = ROOT / "resilimes" / "demo" / "static" / "workshop" / "overview" / "overview.js"


def test_recent_lots_only_after_successful_fetch() -> None:
    text = OVERVIEW_JS.read_text(encoding="utf-8")
    open_lot = text[text.index("function openLot(name)") : text.index("function openFamily")]
    assert "S.recentLots" not in open_lot
    assert "goto(" in open_lot
    assert "S.recentLots = S.recentLots.filter((x) => x !== S.lot)" in text
    assert (
        "S.recentLots = [lot.lot, ...S.recentLots.filter((x) => x !== lot.lot)].slice(0, 8)" in text
    )
