"""Rewrite the generated table at the top of docs/design/TOKENS_REVIEW.md."""

from __future__ import annotations

from resilimes.config import ROOT
from resilimes.design.tokens import REVIEW_PATH, review_markdown

REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
if REVIEW_PATH.exists():
    lines = REVIEW_PATH.read_text(encoding="utf-8").split("\n")
    # Keep any hand-written appendix after a marker, if present.
    marker = "<!-- tokens-review:hand -->"
    if marker in lines:
        idx = lines.index(marker)
        rest = "\n".join(lines[idx:])
        REVIEW_PATH.write_text(review_markdown() + rest, encoding="utf-8")
    else:
        REVIEW_PATH.write_text(review_markdown(), encoding="utf-8")
else:
    REVIEW_PATH.write_text(review_markdown(), encoding="utf-8")
print("rewrote", REVIEW_PATH.relative_to(ROOT))
