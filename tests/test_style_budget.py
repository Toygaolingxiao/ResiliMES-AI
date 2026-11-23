"""Wave 0: style-violation budgets only go down (#121).

Counts must stay within the budgets in VIOLATION_BUDGET.json, and the
budgets themselves must stay at or below the frozen Wave 0 baseline in
VIOLATION_BUDGET_BASELINE.json. Raising a budget therefore requires
updating the baseline file in the same PR, so the raise is visible in
the diff and must be reviewed; the tests cannot check the reason given
for it.
"""

from __future__ import annotations

from resilimes.design.violations import count_violations, load_baseline, load_budget

# Frozen metric set: adding, removing, or renaming a metric requires
# updating this set in the same PR. Without it, a metric could be
# deleted from the counter, the budget file, and the baseline file
# together and every set-equality check would still pass.
EXPECTED_METRICS = frozenset(
    {
        "breakpoints_outside_baseline",
        "css_hex_outside_token_defs",
        "css_rgba_outside_token_defs",
        "font_size_outside_text_tokens",
        "js_hex_literals",
        "js_rgba_literals",
        "spacing_outside_legacy_ladder",
    }
)


def test_style_violations_within_budget() -> None:
    budget = load_budget()
    counts = count_violations()
    metrics = budget["metrics"]
    assert set(counts) == set(metrics) == EXPECTED_METRICS, (
        f"metric keys drifted: counts={sorted(counts)} budget={sorted(metrics)} "
        f"expected={sorted(EXPECTED_METRICS)}"
    )
    over = {
        name: {"count": counts[name], "budget": metrics[name]["budget"]}
        for name in counts
        if counts[name] > metrics[name]["budget"]
    }
    assert not over, f"style violations exceeded budget (ratchet only descends): {over}"


def test_budgets_do_not_exceed_baseline() -> None:
    budget = load_budget()
    baseline = load_baseline()
    base_metrics = baseline["metrics"]
    metrics = budget["metrics"]
    assert set(metrics) == set(base_metrics) == EXPECTED_METRICS, (
        "metric keys drifted from the frozen baseline: "
        f"budget={sorted(metrics)} baseline={sorted(base_metrics)} "
        f"expected={sorted(EXPECTED_METRICS)}"
    )
    # Budgets are counts: non-integer values would compare silently
    # (e.g. a float baseline of 112.5 still caps the count at 112.5).
    assert all(type(v) is int for v in base_metrics.values()), (
        f"baseline values must be integers: {base_metrics}"
    )
    assert all(type(m["budget"]) is int for m in metrics.values()), (
        f"budget values must be integers: { {k: m['budget'] for k, m in metrics.items()} }"
    )
    raised = {
        name: {"budget": metrics[name]["budget"], "baseline": base_metrics[name]}
        for name in metrics
        if metrics[name]["budget"] > base_metrics[name]
    }
    assert not raised, (
        "budgets raised above the frozen Wave 0 baseline "
        "(update VIOLATION_BUDGET_BASELINE.json in the same PR and state "
        f"the reason in the PR body): {raised}"
    )


def test_text_warning_contrast_clears_aa() -> None:
    from resilimes.design.tokens import text_contrast_rows, text_warning_contrast_rows

    rows = text_warning_contrast_rows()
    assert rows, "expected scripted --text-warning contrast rows"
    fails = [(label, bg, ratio) for label, bg, ratio in rows if ratio < 4.5]
    assert not fails, f"--text-warning fails AA text contrast: {fails}"

    all_rows = text_contrast_rows()
    assert all_rows, "expected semantic contrast rows from tokens.json"
    text_fails = [r for r in all_rows if r["min_ratio"] == 4.5 and r["ratio"] < r["min_ratio"]]
    graphic_groups: dict[tuple[str, str], list[dict]] = {}
    for r in all_rows:
        if r["min_ratio"] != 3.0:
            continue
        graphic_groups.setdefault((r["theme"], r["token"]), []).append(r)
    graphic_fails = [
        (theme, token, rows)
        for (theme, token), rows in graphic_groups.items()
        if not any(row["ratio"] >= row["min_ratio"] for row in rows)
    ]
    assert not text_fails, f"text-* tokens fail AA contrast: {text_fails[:6]}"
    assert not graphic_fails, f"graphic-* tokens fail non-text contrast: {graphic_fails}"
