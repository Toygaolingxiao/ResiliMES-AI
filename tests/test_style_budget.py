"""Wave 0: style-violation budgets only go down (#121)."""

from __future__ import annotations

from resilimes.design.violations import count_violations, load_budget


def test_style_violations_within_budget() -> None:
    budget = load_budget()
    counts = count_violations()
    metrics = budget["metrics"]
    assert set(counts) == set(metrics), (
        f"budget keys drifted: counts={sorted(counts)} budget={sorted(metrics)}"
    )
    over = {
        name: {"count": counts[name], "budget": metrics[name]["budget"]}
        for name in counts
        if counts[name] > metrics[name]["budget"]
    }
    assert not over, f"style violations exceeded budget (ratchet only descends): {over}"


def test_text_warning_contrast_clears_aa() -> None:
    from resilimes.design.tokens import text_warning_contrast_rows

    rows = text_warning_contrast_rows()
    assert rows, "expected scripted --text-warning contrast rows"
    fails = [(label, bg, ratio) for label, bg, ratio in rows if ratio < 4.5]
    assert not fails, f"--text-warning fails AA text contrast: {fails}"
