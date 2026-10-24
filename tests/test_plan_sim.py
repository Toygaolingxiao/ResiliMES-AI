"""Planning layer inside the sim: step-due risk, plan tie-break, schedule, deviations."""

from __future__ import annotations

import math

from tests.test_smt_qtime_r2 import _crowded_b_fab, _run, _three_step_fab

from resilimes.smt.fab import Fab
from resilimes.smt.planning import LotPlan, PlanningOutput
from resilimes.smt.simulate import DEVIATION_REASONS, _Sim


def _plan(
    fab: Fab,
    *,
    ranks: dict[str, int] | None = None,
    dues: dict[str, tuple[tuple[int, ...], tuple[float, ...]]] | None = None,
) -> PlanningOutput:
    """Labeled unit fixture: a hand-written plan (rank, step dues) for a toy fab."""
    lots = []
    for lot, name in enumerate(fab.lot_id):
        steps, step_due = (dues or {}).get(name, ((), ()))
        lots.append(
            LotPlan(
                index=lot,
                lot_id=name,
                route_id=fab.routes[fab.lot_route[lot]].route_id,
                order_class=fab.lot_class[lot],
                tier=2,
                released=False,
                ready_sec=0.0,
                due_sec=fab.lot_due[lot],
                step=fab.lot_step[lot],
                remaining_raw_sec=0.0,
                raw_finish_sec=0.0,
                plan_finish_sec=0.0,
                raw_slack_sec=0.0,
                plan_slack_sec=0.0,
                litho_wait_sec=0.0,
                score=0.0,
                band="on_plan",
                rank=(ranks or {}).get(name, lot + 1),
                qtime_windows=0,
                qtime_at_risk=0,
                steps=steps,
                step_due=step_due,
                latest_start=step_due,
                plan_start=step_due,
                plan_end=step_due,
            )
        )
    return PlanningOutput(
        scenario_id="toy",
        now=0.0,
        lots=lots,
        litho=[],
        availability={},
        release_until=0.0,
        runtime_ms=0.0,
    )


def _plan_sim(fab: Fab, plan: PlanningOutput) -> _Sim:
    sim = _Sim(
        fab,
        policy="resilimes",
        seed=1,
        horizon=10_000.0,
        downs=[[] for _ in fab.tool_name],
        pm=[[] for _ in fab.tool_name],
        hot_lot=None,
        hot_due=None,
        promote_hot=False,
        trace=False,
        focus_down_until=0.0,
        plan=plan,
    )
    assert sim.plan is plan
    return sim


def test_step_due_risk_is_family_wait_over_step_slack() -> None:
    fab = _three_step_fab()
    # L_AB (lot 0) at the first B step (index 1, 300 s): step dues 1500, 2000.
    plan = _plan(fab, dues={fab.lot_id[0]: ((1, 2), (1500.0, 2000.0))})
    sim = _plan_sim(fab, plan)
    sim.due[0] = 2_000.0
    sim.fam_wait[1] = 100.0
    sim.wait_sum, sim.proc_sum, sim.flow_wait = 600.0, 300.0, 2.0
    sim.risk_at = -1.0
    # wait here / (step due - now - this step's process time). No flow ratio.
    assert sim.risk(0, 0.0) == (100.0 / 1200.0, 1200.0)
    assert math.isinf(sim.risk(0, 1200.0)[0])
    # Lot 1 has no plan steps: raw slack (due - now - remaining raw), counted.
    sim.risk_at = -1.0
    raw = sim._slack(1, 0.0)
    assert sim.risk(1, 0.0)[1] == raw
    assert (1, fab.lot_step[1]) in sim.plan_fallback


def test_plan_rank_breaks_a_risk_tie() -> None:
    fab = _crowded_b_fab(others=3)
    names = fab.lot_id
    plan = _plan(fab, ranks={names[1]: 3, names[2]: 1, names[3]: 2, names[0]: 4})
    sim = _plan_sim(fab, plan)
    for lot in (1, 2, 3):
        sim.due[lot] = 30_000.0
    # No live wait: every risk is 0 and setup is equal, so the plan decides.
    ordered = sorted((1, 2, 3), key=lambda lot: sim.plain_rank(lot, 1, 0.0))
    assert ordered == [2, 3, 1]


def _equal_due_fab(others: int = 6) -> Fab:
    fab = _crowded_b_fab(others=others)
    for lot in range(1, others + 1):
        fab.lot_due[lot] = 30_000.0
    return fab


def test_schedule_head_is_the_rank_1_lot_and_dispatch_follows_it() -> None:
    fab = _equal_due_fab()
    # Plan ranks reverse the lot order: the last lot is rank 1.
    ranks = {name: len(fab.lot_id) - lot for lot, name in enumerate(fab.lot_id)}
    plan = _plan(fab, ranks=ranks)
    result = _run(fab, policy="resilimes", horizon=3_000.0, plan=plan)
    starts = [e[3][0] for e in result.events if e[0] == "start" and e[2] == 1]
    assert starts[0] == len(fab.lot_id) - 1
    assert result.plan_used and result.sched_follow >= 1


def test_every_start_is_followed_or_a_deviation_with_a_reason() -> None:
    for policy in ("resilimes", "edd", "fifo"):
        fab = _crowded_b_fab(others=12)
        ranks = {name: len(fab.lot_id) - lot for lot, name in enumerate(fab.lot_id)}
        result = _run(fab, policy=policy, horizon=20_000.0, plan=_plan(fab, ranks=ranks))
        logged = [e for e in result.events if e[0] == "deviation"]
        assert all(e[5] in DEVIATION_REASONS for e in logged)
        assert set(result.deviations) <= set(DEVIATION_REASONS)
        assert sum(result.deviations.values()) == len(logged)
        assert result.sched_follow + len(logged) == result.sched_starts
        starts = sum(1 for e in result.events if e[0] == "start")
        assert result.sched_starts == starts
        stale = result.deviations.get("schedule_stale", 0)
        assert sum(result.sched_stale_detail.values()) == stale


def test_schedule_never_changes_a_policy_that_ignores_the_plan() -> None:
    for policy in ("edd", "fifo", "cr", "smt_rule"):
        fab = _crowded_b_fab(others=12)
        plain = _run(fab, policy=policy, horizon=20_000.0)
        planned = _run(fab, policy=policy, horizon=20_000.0, plan=_plan(fab))
        assert [e for e in planned.events if e[0] != "deviation"] == plain.events
        assert planned.on_time_pct == plain.on_time_pct


def test_no_plan_is_the_qtime_r2_path() -> None:
    fab = _crowded_b_fab(others=12)
    default = _run(fab, policy="resilimes", horizon=20_000.0)
    explicit = _run(fab, policy="resilimes", horizon=20_000.0, plan=None)
    assert default.events == explicit.events
    assert not default.plan_used and default.sched_starts == 0 and default.deviations == {}


def test_schedule_heap_is_not_the_event_heap(monkeypatch) -> None:
    # The stress audit wraps ``simulate.heapq`` and samples on every pop; the
    # schedule's tool free-time heap must not go through it.
    import heapq

    from resilimes.smt import simulate as sim_mod

    pops: list[int] = []

    class Counting:
        def __getattr__(self, name: str):
            return getattr(heapq, name)

        def heappop(self, heap):
            pops.append(1)
            return heapq.heappop(heap)

    fab = _crowded_b_fab(others=12)
    monkeypatch.setattr(sim_mod, "heapq", Counting())
    _run(fab, policy="edd", horizon=20_000.0)
    plain = len(pops)
    pops.clear()
    _run(fab, policy="edd", horizon=20_000.0, plan=_plan(fab))
    assert len(pops) == plain
