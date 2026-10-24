"""Rewrite the generated table at the top of docs/i18n_review.md from i18n.json."""

from __future__ import annotations

from resilimes.config import ROOT
from resilimes.i18n import review_markdown

path = ROOT / "docs" / "i18n_review.md"
lines = path.read_text(encoding="utf-8").split("\n")
start = next(i for i, line in enumerate(lines) if line.startswith("| --- |"))
end = start + 1
while end < len(lines) and lines[end].startswith("|"):
    end += 1
rest = "\n".join(lines[end:])
path.write_text(review_markdown() + rest, encoding="utf-8")
print("rewrote", path.name)
