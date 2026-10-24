"""Multi-building transport layout: off is main, on adds a cross-building tier."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pytest

from resilimes.smt.fab import Fab, load_fab, transport_seconds
from resilimes.smt.freeze import FreezeConfig
from resilimes.smt.invariants import check_trace
from resilimes.smt.layout import (
    EXAMPLE_TWO_BUILDINGS,
    FabLayout,
    family_buildings,
    family_key,
    resolve,
)
from resilimes.smt.simulate import RunResult, pm_windows, run_policy, sample_downs

HOURS = 3.0
# Same golden as tests/test_sched_freeze.py: the 3 h published seed-1 run on
# main (c75ff85, unchanged on a8f68fa), timing fields left out.
MAIN_GOLDEN = {
    "resilimes": "0856dd5b0b3eb52847b421703d708d90f21a7b23307a54b01b8827f9f38c72a8",
    "edd": "7663f6893a35fcc8c72ec9c3759393d60ab12304ec1c7a3cf09ef664964afbc7",
}
SKIP = {
    "sim_s",
    "dispatch_p50_ms",
    "dispatch_p95_ms",
    "dispatch_busy_p50_ms",
    "dispatch_busy_p95_ms",
    "replan_tick_p50_ms",
    "replan_tick_p95_ms",
    "replan_tick_total_s",
    "sched_freeze",
    "layout",
}
ENV = (
    "RESILIMES_FAB_LAYOUT",
    "RESILIMES_SCHED_FREEZE",
    "RESILIMES_FREEZE_LOTS",
    "RESILIMES_FREEZE_MIN",
    "RESILIMES_SCHED_TRACK",
    "RESILIMES_TICK_LOG",
)


@pytest.fixture(scope="module")
def fab() -> Fab:
    return load_fab()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def _run(fab: Fab, policy: str, **kwargs: object) -> RunResult:
    horizon = HOURS * 3600.0
    return run_policy(
        fab,
        policy=policy,
        seed=1,
        horizon=horizon,
        downs=sample_downs(fab, 1, horizon),
        pm=pm_windows(fab, horizon),
        trace=False,
        record=True,
        **kwargs,  # type: ignore[arg-type]
    )


def _digest(result: RunResult) -> str:
    # lot_log (evidence toolkit, opt-in) is always {} here; main's golden ignores it too.
    data = {
        key: value
        for key, value in asdict(result).items()
        if key not in SKIP and not (key == "lot_log" and not value)
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def test_family_keys_follow_the_fe_be_token() -> None:
    assert family_key("Litho", "Litho_FE_92") == "Litho/FE"
    assert family_key("Litho", "LithoTrack_BE_117") == "Litho/BE"
    assert family_key("Dry_Etch", "DE_BE_11") == "Dry_Etch/BE"
    assert family_key("Def_Met", "DefMEt_FE_118") == "Def_Met/FE"
    assert family_key("Implant", "EPI_36") == "Implant"
    assert family_key("Delay_32", "Delay_32") == "Delay_32"


def test_example_layout_maps_every_family(fab: Fab) -> None:
    buildings = family_buildings(fab, EXAMPLE_TWO_BUILDINGS)
    assert len(buildings) == len(fab.families) == 106
    by_name = {fam.name: b for fam, b in zip(fab.families, buildings, strict=True)}
    assert by_name["Litho_FE_92"] == "A" and by_name["Litho_BE_93"] == "B"
    assert by_name["Implant_128"] == "A" and by_name["Delay_32"] == "A"
    assert all(b == "B" for name, b in by_name.items() if "_BE_" in name)
    assert set(buildings) == {"A", "B"}
    with pytest.raises(KeyError):
        family_buildings(fab, FabLayout(name="empty"))


def test_three_transport_tiers(fab: Fab) -> None:
    idx = fab.family_index
    buildings = family_buildings(fab, EXAMPLE_TWO_BUILDINGS)

    def move(a: str, b: str, layout: bool = True) -> float:
        return transport_seconds(fab, idx[a], idx[b], buildings if layout else None, 900.0)

    assert move("Litho_FE_92", "Litho_FE_35") == 60.0  # same bay
    assert move("Litho_FE_92", "DE_FE_1") == 180.0  # same building, other bay
    assert move("Litho_FE_92", "Litho_BE_93") == 900.0  # cross-building
    assert move("DE_BE_11", "Implant_128") == 900.0
    # Off: main's two tiers.
    assert move("Litho_FE_92", "Litho_BE_93", layout=False) == 60.0
    assert move("DE_BE_11", "Implant_128", layout=False) == 180.0


def test_resolve_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve(None) is None
    assert resolve(False) is None
    assert resolve(True) is EXAMPLE_TWO_BUILDINGS
    assert resolve("example") is EXAMPLE_TWO_BUILDINGS
    monkeypatch.setenv("RESILIMES_FAB_LAYOUT", "two_building")
    assert resolve(None) is EXAMPLE_TWO_BUILDINGS
    assert resolve(False) is None
    monkeypatch.setenv("RESILIMES_FAB_LAYOUT", "off")
    assert resolve(None) is None
    with pytest.raises(ValueError):
        resolve("nowhere")


@pytest.mark.parametrize("policy", ["resilimes", "edd"])
def test_off_is_identical_to_main(fab: Fab, policy: str, monkeypatch: pytest.MonkeyPatch) -> None:
    default = _run(fab, policy)
    assert _digest(default) == MAIN_GOLDEN[policy]
    explicit = _run(fab, policy, layout=False)
    assert _digest(explicit) == MAIN_GOLDEN[policy]
    monkeypatch.setenv("RESILIMES_FAB_LAYOUT", "off")
    assert _digest(_run(fab, policy)) == MAIN_GOLDEN[policy]
    kpi = default.layout
    assert kpi["name"] is None
    assert kpi["cross_building_moves"] == 0
    assert kpi["transport_moves"] > 0
    # One building: every move is 1 or 3 min.
    assert kpi["transport_moves"] <= kpi["transport_min"] <= 3 * kpi["transport_moves"]
    assert kpi == explicit.layout


@pytest.mark.parametrize("policy", ["resilimes", "edd"])
def test_on_adds_cross_building_moves(fab: Fab, policy: str) -> None:
    horizon = HOURS * 3600.0
    downs = sample_downs(fab, 1, horizon)
    pm = pm_windows(fab, horizon)
    on = _run(fab, policy, layout=True)
    kpi = on.layout
    assert kpi["name"] == EXAMPLE_TWO_BUILDINGS.name
    assert kpi["cross_building_moves"] > 0
    assert kpi["transport_min"] >= kpi["transport_moves"] + 14 * kpi["cross_building_moves"]
    assert _digest(on) != MAIN_GOLDEN[policy]
    # Every start waits at least its (three-tier) transport.
    assert check_trace(fab, on, downs=downs, pm=pm)["counts"]["transport"] == 0


def test_env_switch_turns_the_layout_on(fab: Fab, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESILIMES_FAB_LAYOUT", "example")
    assert _run(fab, "edd").layout["name"] == EXAMPLE_TWO_BUILDINGS.name


def test_second_transports_are_weighted_by_their_move(fab: Fab) -> None:
    result = _run(fab, "resilimes", layout=True, freeze=FreezeConfig(track=True))
    stats = result.sched_freeze
    assert stats["second_transports"] > 0
    # Staged and new tool are in one family, so one bay: 1 min each.
    assert stats["second_transport_min"] == pytest.approx(stats["second_transports"] * 1.0)
    assert result.layout["second_transport_min"] == stats["second_transport_min"]
