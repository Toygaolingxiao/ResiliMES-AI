"""A scanner pin binds only the later steps of its own layer (Q-time r2 stress fix)."""

from __future__ import annotations

from resilimes.smt.fab import Fab, Family, Route
from resilimes.smt.invariants import check_trace
from resilimes.smt.simulate import run_policy


def _two_layer_fab() -> Fab:
    """Labeled unit fixture, not SMT2020 data.

    Layer 1 is two steps on ``Litho_FE_92`` (tools 1 and 2), pinned to the
    scanner that ran the first. Layer 2 is one root step on ``Litho_FE_111``
    (tool 1), a new layer in another family.
    """
    families = [
        Family(name="Litho_FE_92", group="Litho", tools=2, tool0=0, litho=True, scanner=True),
        Family(name="Litho_FE_111", group="Litho", tools=1, tool0=2, litho=True, scanner=True),
    ]
    route = Route(
        route_id="r",
        family=[0, 0, 1],
        cycle=[100.0, 100.0, 100.0],
        recipe=[0, 0, 0],
        batch_min=[0, 0, 0],
        batch_max=[0, 0, 0],
        cqt_limit=[0.0, 0.0, 0.0],
        cqt_target=[-1, -1, -1],
        remain=[300.0, 200.0, 100.0],
        step_index={1: 0, 2: 1, 3: 2},
        dedicate_root=[0, 0, 2],
    )
    return Fab(
        families=families,
        family_index={"Litho_FE_92": 0, "Litho_FE_111": 1},
        tool_family=[0, 0, 1],
        tool_name=["Litho_FE_92-1", "Litho_FE_92-2", "Litho_FE_111-1"],
        routes=[route],
        route_index={"r": 0},
        lot_id=["L1"],
        lot_product=["p"],
        lot_route=[0],
        lot_step=[0],
        lot_due=[10_000.0],
        lot_value=[1.0],
        lot_class=["normal"],
        lot_priority=[10],
        recipe_name=[""],
        setup={},
        down_mttf={},
        down_mttr={},
        pm=[],
        focus_family=0,
        focus_tool=0,
        hot_lot=0,
        pm_calendar="",
        group_names=["Litho"],
    )


def test_root_of_a_new_layer_in_another_family_is_not_held_by_the_old_pin() -> None:
    fab = _two_layer_fab()
    downs: list[list[tuple[float, float]]] = [[], [], []]
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=5000,
        downs=downs,
        pm=[[], [], []],
        record=True,
        transport=False,
    )
    starts = [event for event in result.events if event[0] == "start"]
    assert [event[4] for event in starts] == [(0,), (1,), (2,)]
    # Layer 1 stays on its scanner; layer 2 starts on Litho_FE_111-1 at once.
    assert starts[0][2] == starts[1][2]
    assert starts[2][2] == 2
    assert starts[2][1] == 200.0
    assert result.completed_routes == 1
    assert result.repins == 0
    report = check_trace(fab, result, downs=downs, pm=[[], [], []])
    assert report["counts"]["dedication"] == 0


def test_follower_step_still_waits_for_its_pinned_scanner() -> None:
    fab = _two_layer_fab()
    # Layer 1 root runs on tool 1 (0-100 s); tool 1 is then in PM 100-500 s.
    # The follower waits for it rather than moving to the idle tool 2.
    pm = [[(100.0, 500.0)], [], []]
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=5000,
        downs=[[], [], []],
        pm=pm,
        record=True,
        transport=False,
    )
    starts = [event for event in result.events if event[0] == "start"]
    assert starts[0][2] == 0
    assert starts[1][2] == 0
    assert starts[1][1] >= 500.0
