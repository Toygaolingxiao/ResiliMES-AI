"""Pre-registered stress book (docs/AI_SHIFT_LEAD_STRESS.md): fixed params."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from resilimes.smt import sim_select_study as study
from resilimes.smt import stress_book
from resilimes.smt.fab import load_fab
from resilimes.smt.qtime_study import _setup


@pytest.fixture(autouse=True)
def _keep_env() -> object:
    before = os.environ.get("RESILIMES_STUDY_HORIZON_H")
    os.environ["RESILIMES_STUDY_HORIZON_H"] = "8"
    yield None
    if before is None:
        os.environ.pop("RESILIMES_STUDY_HORIZON_H", None)
    else:
        os.environ["RESILIMES_STUDY_HORIZON_H"] = before


def test_order_and_seeds_are_preregistered() -> None:
    assert stress_book.STRESS_SEEDS == (9, 10, 11)
    pairs = stress_book.ordered_pairs()
    assert len(pairs) == 15
    assert pairs[:6] == [*[(b, 9) for b in stress_book.SCENARIOS], ("stress_furnace_down", 10)]
    args = study.parse(["--book", "stress", "--first", "4"])
    assert args.seeds == [9, 10, 11]
    assert study.pairs(args) == pairs[:4]
    assert study.parse(["--book", "heldout_published"]).seeds == [9, 10, 11, 12, 13]


def test_resolved_parameters() -> None:
    fab = load_fab()
    lot, remain = stress_book.hot_candidate(fab)
    assert fab.lot_id[lot] == "Init_Lot_2_1" and round(remain / 3600, 3) == 3.379
    assert len(stress_book.burst_lots(fab)) == 80
    assert len(stress_book.half_tools(fab, "Diffusion_BE_123")) == 5
    assert len(stress_book.half_tools(fab, "Diffusion_FE_94")) == 7


def test_setup_injects_each_incident() -> None:
    fab = load_fab()
    _, base = _setup(fab, "heldout_published", 9, "resilimes")
    furnace = stress_book.half_tools(fab, "Diffusion_BE_123")
    _, kw = _setup(fab, "stress_furnace_down", 9, "resilimes")
    assert all(kw["downs"][t][0][0] == 0.0 and kw["downs"][t][0][1] >= 4 * 3600 for t in furnace)
    _, kw = _setup(fab, "stress_hot_cqt", 9, "resilimes")
    assert kw["promote_hot"] and abs(kw["hot_due"] - 2 * 3.3785 * 3600) < 60
    _, kw = _setup(fab, "stress_release_burst", 9, "resilimes")
    assert set(kw["faults"].hold_until.values()) == {3600.0}
    _, kw = _setup(fab, "stress_pm_peak", 9, "resilimes")
    tool = stress_book.half_tools(fab, "Diffusion_FE_94")[0]
    assert any(s <= 3600 and e >= 5 * 3600 for s, e in kw["pm"][tool])
    assert kw["pm"][tool] != base["pm"][tool]
    _, kw = _setup(fab, "stress_batch_cap", 9, "resilimes")
    assert kw["faults"].batch_cap_wafers == 25 and kw["faults"].batch_window == (0.0, 21600.0)
    with pytest.raises(KeyError):
        _setup(fab, "stress_unknown", 9, "resilimes")


def test_stress_run_and_report(tmp_path: Path) -> None:
    argv = [
        "--arms", "rules,sim_hmem", "--book", "stress", "--first", "1",
        "--horizon-h", "1", "--fork-h", "1", "--futures", "1", "--workers", "1",
        "--out-dir", str(tmp_path),
    ]  # fmt: skip
    study.main(argv)
    row = json.loads((tmp_path / "rules" / "stress_furnace_down_s9.json").read_text("utf-8"))
    assert "avoidable" in row["qtime_miss_class"] or row["qtime_avoidable"] == 0
    assert {"qtime_avoidable", "hot_late", "hot_due"} <= set(row)
    assert not (tmp_path / "memory_sim_hmem.json").exists()  # no warm-up on stress
    report = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert report["summary"]["sim_hmem"]["wtl_vs_rules"] is not None
    assert (tmp_path / "report_stress_furnace_down.md").exists()


def test_lexicographic_metric() -> None:
    base = {"qtime_avoidable": 2, "hot_late": 0, "weighted_tardiness_min": 100.0}
    assert study.lexi_cmp({**base, "qtime_avoidable": 1, "weighted_tardiness_min": 900}, base) == -1
    assert study.lexi_cmp({**base, "hot_late": 1, "weighted_tardiness_min": 0}, base) == 1
    assert study.lexi_cmp({**base, "weighted_tardiness_min": 100.4}, base) == 0
