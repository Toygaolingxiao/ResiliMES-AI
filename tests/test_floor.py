"""Floor queues, tool state, and WIP warnings stay tied to real plant data."""

from pathlib import Path

from resilimes.config import HORIZON
from resilimes.domain.floor import board_state, queue_kind, wip_steps
from resilimes.domain.gantt import build_gantt
from resilimes.domain.plant import load_sample
from resilimes.domain.schedule import POLICY_FROZEN, schedule_plant


def test_queue_kind_is_litho_or_furnace_only() -> None:
    assert queue_kind("Lithography", ["litho_193nm"]) == "litho"
    assert queue_kind("Diffusion", ["furnace_poly"]) == "furnace"
    assert queue_kind("Furnace", []) == "furnace"
    assert queue_kind("Etch", ["etch_dielectric"]) is None


def test_tool_state_uses_the_book_and_the_status() -> None:
    running = {"start_min": 0, "end_min": 30, "setup_min": 0, "held": False}
    setup = {"start_min": 0, "end_min": 40, "setup_min": 10, "held": False}
    assert board_state("IDLE", [setup]) == "setup"
    assert board_state("IDLE", [running]) == "run"
    assert board_state("MAINTENANCE", [running]) == "pm"
    assert board_state("DOWN", [running]) == "down"
    assert board_state("SETUP", []) == "setup"
    assert board_state("IDLE", []) == "idle"
    assert board_state("RUNNING", []) == "run"


def test_wip_warning_waits_for_a_real_limit() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    plain = wip_steps(plant)
    assert plain
    assert all(step.threshold is None and step.warning is False for step in plain)
    assert sum(step.lots for step in plain) == len(plant.jobs)
    limited = wip_steps(plant, {"LITHO": 1})
    litho = next(step for step in limited if step.step == "LITHO")
    assert litho.threshold == 1
    assert litho.lots >= 1
    assert litho.warning is True


def test_gantt_rows_name_state_and_capability() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    chart = build_gantt(plant, schedule_plant(plant, POLICY_FROZEN))
    rows = chart["rows"]
    assert isinstance(rows, list)
    litho = next(row for row in rows if row["equipment_id"] == "LITHO-02")
    assert litho["state"] == "down"
    assert "litho_193nm" in litho["capability"]
