"""Rewrite generated CSS variables at resilimes/demo/static/design/tokens.css."""

from __future__ import annotations

from resilimes.config import ROOT
from resilimes.design.tokens import CSS_PATH, css_text

CSS_PATH.parent.mkdir(parents=True, exist_ok=True)
CSS_PATH.write_text(css_text(), encoding="utf-8")
print("rewrote", CSS_PATH.relative_to(ROOT))
