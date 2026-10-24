"""Typed, deterministic evidence queries over one recorded SMT2020 run.

``record_run`` runs the simulator once with ``record=True, lot_log=True`` (and
an optional fault plan). ``Toolkit`` answers small typed questions about that
run. Every result is JSON-ready, rounded the way it may be quoted, and fed to a
``FactRegistry`` so a later fact check knows which ids and numbers are real.
Times in and out are hours after the snapshot.
"""

from __future__ import annotations

import bisect
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from resilimes.evidence.factcheck import FactRegistry
from resilimes.evidence.lateness import decompose, late_lots, rounded_minutes, visit_waits
from resilimes.evidence.timeline import BUSY, DOWN, IDLE, PM, RESERVED, Timeline, build_timeline
from resilimes.smt.fab import Fab
from resilimes.smt.faults import FaultPlan
from resilimes.smt.simulate import RunResult, pm_windows, run_policy, sample_downs

HOUR = 3600.0


@dataclass
class RecordedRun:
    fab: Fab
    seed: int
    horizon: float
    policy: str
    downs: list[list[tuple[float, float]]]
    pm: list[list[tuple[float, float]]]
    result: RunResult
    timeline: Timeline
    faults: FaultPlan | None = None
    label: str = "baseline"
    notes: dict[str, Any] = field(default_factory=dict)


def record_run(
    fab: Fab,
    *,
    seed: int,
    horizon: float,
    policy: str = "resilimes",
    faults: FaultPlan | None = None,
    extra_downs: dict[int, list[tuple[float, float]]] | None = None,
    extra_pm: dict[int, list[tuple[float, float]]] | None = None,
    label: str = "baseline",
    hot_lot: int | None = None,
    drop_downs: dict[int, list[tuple[float, float]]] | None = None,
    drop_pm: dict[int, list[tuple[float, float]]] | None = None,
) -> RecordedRun:
    """One recorded run. ``hot_lot`` promotes one lot; ``drop_*`` remove the down or
    PM spans of a tool that overlap the given windows (counterfactual re-runs)."""
    downs = [list(spans) for spans in sample_downs(fab, seed, horizon)]
    pm = [list(spans) for spans in pm_windows(fab, horizon)]
    for tool, spans in (extra_downs or {}).items():
        downs[tool] = sorted(downs[tool] + list(spans))
    for tool, spans in (extra_pm or {}).items():
        pm[tool] = sorted(pm[tool] + list(spans))
    for tool, windows in (drop_downs or {}).items():
        downs[tool] = [span for span in downs[tool] if not _overlaps(span, windows)]
    for tool, windows in (drop_pm or {}).items():
        pm[tool] = [span for span in pm[tool] if not _overlaps(span, windows)]
    result = run_policy(
        fab,
        policy=policy,
        seed=seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        record=True,
        lot_log=True,
        faults=faults,
        hot_lot=hot_lot,
        promote_hot=hot_lot is not None,
    )
    timeline = build_timeline(
        fab, result, downs=downs, pm=pm, hold_until=faults.hold_until if faults else None
    )
    return RecordedRun(
        fab=fab,
        seed=seed,
        horizon=horizon,
        policy=policy,
        downs=downs,
        pm=pm,
        result=result,
        timeline=timeline,
        faults=faults,
        label=label,
    )


def _overlaps(span: tuple[float, float], windows: list[tuple[float, float]]) -> bool:
    return any(span[0] < right and left < span[1] for left, right in windows)


def _h(seconds: float) -> float:
    return round(seconds / HOUR, 1)


class Toolkit:
    """The only door from an AI feature to run data."""

    def __init__(self, run: RecordedRun, registry: FactRegistry | None = None) -> None:
        self.run = run
        self.fab = run.fab
        self.tl = run.timeline
        self.registry = registry or FactRegistry()
        self.calls: list[dict[str, Any]] = []
        self._tool_family = run.fab.tool_family

    # ---- plumbing -----------------------------------------------------------------------
    def _out(self, name: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        self.registry.add(result)
        self.calls.append({"tool": name, "args": args})
        return result

    def family_id(self, name_or_index: str | int) -> int:
        if isinstance(name_or_index, int):
            return name_or_index
        text = str(name_or_index).strip()
        if text in self.fab.family_index:
            return self.fab.family_index[text]
        lowered = {key.lower(): value for key, value in self.fab.family_index.items()}
        if text.lower() in lowered:
            return lowered[text.lower()]
        raise KeyError(f"unknown family {text!r}")

    def lot_index(self, lot_id: str) -> int:
        try:
            return self.fab.lot_id.index(lot_id)
        except ValueError as exc:
            raise KeyError(f"unknown lot {lot_id!r}") from exc

    # ---- queries ------------------------------------------------------------------------
    def family_wip(
        self, family: str | int, start_h: float, end_h: float, step_min: float = 60.0
    ) -> dict[str, Any]:
        """Lots waiting and in process at the family, sampled every ``step_min``."""
        fam = self.family_id(family)
        points = []
        moment = start_h * HOUR
        stop = min(end_h * HOUR, self.run.horizon)
        while moment <= stop + 1e-6:
            points.append(
                {
                    "hour": round(moment / HOUR, 2),
                    "waiting": self.tl.waiting_at(fam, moment),
                    "in_process": self.tl.in_process_at(fam, moment),
                }
            )
            moment += step_min * 60.0
        result = {"family": self.fab.families[fam].name, "series": points}
        return self._out(
            "family_wip", {"family": family, "start_h": start_h, "end_h": end_h}, result
        )

    def window_stats(self, fam: int, start: float, end: float) -> dict[str, float]:
        """Raw (unrounded) family stats on [start, end) seconds. Used by baselines too."""
        tools = list(self.tl.family_tools(fam))
        states = {DOWN: 0.0, PM: 0.0, BUSY: 0.0, RESERVED: 0.0, IDLE: 0.0}
        for tool in tools:
            for key, value in self.tl.state_seconds(tool, start, end).items():
                states[key] += value
        rows = self.tl.by_family.get(fam, [])
        readies = self.tl._ready_index.get(fam, [])
        lo = bisect.bisect_left(readies, start)
        hi = bisect.bisect_left(readies, end)
        arrivals = hi - lo
        waits = [
            v.start - v.ready
            for v in rows[: bisect.bisect_left(readies, end)]
            if v.start is not None and start <= v.start < end
        ]
        tool_set = set(tools)
        setups = [(t, tool, sec) for t, tool, sec in self.tl.setups if tool in tool_set]
        setup_sec = sum(sec for t, _tool, sec in setups if start <= t < end)
        changeovers = sum(1 for t, _tool, sec in setups if start <= t < end and sec > 0)
        starts = [(t, n) for t, tool, n in self.tl.starts if tool in tool_set and start <= t < end]
        span_h = max(1e-9, (end - start) / HOUR)
        return {
            "hours": span_h,
            "tools": float(len(tools)),
            "arrivals": float(arrivals),
            "arrivals_per_h": arrivals / span_h,
            "lot_starts": float(len(waits)),
            "tool_starts": float(len(starts)),
            "lots_per_start": (sum(n for _t, n in starts) / len(starts)) if starts else 0.0,
            "down_tool_h": states[DOWN] / HOUR,
            "pm_tool_h": states[PM] / HOUR,
            "busy_tool_h": states[BUSY] / HOUR,
            "reserved_tool_h": states[RESERVED] / HOUR,
            "idle_tool_h": states[IDLE] / HOUR,
            "setup_min": setup_sec / 60.0,
            "setup_min_per_start": (setup_sec / 60.0 / len(starts)) if starts else 0.0,
            "changeovers": float(changeovers),
            "mean_wait_min": (sum(waits) / len(waits) / 60.0) if waits else 0.0,
            "waiting_start": float(self.tl.waiting_at(fam, start)),
            "waiting_end": float(self.tl.waiting_at(fam, end)),
        }

    def family_window(self, family: str | int, start_h: float, end_h: float) -> dict[str, Any]:
        """Arrivals, starts, tool hours by state, setup, batch fill and waits in a window."""
        fam = self.family_id(family)
        raw = self.window_stats(fam, start_h * HOUR, end_h * HOUR)
        result: dict[str, Any] = {
            "family": self.fab.families[fam].name,
            "window_h": [start_h, end_h],
            "batch_family": self._is_batch(fam),
        }
        for key, value in raw.items():
            if key == "hours":
                continue
            result[key] = round(value, 2 if key == "lots_per_start" else 1)
        return self._out(
            "family_window", {"family": family, "start_h": start_h, "end_h": end_h}, result
        )

    def tool_states(self, family: str | int, start_h: float, end_h: float) -> dict[str, Any]:
        """Per tool: hours down / PM / busy / idle, and the down and PM windows that overlap."""
        fam = self.family_id(family)
        start, end = start_h * HOUR, end_h * HOUR
        tools = []
        for tool in self.tl.family_tools(fam):
            states = self.tl.state_seconds(tool, start, end)
            downs = [
                [_h(max(0.0, a)), _h(b)] for a, b in self.run.downs[tool] if a < end and b > start
            ]
            pms = [[_h(max(0.0, a)), _h(b)] for a, b in self.run.pm[tool] if a < end and b > start]
            tools.append(
                {
                    "tool": self.fab.tool_name[tool],
                    "down_h": _h(states[DOWN]),
                    "pm_h": _h(states[PM]),
                    "busy_h": _h(states[BUSY]),
                    "idle_h": _h(states[IDLE] + states[RESERVED]),
                    "down_windows_h": downs[:6],
                    "pm_windows_h": pms[:6],
                }
            )
        result = {
            "family": self.fab.families[fam].name,
            "window_h": [start_h, end_h],
            "tools": tools,
        }
        return self._out(
            "tool_states", {"family": family, "start_h": start_h, "end_h": end_h}, result
        )

    def upstream(self, family: str | int, start_h: float, end_h: float) -> dict[str, Any]:
        """Where the family's arrivals in the window came from (previous family of each lot)."""
        fam = self.family_id(family)
        start, end = start_h * HOUR, end_h * HOUR
        counts = self.upstream_counts(fam, start, end)
        rows = [
            {"family": self.fab.families[src].name if src >= 0 else "snapshot_wip", "arrivals": n}
            for src, n in counts.most_common(8)
        ]
        result = {"family": self.fab.families[fam].name, "window_h": [start_h, end_h], "from": rows}
        return self._out("upstream", {"family": family, "start_h": start_h, "end_h": end_h}, result)

    def upstream_counts(self, fam: int, start: float, end: float) -> Counter[int]:
        counts: Counter[int] = Counter()
        for visit in self.tl.by_family.get(fam, []):
            if not (start <= visit.ready < end):
                continue
            prev = -1
            for other in self.tl.visits.get(visit.lot, []):
                if other is visit:
                    break
                prev = other.family
            counts[prev] += 1
        return counts

    def route_upstream(self, fam: int) -> Counter[int]:
        """Static: which family precedes ``fam`` on the routes, weighted by lots on them."""
        counts: Counter[int] = Counter()
        per_route = Counter(self.fab.lot_route)
        for index, route in enumerate(self.fab.routes):
            for step in range(1, len(route.family)):
                if route.family[step] == fam and route.family[step - 1] != fam:
                    counts[route.family[step - 1]] += per_route.get(index, 0)
        return counts

    def lot_trace(self, lot_id: str, limit: int = 12) -> dict[str, Any]:
        """The lot's last visits: family, tool, ready/start/leave hours, outcome."""
        lot = self.lot_index(lot_id)
        visits = self.tl.visits.get(lot, [])[-limit:]
        rows = [
            {
                "step": v.step,
                "family": self.fab.families[v.family].name,
                "tool": self.fab.tool_name[v.tool] if v.tool >= 0 else None,
                "ready_h": round(v.ready / HOUR, 2),
                "start_h": round(v.start / HOUR, 2) if v.start is not None else None,
                "leave_h": round(v.leave / HOUR, 2) if v.leave is not None else None,
                "wait_min": round(((v.start or v.leave or self.run.horizon) - v.ready) / 60.0, 1),
                "outcome": v.outcome,
            }
            for v in visits
        ]
        result = {"lot": lot_id, "visits": rows}
        return self._out("lot_trace", {"lot_id": lot_id}, result)

    def late_lots(self, limit: int = 30) -> dict[str, Any]:
        rows = []
        for lot in late_lots(self.tl)[:limit]:
            end = self.tl.completed.get(lot, self.run.horizon)
            rows.append(
                {
                    "lot": self.fab.lot_id[lot],
                    "product": self.fab.lot_product[lot],
                    "due_h": _h(self.fab.lot_due[lot]),
                    "end_h": _h(end),
                    "finished": lot in self.tl.completed,
                    "late_h": _h(end - self.fab.lot_due[lot]),
                }
            )
        result = {"horizon_h": _h(self.run.horizon), "late_lots": rows}
        return self._out("late_lots", {"limit": limit}, result)

    def lot_lateness(self, lot_id: str) -> dict[str, Any]:
        """Exact split of the lot's lateness (minutes, rounded so the parts add up)."""
        lot = self.lot_index(lot_id)
        raw = decompose(self.tl, lot)
        history = rounded_minutes(raw["history_sec"])
        overrun = rounded_minutes(raw["overrun_sec"])
        result = {
            "lot": lot_id,
            "due_h": _h(raw["due_sec"]),
            "end_h": _h(raw["end_sec"]),
            "finished": raw["finished"],
            "late_min": round(sum(overrun.values()), 1),
            "time_in_fab_min": round(sum(history.values()), 1),
            "allowance_min": round(sum(history.values()) - sum(overrun.values()), 1)
            if raw["due_sec"] >= 0
            else round(raw["due_sec"] / 60.0, 1),
            "while_late_min": {k: v for k, v in overrun.items() if v},
            "whole_stay_min": {k: v for k, v in history.items() if v},
            "exact": raw["exact"],
        }
        return self._out("lot_lateness", {"lot_id": lot_id}, result)

    def lot_waits(self, lot_id: str, top: int = 6) -> dict[str, Any]:
        """Where the lot waited (whole stay): the longest queue waits by step, with buckets,
        and how late it would still be with no waiting at all."""
        lot = self.lot_index(lot_id)
        end = self.tl.completed.get(lot, self.run.horizon)
        rows = sorted(visit_waits(self.tl, lot, 0.0, end), key=lambda r: -r["wait_sec"])
        history = decompose(self.tl, lot)["history_sec"]
        work = history["processing"] + history["setup"] + history["transport"]
        waits = []
        for row in rows[:top]:
            visit = row["visit"]
            buckets = rounded_minutes(row["buckets"])
            waits.append(
                {
                    "step": visit.step,
                    "family": self.fab.families[visit.family].name,
                    "from_h": _h(row["window"][0]),
                    "to_h": _h(row["window"][1]),
                    "wait_min": round(sum(buckets.values()), 1),
                    "buckets_min": {k: v for k, v in buckets.items() if v},
                }
            )
        result = {
            "lot": lot_id,
            "steps_waited": len(rows),
            "total_wait_min": round(sum(r["wait_sec"] for r in rows) / 60.0, 1),
            "longest_waits": waits,
            "no_wait_late_min": round((work - self.fab.lot_due[lot]) / 60.0, 1),
        }
        return self._out("lot_waits", {"lot_id": lot_id}, result)

    def maintenance(self, family: str | int) -> dict[str, Any]:
        """Downtime model (downcal MTTF/MTTR) and PM calendar for the family's tool group."""
        fam = self.family_id(family)
        info = self.fab.families[fam]
        group = info.group
        pms = [
            {"calendar": name, "every_h": _h(interval), "duration_h": _h(duration)}
            for f, _first, interval, duration, name in self.fab.pm
            if f == fam
        ]
        result = {
            "family": info.name,
            "group": group,
            "mttf_h": _h(self.fab.down_mttf.get(group, 0.0))
            if group in self.fab.down_mttf
            else None,
            "mttr_h": _h(self.fab.down_mttr.get(group, 0.0))
            if group in self.fab.down_mttr
            else None,
            "pm_calendars": pms,
        }
        return self._out("maintenance", {"family": family}, result)

    def _is_batch(self, fam: int) -> bool:
        for route in self.fab.routes:
            for step, owner in enumerate(route.family):
                if owner == fam and route.batch_max[step] > 0:
                    return True
        return False
