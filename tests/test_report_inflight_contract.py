"""Wave H②: /report load must use a seq token and busy disable.

Overlapping Show / lot changes used to commit a stale payload into
``state``, the URL, and the hash check. ``loadReport`` now bumps
``state.loadSeq``, ignores stale completions, and disables the form
while a load is in flight.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_JS = ROOT / "resilimes" / "demo" / "static" / "product" / "report" / "report.js"


def test_report_load_has_seq_and_busy() -> None:
    text = REPORT_JS.read_text(encoding="utf-8")
    assert "loadSeq: 0" in text
    assert "const seq = ++state.loadSeq" in text
    assert "if (seq !== state.loadSeq) return" in text
    assert "function setBusy(busy)" in text
    assert 'setAttribute("aria-busy"' in text
    assert "setBusy(true)" in text
    assert "setBusy(false)" in text
    for control in ('"show"', '"lot"', '"seed"', '"horizon"'):
        assert control in text
