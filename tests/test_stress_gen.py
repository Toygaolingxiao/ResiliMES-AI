"""Pre-registered generated stress set, the D arm, and the A/B/C script.

The generator test is the pre-registration guard: the committed spec
file must be reproducible from GEN_SEED byte for byte (as parsed JSON),
so scenarios can never be edited after results are seen without the
generator changing too.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from resilimes.llm.search import SearchCompleter
from resilimes.smt import stress_gen
from resilimes.smt.fab import load_fab
from resilimes.smt.qtime_study import _setup
from resilimes.smt.stress_gen_validate import verdict

ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_stress_live", ROOT / "scripts" / "run_stress_live.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(kind: str, n: int = 30) -> dict[str, Any]:
    lots = [
        {
            "lot": f"LOT-{i}",
            "class": ("VIP", "hot", "normal")[i % 3],
            "queued_here": True,
            "qtime_slack_min": 10.0 * i + 5,
            "due_slack_min": 30.0 * i + 7,
        }
        for i in range(n)
    ]
    return {
        "kind": kind,
        "family": "Fam_A",
        "situation": "Fam_A: 2 idle furnace(s); recipe 42 batch has 60 of min 96 wafers",
        "facts": {"tool": "T-1"},
        "lots": lots,
        "tools": [{"tool": "T-1"}, {"tool": "T-2"}],
        "engine_options": [],
        "max_plans": 50,
    }


def _ask(completer: SearchCompleter, payload: dict[str, Any]) -> dict[str, Any]:
    from resilimes.agents.sim_select import PLAN_LANE, PLAN_SYSTEM

    messages = [
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user", "content": json.dumps(payload)},
    ]
    result = completer.complete(messages, lane=PLAN_LANE)
    return json.loads(result.content)


# ----------------------------------------------------------------------
def test_specs_are_16_balanced_and_unique() -> None:
    specs = stress_gen.load_specs()
    assert len(specs) == 16
    assert len({spec["id"] for spec in specs}) == 16
    assert Counter(spec["archetype"] for spec in specs) == Counter(
        {name: 4 for name in stress_gen.ARCHETYPES}
    )
    assert all(spec["gen_seed"] == stress_gen.GEN_SEED for spec in specs)


def test_generator_reproduces_the_committed_specs() -> None:
    assert stress_gen.generate(load_fab()) == stress_gen.load_specs()


def test_specs_come_from_the_fault_tail() -> None:
    fab = load_fab()
    tail_names = {fab.families[i].name for i in stress_gen.tail_families(fab)}
    specs = stress_gen.load_specs()
    for spec in specs:
        if spec["archetype"] == "combo_down":
            assert all(name in tail_names for name in spec["families"])
            assert 1.0 <= spec["span_h"][1] <= 6.0
        if spec["archetype"] == "hot_cluster":
            assert 1.1 <= spec["hot_factor"] <= 1.5
            assert 8 <= spec["hold_lots"] <= 20


def test_apply_smoke_one_per_archetype() -> None:
    fab = load_fab()
    seen: set[str] = set()
    for spec in stress_gen.load_specs():
        if spec["archetype"] in seen:
            continue
        seen.add(spec["archetype"])
        _plant, kwargs = _setup(fab, spec["id"], 9, "resilimes")
        if spec["archetype"] == "hot_cluster":
            assert kwargs.get("promote_hot") is True
            assert kwargs.get("hot_lot") is not None
        if spec["archetype"] == "down_pm_batch":
            assert kwargs.get("faults") is not None
    assert seen == set(stress_gen.ARCHETYPES)


def test_unknown_gen_book_is_rejected() -> None:
    fab = load_fab()
    with pytest.raises(KeyError):
        _setup(fab, "gen_99_combo_down", 9, "resilimes")


def test_verdict_is_the_preregistered_trigger_rule() -> None:
    assert verdict({"escalated": 0}) is False
    assert verdict({}) is False
    assert verdict({"escalated": 1}) is True
    assert verdict({"escalated": 7}) is True


# ----------------------------------------------------------------------
def test_d_arm_budget_returns_50_unique_plans() -> None:
    for kind in ("qtime_competition", "pm_conflict", "batch_underfill", "breakdown"):
        body = _ask(SearchCompleter(seed=3), _payload(kind))
        plans = body["plans"]
        assert len(plans) == 50, kind
        keys = {
            tuple(sorted(json.dumps(lever, sort_keys=True) for lever in plan["levers"]))
            for plan in plans
        }
        assert len(keys) == 50, kind


def test_curve_planned_includes_d_points() -> None:
    from resilimes.smt import search_curve_study as curve

    args = curve.parse(["--ks", "1,3", "--d-ks", "50"])
    planned = curve._planned(args)
    assert (50, 101, 9) in planned
    assert len(planned) == 3 * 3  # (2 curve K + 1 D K) x 3 search seeds x 1 book seed
    assert curve.D_KS == (50,)


# ----------------------------------------------------------------------
def test_live_script_report_math(tmp_path: Path) -> None:
    script = _load_script()

    def row(book: str, avoidable: int, hot: int, wt: float, **lead: Any) -> dict[str, Any]:
        return {
            "book": book,
            "seed": 9,
            "qtime_avoidable": avoidable,
            "hot_late": hot,
            "weighted_tardiness_min": wt,
            "completed_routes": 5,
            "shift_lead": lead,
        }

    rows = {
        "A": row("gen_01_qtime_chain_down", 3, 1, 900.0, escalated=4, llm_calls=0),
        "B": row("gen_01_qtime_chain_down", 2, 1, 800.0, escalated=4, llm_calls=4),
        "C": row(
            "gen_01_qtime_chain_down",
            1,
            0,
            500.0,
            escalated=4,
            llm_calls=6,
            llm_failures={"timeout": 2, "provider_error": 1},
            served_models={"nvidia/nemotron-test": 4},
            non_nemotron_replies=1,
        ),
    }
    for arm, record in rows.items():
        folder = tmp_path / arm
        folder.mkdir()
        (folder / "gen_01_qtime_chain_down_s9.json").write_text(
            json.dumps(record), encoding="utf-8"
        )
    validation = {
        "generated": 16,
        "validated": 16,
        "triggered": ["gen_01_qtime_chain_down"],
        "excluded_no_trigger": ["gen_02_qtime_chain_down"],
        "pending": [],
    }
    report = script.build_report(tmp_path, "live", validation, ["gen_01_qtime_chain_down"], [9])
    assert report["wtl"]["C_vs_A"] == {
        "win": 1,
        "tie": 0,
        "loss": 0,
        "detail": [{"book": "gen_01_qtime_chain_down", "seed": 9, "cmp": -1}],
    }
    assert report["wtl"]["C_vs_B"]["win"] == 1
    deg = report["degradation_C"]
    assert deg["llm_calls"] == 6
    assert deg["timeouts"] == 2
    assert deg["fallbacks_total"] == 3
    assert deg["non_nemotron_replies"] == 1
    assert report["validation"]["trigger_rate"] == round(1 / 16, 3)
    md = script.render_md(report)
    assert "C_vs_A" in md and "MOCK" not in md

    mock_report = dict(report)
    mock_report["manifest"] = {**report["manifest"], "mock": True, "mode": "mock"}
    assert "MOCK" in script.render_md(mock_report)


def test_live_script_scenario_set_requires_validation(tmp_path: Path) -> None:
    script = _load_script()
    with pytest.raises(SystemExit):
        script.scenario_set(tmp_path / "missing.json", [])
    books, summary = script.scenario_set(tmp_path / "missing.json", ["gen_01_qtime_chain_down"])
    assert books == ["gen_01_qtime_chain_down"]
    assert "override" in summary["source"]
