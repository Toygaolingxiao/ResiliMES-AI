"""Live A/B/C runner: notes events applied to the real SMT2020 simulator.

Implements the :class:`resilimes.insight.notes_ab.ScheduleRunner` protocol
against ``resilimes.smt.simulate.run_policy`` so
``scripts/compare_notes_ab.py --runner live`` produces fab numbers instead
of mock ledger units. The runner **never reads ``truth``** (the protocol's
gold map): correctness has to emerge from the schedule itself.

Event mapping (validated events only; anything else counts as
``unsupported`` and never enters the simulation):

- ``planned_down`` -> extra windows appended to the ``downs`` list passed
  to ``make_sim``. Equipment naming a tool (``Litho_FE_92-1``) downs that
  tool; naming a family (``Litho_FE_98``) downs every tool of the family.
  Windows are clipped to the run horizon; a window that does not intersect
  it at all is unsupported (it cannot affect this run).
- ``priority_change`` -> the run's own due/class handling: a replaced
  ``Fab`` copy whose ``lot_due`` / ``lot_class`` carry the event
  (``new_due_h`` is hours from the note's timestamp; ``vip`` -> ``VIP``,
  ``hot`` -> ``hot``, ``normal`` -> ``normal``). The planning layer and
  every policy read dues/classes from the fab, so the change flows through
  the existing mechanism. Lots that are not SMT2020 WIP (sample-bay
  ``LOT-####`` ids) are unsupported.
- ``hold`` with ``scope == "lot"`` -> ``FaultPlan.hold_until[lot] =
  horizon``: the note states no release time, so the lot stays held for
  the whole run (it is not queued at t=0 and never arrives inside the
  window). ``scope == "step"`` is unsupported: the simulator has no
  step-hold mechanism (fault-plan holds are per lot), and the notes' step
  names are sample-bay steps, not SMT route steps.
- ``capacity_derate`` -> unsupported. The simulator has no capacity
  scaling: tool availability is binary (``downs``) and process times are
  static route data. Faking a partial derate as a full down would
  overstate it, so the event is counted, not applied.

Time anchor: sim t=0 is 00:00 UTC of the earliest note's day (the notes
dataset's scenario day, 2026-10-22). ``planned_down`` starts and
``priority_change`` dues are resolved against that anchor and the note
timestamps (read from the notes file's ``id``/``ts`` fields only — never
its gold). Unknown note ids fall back to the anchor for due resolution.

Arms share the fab, seed, sampled breakdowns and PM calendar; only the
event feed differs. With no fab-affecting events the run is the plain
baseline call, bit-identical to ``run_policy`` on the same inputs.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from resilimes.insight.notes import load_notes
from resilimes.insight.notes_ab import ArmOutcome
from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.faults import FaultPlan
from resilimes.smt.simulate import pm_windows, run_policy, sample_downs

# Default book: seed 1 on the full SMT2020 extract. Horizon default is set
# from the measured single-arm cost (see DEFAULT_HORIZON_H note in
# build_runner); RESILIMES_NOTES_HORIZON_H overrides it.
_CLASS_MAP = {"vip": "VIP", "hot": "hot", "normal": "normal"}


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


class LiveScheduleRunner:
    """One scenario/seed/horizon, three event feeds (arms A/B/C)."""

    is_mock = False

    def __init__(
        self,
        *,
        scenario: str = "smt2020",
        seed: int = 1,
        horizon_hours: float = 24.0,
        policy: str = "resilimes",
        notes_path: str | None = None,
        fab: Fab | None = None,
    ) -> None:
        if scenario != "smt2020":
            raise ValueError(f"unknown scenario {scenario!r} (only 'smt2020')")
        self.scenario = scenario
        self.seed = int(seed)
        self.horizon_hours = float(horizon_hours)
        self.policy = policy
        self.name = f"live-{scenario}-{policy}"
        self.fab = fab if fab is not None else load_fab()
        self._lot_index = {lot_id: i for i, lot_id in enumerate(self.fab.lot_id)}
        self._tool_index = {name: i for i, name in enumerate(self.fab.tool_name)}
        self._family_tools: dict[int, list[int]] = {}
        for tool, fam in enumerate(self.fab.tool_family):
            self._family_tools.setdefault(fam, []).append(tool)
        # Note timestamps (id -> sim-second offset) and the t=0 anchor.
        items = load_notes(notes_path)
        stamps = {str(n["id"]): _parse_iso(str(n["ts"])) for n in items}
        anchor_day = min(stamps.values()).date() if stamps else datetime(2026, 10, 22, tzinfo=UTC).date()
        self._anchor = datetime(anchor_day.year, anchor_day.month, anchor_day.day, tzinfo=UTC)
        self._note_ts = {
            note_id: (ts - self._anchor).total_seconds() for note_id, ts in stamps.items()
        }

    # -- event mapping ----------------------------------------------------
    def _resolve_tools(self, equipment: str) -> list[int] | None:
        if equipment in self._tool_index:
            return [self._tool_index[equipment]]
        fam = self.fab.family_index.get(equipment)
        if fam is not None:
            return list(self._family_tools.get(fam, []))
        return None

    def _build_inputs(
        self, events: list[dict[str, Any]]
    ) -> tuple[Fab, dict[str, Any], list[dict[str, Any]], int]:
        """Translate events into simulator inputs. Returns (fab, run_policy
        kwargs, applied events, unsupported count). Pure input construction:
        no simulation runs here, so tests can probe exactly what an arm
        would feed the simulator."""
        horizon = self.horizon_hours * 3600.0
        downs = sample_downs(self.fab, self.seed, horizon)
        pm = pm_windows(self.fab, horizon)
        hold_until: dict[int, float] = {}
        due_overrides: dict[int, float] = {}
        class_overrides: dict[int, str] = {}
        applied: list[dict[str, Any]] = []
        unsupported = 0
        for event in events:
            etype = event.get("type")
            if etype == "planned_down":
                tools = self._resolve_tools(str(event.get("equipment", "")))
                if tools is None:
                    unsupported += 1
                    continue
                start = (_parse_iso(str(event["start"])) - self._anchor).total_seconds()
                end = start + float(event["duration_min"]) * 60.0
                lo, hi = max(0.0, start), min(horizon, end)
                if hi <= lo:
                    unsupported += 1  # window never intersects this run
                    continue
                for tool in tools:
                    downs[tool].append((lo, hi))
                    downs[tool].sort()
                applied.append(event)
            elif etype == "priority_change":
                idx = self._lot_index.get(str(event.get("lot", "")))
                if idx is None:
                    unsupported += 1
                    continue
                if "new_due_h" in event:
                    base = self._note_ts.get(str(event.get("_note_id", "")), 0.0)
                    due_overrides[idx] = base + float(event["new_due_h"]) * 3600.0
                if "priority" in event:
                    class_overrides[idx] = _CLASS_MAP[str(event["priority"]).lower()]
                applied.append(event)
            elif etype == "hold" and event.get("scope") == "lot":
                idx = self._lot_index.get(str(event.get("lot", "")))
                if idx is None:
                    unsupported += 1
                    continue
                hold_until[idx] = horizon  # no release time stated: held all run
                applied.append(event)
            else:
                # hold scope=step, capacity_derate, anything unknown: no
                # faithful mechanism exists (see module docstring).
                unsupported += 1
        fab = self.fab
        if due_overrides or class_overrides:
            lot_due = list(self.fab.lot_due)
            lot_class = list(self.fab.lot_class)
            for idx, due in due_overrides.items():
                lot_due[idx] = due
            for idx, klass in class_overrides.items():
                lot_class[idx] = klass
            fab = replace(self.fab, lot_due=lot_due, lot_class=lot_class)
        kwargs: dict[str, Any] = {
            "policy": self.policy,
            "seed": self.seed,
            "horizon": horizon,
            "downs": downs,
            "pm": pm,
        }
        if hold_until:
            kwargs["faults"] = FaultPlan(hold_until=hold_until)
        return fab, kwargs, applied, unsupported

    # -- protocol -----------------------------------------------------------
    def run(self, events: list[dict[str, Any]], truth: Any) -> ArmOutcome:
        del truth  # the live runner never reads gold; see module docstring
        fab, kwargs, applied, unsupported = self._build_inputs(events)
        result = run_policy(fab, **kwargs)
        return ArmOutcome(
            avoidable_qtime=int(result.qtime_miss_class.get("avoidable", 0)),
            qtime_violations=int(result.qtime_violations),
            on_time_pct=float(result.on_time_pct),
            completed=int(result.completed_routes),
            applied=applied,
            unsupported=unsupported,
        )


def build_runner(
    scenario: str = "smt2020",
    *,
    seed: int = 1,
    horizon_hours: float | None = None,
    policy: str = "resilimes",
    notes_path: str | None = None,
) -> LiveScheduleRunner:
    """Factory used by ``scripts/compare_notes_ab.py --runner live``.

    Defaults: seed 1, ``resilimes`` policy, horizon from
    ``RESILIMES_NOTES_HORIZON_H`` or 24 h (one day on the notes' scenario
    day; a single arm measures ~1.5-2 min in-process on this machine, so
    the full three-arm compare takes ~5-6 min).
    """
    if horizon_hours is None:
        env = os.environ.get("RESILIMES_NOTES_HORIZON_H", "").strip()
        horizon_hours = float(env) if env else 24.0
    return LiveScheduleRunner(
        scenario=scenario,
        seed=seed,
        horizon_hours=horizon_hours,
        policy=policy,
        notes_path=notes_path,
    )
