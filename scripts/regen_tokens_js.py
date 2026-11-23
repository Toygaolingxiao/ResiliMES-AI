"""Rewrite generated JS constants at resilimes/demo/static/design/tokens.js."""

from __future__ import annotations

from resilimes.config import ROOT
from resilimes.design.tokens import JS_PATH, js_text

JS_PATH.parent.mkdir(parents=True, exist_ok=True)
JS_PATH.write_text(js_text(), encoding="utf-8")
print("rewrote", JS_PATH.relative_to(ROOT))
