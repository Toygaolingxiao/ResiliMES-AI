"""Shared Gantt window: work span only, one scale for both charts."""

from __future__ import annotations

from pathlib import Path

from resilimes.agents.orchestrator import _gantt_pair
from resilimes.config import HORIZON
from resilimes.domain.gantt import choose_step, shared_window
from resilimes.domain.plant import load_sample
from resilimes.domain.scenarios import plants_for_scenario
from resilimes.domain.schedule import POLICY_FROZEN, POLICY_RECOVER, schedule_plant

STEPS = (15, 30, 60, 120, 180, 240)


def _pair(scenario_id: str) -> dict[str, object]:
    plant = load_sample(Path("data/sample"), HORIZON)
    plants = plants_for_scenario(plant, scenario_id)
    before = schedule_plant(plants.before, POLICY_FROZEN)
    after = schedule_plant(plants.after, POLICY_RECOVER)
    return _gantt_pair(plants.before, before, plants.after, after)


def test_choose_step_prefers_the_finest_legible_interval() -> None:
    assert choose_step(110) == 15
    assert choose_step(441) == 60
    assert choose_step(536) == 120
    assert choose_step(1013) == 180
    assert choose_step(2000) == 240


def test_window_ignores_down_time_and_far_dues() -> None:
    before = {
        "rows": [{"bars": [{"end_min": 100}], "available_at_min": 1000}],
        "dues": [{"due_min": 800, "job_id": "LOT-1", "priority": 1}],
    }
    after = {"rows": [{"bars": [{"end_min": 40}]}], "dues": []}
    window = shared_window(before, after)
    assert window["start_min"] == 0
    assert window["step_min"] in STEPS
    assert window["end_min"] % window["step_min"] == 0
    assert 100 <= window["end_min"] < 200


def _max_end(gantt: object) -> int:
    assert isinstance(gantt, dict)
    rows = gantt["rows"]
    assert isinstance(rows, list)
    ends = [int(bar["end_min"]) for row in rows for bar in row["bars"]]
    return max(ends)


def test_litho_window_keeps_the_late_bar_and_one_scale() -> None:
    pair = _pair("litho_down")
    window = pair["window"]
    assert isinstance(window, dict)
    end = max(_max_end(pair["before"]), _max_end(pair["after"]))
    assert end > 800
    assert window["start_min"] == 0
    assert window["end_min"] >= end
    assert window["step_min"] in STEPS
    assert window["end_min"] % window["step_min"] == 0
    padded = end + max(end // 20, 10)
    assert window["end_min"] >= padded
    assert window["end_min"] < padded + int(window["step_min"])
    assert window == shared_window(pair["before"], pair["after"])  # type: ignore[arg-type]


def test_rush_window_stops_before_the_far_priority_due() -> None:
    pair = _pair("rush_order")
    window = pair["window"]
    assert isinstance(window, dict)
    assert window["end_min"] > 180
    assert window["end_min"] < 690
    assert window == shared_window(pair["before"], pair["after"])  # type: ignore[arg-type]
