"""Hard investigator cases: combined, misleading and out-of-distribution faults.

The committed 24 cases (``eval/investigator_cases.json``) inject one fault at
one standard strength, and the rule baseline and the AI stand-in tie on them
(top-1 20/24 each). This module builds a harder set on the same machinery:

* ``combo``       two faults at once, at comparable magnitude; the answer key
                  is the (primary, secondary) pair.
* ``misleading``  a decoy fault whose headline indicator moves more than the
                  primary's, while an ablation (solo runs of each fault)
                  proves the decoy explains less of the WIP symptom.
* ``ood``         faults stacked on a taxonomy boundary, or at strengths /
                  shapes outside the standard set (extreme setup, partial
                  upstream, all-tools down, extreme batch cap).

Ground truth is by construction: the injected faults are the answer key, a
case is kept only when the symptom is visible against the baseline (the same
pre-check as :mod:`resilimes.insight.injector`), every truth cause's
indicator has a real signal in ``compare_windows`` / ``anomaly_scores``, and
misleading cases additionally pass the ablation check. Cases that fail any
check are dropped by the generator, never repaired by hand.

Regenerate with ``python eval/generate_hard_cases.py``; score with
``python eval/run_hard_eval.py``.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from resilimes.evidence.toolkit import HOUR, RecordedRun, Toolkit
from resilimes.insight.injector import (
    BATCH_CAP_WAFERS,
    SETUP_EXTRA_SEC,
    TAXONOMY,
    Injection,
    _peak_start,
    _symptom,
    candidates,
    faulted_run,
    main_upstream,
)
from resilimes.insight.investigator import anomaly_scores, compare_windows
from resilimes.smt.fab import Fab
from resilimes.smt.faults import FaultPlan

CATEGORIES: tuple[str, ...] = ("combo", "misleading", "ood")

# Signal gates a kept case must pass (checked on the faulted run).
PRIMARY_ANOMALY_MIN = 0.75
SECONDARY_ANOMALY_MIN = 0.4
PRIMARY_REL_MIN = 0.2
SECONDARY_REL_MIN = 0.12
# "Comparable magnitude" for a combo: the two causes' relative indicator
# changes must be within one order of magnitude. The rel changes live in
# different units per cause (tool-time share vs lots/h vs min/start), so a
# tighter cross-unit ratio would reject almost every constructible pair.
COMBO_BALANCE = (0.1, 10.0)  # |rel primary| / |rel secondary| for combo cases
OOD_BALANCE = (0.08, 12.0)
DECOY_ABLATION_MAX = 0.6  # decoy solo WIP delta <= 60% of the primary's


@dataclass
class FaultSpec:
    """One injected fault, with a strength knob the standard set does not have."""

    cause: str
    role: str = "primary"  # primary | secondary | decoy
    tool_frac: float = 0.5  # tool_down / pm_in_peak / upstream_starvation
    setup_mult: float = 1.0  # setup_thrash: multiplier on SETUP_EXTRA_SEC
    batch_cap_wafers: int = 0  # batch_cap: 0 -> the standard BATCH_CAP_WAFERS
    release_frac: float = 1.0  # release_burst: fraction of the held lots
    pm_at_peak: bool = False  # pm_in_peak: place the PM at the arrival peak
    t0_h: float = 6.0
    dur_h: float = 6.0


@dataclass
class HardCase:
    case_id: str
    category: str
    seed: int
    family: str
    upstream: str | None
    t1_h: float
    t2_h: float
    direction: str
    wip_t1: int
    wip_t2: int
    base_wip_t2: int
    truths: list[str]  # answer key, primary first; one entry for single-fault cases
    decoy: str | None
    specs: list[dict[str, Any]]  # the FaultSpec dicts that were injected
    injection: list[dict[str, Any]]  # human-readable describe per part
    signals: dict[str, dict[str, float | None]] = field(default_factory=dict)
    ablation: dict[str, float] | None = None

    @property
    def question(self) -> str:
        if self.direction == "rise":
            verb = "double" if self.wip_t1 > 0 and self.wip_t2 >= 2 * self.wip_t1 else "rise"
            return (
                f"Why did {self.family} WIP {verb} between {self.t1_h:g} h and {self.t2_h:g} h "
                f"(waiting lots {self.wip_t1} -> {self.wip_t2})?"
            )
        return (
            f"Why did {self.family} WIP fall between {self.t1_h:g} h and {self.t2_h:g} h "
            f"(waiting lots {self.wip_t1} -> {self.wip_t2})?"
        )

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["question"] = self.question
        return out

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> HardCase:
        keys = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in payload.items() if key in keys})


@dataclass
class Template:
    name: str
    category: str
    seed: int
    parts: list[FaultSpec]

    @property
    def primary(self) -> str:
        return next(spec.cause for spec in self.parts if spec.role == "primary")

    @property
    def secondary(self) -> str | None:
        found = [spec.cause for spec in self.parts if spec.role == "secondary"]
        return found[0] if found else None

    @property
    def decoy(self) -> str | None:
        found = [spec.cause for spec in self.parts if spec.role == "decoy"]
        return found[0] if found else None

    @property
    def truths(self) -> list[str]:
        out = [self.primary]
        if self.secondary:
            out.append(self.secondary)
        return out


def _frac_tools(kit: Toolkit, fam: int, frac: float) -> list[int]:
    tools = sorted(kit.tl.family_tools(fam))
    return tools[: max(1, math.ceil(len(tools) * frac))]


def build_multi_injection(specs: list[FaultSpec], kit: Toolkit, fam: int) -> Injection | None:
    """Merge several fault specs at one family into a single Injection.

    Mirrors :func:`resilimes.insight.injector.build_injection` per fault, with
    strength knobs; returns None when any part is not eligible at ``fam``.
    """
    fab = kit.fab
    downs: dict[int, list[tuple[float, float]]] = {}
    pm: dict[int, list[tuple[float, float]]] = {}
    hold: dict[int, float] = {}
    plan: dict[str, Any] = {}
    describes: list[dict[str, Any]] = []
    upstream = -1
    starts: list[float] = []
    ends: list[float] = []
    for spec in specs:
        t0, t_end = spec.t0_h * HOUR, (spec.t0_h + spec.dur_h) * HOUR
        cause = spec.cause
        if cause == "tool_down":
            tools = _frac_tools(kit, fam, spec.tool_frac)
            for tool in tools:
                downs.setdefault(tool, []).append((t0, t_end))
            starts.append(spec.t0_h)
            ends.append(spec.t0_h + spec.dur_h)
            describes.append(
                {
                    "cause": cause,
                    "role": spec.role,
                    "tools_down": [fab.tool_name[t] for t in tools],
                    "window_h": [spec.t0_h, spec.t0_h + spec.dur_h],
                }
            )
        elif cause == "pm_in_peak":
            start_h = _peak_start(kit, fam) if spec.pm_at_peak else spec.t0_h
            span = (start_h * HOUR, (start_h + 4.0) * HOUR)
            tools = _frac_tools(kit, fam, spec.tool_frac)
            for tool in tools:
                pm.setdefault(tool, []).append(span)
            starts.append(start_h)
            ends.append(start_h + 4.0)
            describes.append(
                {
                    "cause": cause,
                    "role": spec.role,
                    "tools_pm": [fab.tool_name[t] for t in tools],
                    "window_h": [start_h, start_h + 4],
                }
            )
        elif cause == "release_burst":
            held: dict[int, float] = {}
            for lot in range(len(fab.lot_id)):
                route = fab.routes[fab.lot_route[lot]]
                step = fab.lot_step[lot]
                if fam in route.family[step : step + 2]:
                    held[lot] = t0
            if len(held) < 8:
                return None
            if spec.release_frac < 1.0:
                stride = max(2, round(1.0 / spec.release_frac))
                held = {
                    lot: t for i, (lot, t) in enumerate(sorted(held.items())) if i % stride == 0
                }
            hold.update(held)
            starts.append(spec.t0_h)
            ends.append(spec.t0_h + spec.dur_h)
            describes.append(
                {
                    "cause": cause,
                    "role": spec.role,
                    "lots_held": len(held),
                    "release_frac": spec.release_frac,
                    "family": fab.families[fam].name,
                }
            )
        elif cause == "setup_thrash":
            base = kit.window_stats(fam, t0, t_end)
            if base["changeovers"] < 4 or "setup_family" in plan:
                return None
            plan.update(
                setup_family=fam,
                setup_extra_sec=SETUP_EXTRA_SEC * spec.setup_mult,
                setup_window=(t0, t_end),
            )
            starts.append(spec.t0_h)
            ends.append(spec.t0_h + spec.dur_h)
            describes.append(
                {
                    "cause": cause,
                    "role": spec.role,
                    "extra_setup_min_per_changeover": SETUP_EXTRA_SEC * spec.setup_mult / 60,
                    "window_h": [spec.t0_h, spec.t0_h + spec.dur_h],
                }
            )
        elif cause == "batch_cap":
            if not kit._is_batch(fam) or "batch_family" in plan:
                return None
            base = kit.window_stats(fam, t0, t_end)
            if base["lots_per_start"] < 2.0:
                return None
            plan.update(
                batch_family=fam,
                batch_cap_wafers=spec.batch_cap_wafers or BATCH_CAP_WAFERS,
                batch_window=(t0, t_end),
            )
            starts.append(spec.t0_h)
            ends.append(spec.t0_h + spec.dur_h)
            describes.append(
                {
                    "cause": cause,
                    "role": spec.role,
                    "batch_cap_wafers": spec.batch_cap_wafers or BATCH_CAP_WAFERS,
                    "window_h": [spec.t0_h, spec.t0_h + spec.dur_h],
                }
            )
        elif cause == "upstream_starvation":
            up = main_upstream(kit, fam)
            if up < 0:
                return None
            upstream = up
            for tool in _frac_tools(kit, up, spec.tool_frac):
                downs.setdefault(tool, []).append((t0, t_end))
            starts.append(spec.t0_h)
            ends.append(spec.t0_h + spec.dur_h)
            describes.append(
                {
                    "cause": cause,
                    "role": spec.role,
                    "upstream_family_down": fab.families[up].name,
                    "upstream_tool_frac": spec.tool_frac,
                    "window_h": [spec.t0_h, spec.t0_h + spec.dur_h],
                }
            )
        else:
            raise ValueError(f"unknown fault {cause!r}")
    faults = FaultPlan(hold_until=hold, **plan) if hold or plan else None
    return Injection(
        faults=faults,
        extra_downs=downs,
        extra_pm=pm,
        t1_h=min(starts),
        t_end_h=max(ends),
        upstream=upstream,
        describe={"parts": describes},
    )


def rebuild_hard(fab: Fab, case: HardCase, base_run: RecordedRun) -> RecordedRun:
    """Re-run the faulted simulation of a stored hard case (deterministic)."""
    kit = Toolkit(base_run)
    specs = [FaultSpec(**spec) for spec in case.specs]
    injection = build_multi_injection(specs, kit, fab.family_index[case.family])
    if injection is None:
        raise ValueError(f"case {case.case_id} no longer eligible")
    return faulted_run(fab, case.seed, injection, label=case.case_id)


def case_signals(
    kit: Toolkit, family: str, t1_h: float, t2_h: float
) -> dict[str, dict[str, float | None]]:
    """Anomaly score and uncapped relative change per cause, for validation."""
    scores = anomaly_scores(kit, family, t1_h, t2_h)
    rows = compare_windows(kit, family, t1_h, t2_h)["causes"]
    return {
        cause: {"anomaly": scores[cause], "rel_change": rows[cause]["rel_change"]}
        for cause in TAXONOMY
    }


def _rel_ok(cause: str, rel: float | None, minimum: float) -> bool:
    if rel is None:
        return False
    if cause == "batch_cap":  # its indicator points to the cause when it falls
        return rel <= -minimum
    return rel >= minimum


def _validate(template: Template, signals: dict[str, dict[str, float | None]]) -> str | None:
    """None when the signals support the answer key, else the rejection reason."""
    primary = template.primary
    if (signals[primary]["anomaly"] or 0.0) < PRIMARY_ANOMALY_MIN or not _rel_ok(
        primary, signals[primary]["rel_change"], PRIMARY_REL_MIN
    ):
        return f"primary {primary} signal too weak: {signals[primary]}"
    secondary = template.secondary
    if secondary:
        if (signals[secondary]["anomaly"] or 0.0) < SECONDARY_ANOMALY_MIN or not _rel_ok(
            secondary, signals[secondary]["rel_change"], SECONDARY_REL_MIN
        ):
            return f"secondary {secondary} signal too weak: {signals[secondary]}"
        balance = COMBO_BALANCE if template.category == "combo" else OOD_BALANCE
        rel_p = abs(signals[primary]["rel_change"] or 0.0)
        rel_s = abs(signals[secondary]["rel_change"] or 0.0)
        if rel_s <= 0 or not balance[0] <= rel_p / rel_s <= balance[1]:
            return f"magnitudes not comparable: primary rel {rel_p:.2f}, secondary rel {rel_s:.2f}"
    decoy = template.decoy
    if decoy:
        rel_d = abs(signals[decoy]["rel_change"] or 0.0)
        rel_p = abs(signals[primary]["rel_change"] or 0.0)
        if rel_d <= rel_p or (signals[decoy]["anomaly"] or 0.0) < (
            signals[primary]["anomaly"] or 0.0
        ):
            return f"decoy {decoy} not misleading enough: rel {rel_d:.2f} vs primary {rel_p:.2f}"
    return None


def make_hard_case(
    fab: Fab, template: Template, base_run: RecordedRun, *, max_tries: int = 5
) -> tuple[HardCase | None, list[str]]:
    """Search families for one template; returns the case (or None) and a log."""
    log: list[str] = []
    base = Toolkit(base_run)
    rng = random.Random(template.seed * 7919 + len(template.name))
    pool = candidates(template.primary, base, rng)
    tries = 0
    for fam in pool:
        injection = build_multi_injection(template.parts, base, fam)
        if injection is None:
            continue
        tries += 1
        if tries > max_tries:
            break
        name = fab.families[fam].name
        run = faulted_run(fab, template.seed, injection, label=template.name)
        kit = Toolkit(run)
        found = _symptom(template.primary, kit, base, fam, injection.t1_h, injection.t_end_h)
        if found is None:
            log.append(f"{name}: symptom not visible")
            continue
        direction, t2_h, w1, w2, b2 = found
        signals = case_signals(kit, name, injection.t1_h, t2_h)
        problem = _validate(template, signals)
        if problem:
            log.append(f"{name}: {problem}")
            continue
        ablation: dict[str, float] | None = None
        if template.decoy:
            deltas: dict[str, float] = {}
            for role in ("decoy", "primary"):
                spec = next(s for s in template.parts if s.role == role)
                solo = build_multi_injection([spec], base, fam)
                if solo is None:
                    deltas[role] = 0.0
                    continue
                solo_run = faulted_run(fab, template.seed, solo, label=f"{template.name}-{role}")
                solo_kit = Toolkit(solo_run)
                sign = 1.0 if direction == "rise" else -1.0
                deltas[role] = sign * (
                    solo_kit.tl.waiting_at(fam, t2_h * HOUR) - base.tl.waiting_at(fam, t2_h * HOUR)
                )
            ablation = {
                "decoy_solo_wip_delta": round(deltas["decoy"], 1),
                "primary_solo_wip_delta": round(deltas["primary"], 1),
            }
            if deltas["primary"] < 4 or deltas["decoy"] > DECOY_ABLATION_MAX * deltas["primary"]:
                log.append(f"{name}: ablation rejects decoy: {ablation}")
                continue
        case = HardCase(
            case_id=template.name,
            category=template.category,
            seed=template.seed,
            family=name,
            upstream=fab.families[injection.upstream].name if injection.upstream >= 0 else None,
            t1_h=injection.t1_h,
            t2_h=t2_h,
            direction=direction,
            wip_t1=w1,
            wip_t2=w2,
            base_wip_t2=b2,
            truths=template.truths,
            decoy=template.decoy,
            specs=[asdict(spec) for spec in template.parts],
            injection=injection.describe["parts"],
            signals=signals,
            ablation=ablation,
        )
        log.append(f"{name}: KEPT (t {case.t1_h:g}-{t2_h:g} h, wip {w1}->{w2}, base {b2})")
        return case, log
    return None, log


def _spec(cause: str, role: str, **kw: Any) -> FaultSpec:
    return FaultSpec(cause=cause, role=role, **kw)


TEMPLATES: list[Template] = [
    # ---- combo: two real causes at comparable magnitude ----------------------
    Template(
        "combo-down-burst-s1",
        "combo",
        1,
        [
            _spec("tool_down", "primary"),
            _spec("release_burst", "secondary", release_frac=0.6),
        ],
    ),
    Template(
        "combo-burst-setup-s2",
        "combo",
        2,
        [
            _spec("release_burst", "primary"),
            _spec("setup_thrash", "secondary", setup_mult=0.7),
        ],
    ),
    Template(
        "combo-pm-burst-s1",
        "combo",
        1,
        [
            _spec("pm_in_peak", "primary", pm_at_peak=True),
            _spec("release_burst", "secondary", release_frac=0.6),
        ],
    ),
    # batch_cap + setup_thrash was tried first and is not constructible on
    # this fab: batch families have < 4 baseline changeovers in the window,
    # so the setup part is never eligible there (see the generator log).
    Template(
        "combo-batch-burst-s2",
        "combo",
        2,
        [
            _spec("batch_cap", "primary"),
            _spec("release_burst", "secondary", release_frac=0.6),
        ],
    ),
    Template(
        "combo-starve-setup-s1",
        "combo",
        1,
        [
            _spec("upstream_starvation", "primary"),
            _spec("setup_thrash", "secondary", setup_mult=0.7),
        ],
    ),
    Template(
        "combo-down-setup-s2",
        "combo",
        2,
        [
            _spec("tool_down", "primary"),
            _spec("setup_thrash", "secondary", setup_mult=0.7),
        ],
    ),
    # ---- misleading: decoy indicator louder, ablation proves it is not the cause
    Template(
        "mislead-down-burst-s2",
        "misleading",
        2,
        [
            _spec("release_burst", "primary"),
            _spec("tool_down", "decoy", tool_frac=0.15),
        ],
    ),
    Template(
        "mislead-pm-batch-s1",
        "misleading",
        1,
        [
            _spec("batch_cap", "primary"),
            _spec("pm_in_peak", "decoy"),
        ],
    ),
    Template(
        "mislead-down-setup-s1",
        "misleading",
        1,
        [
            _spec("setup_thrash", "primary"),
            _spec("tool_down", "decoy", tool_frac=0.15),
        ],
    ),
    Template(
        "mislead-down-batch-s2",
        "misleading",
        2,
        [
            _spec("batch_cap", "primary"),
            _spec("tool_down", "decoy", tool_frac=0.15),
        ],
    ),
    Template(
        "mislead-pm-burst-s2",
        "misleading",
        2,
        [
            _spec("release_burst", "primary"),
            _spec("pm_in_peak", "decoy", pm_at_peak=True),
        ],
    ),
    Template(
        "mislead-pm-setup-s1",
        "misleading",
        1,
        [
            _spec("setup_thrash", "primary"),
            _spec("pm_in_peak", "decoy"),
        ],
    ),
    Template(
        "mislead-pm-down-s2",
        "misleading",
        2,
        [
            _spec("tool_down", "primary"),
            _spec("pm_in_peak", "decoy"),
        ],
    ),
    Template(
        "mislead-pm-batch-s2",
        "misleading",
        2,
        [
            _spec("batch_cap", "primary"),
            _spec("pm_in_peak", "decoy"),
        ],
    ),
    Template(
        "mislead-starve-down-s1",
        "misleading",
        1,
        [
            _spec("tool_down", "primary"),
            _spec("upstream_starvation", "decoy"),
        ],
    ),
    Template(
        "mislead-starve-burst-s2",
        "misleading",
        2,
        [
            _spec("release_burst", "primary"),
            _spec("upstream_starvation", "decoy"),
        ],
    ),
    Template(
        "mislead-down-starve-s1",
        "misleading",
        1,
        [
            _spec("upstream_starvation", "primary"),
            _spec("tool_down", "decoy"),
        ],
    ),
    Template(
        "mislead-setup-burst-s2",
        "misleading",
        2,
        [
            _spec("release_burst", "primary"),
            _spec("setup_thrash", "decoy"),
        ],
    ),
    Template(
        "mislead-setup-down-s1",
        "misleading",
        1,
        [
            _spec("tool_down", "primary"),
            _spec("setup_thrash", "decoy"),
        ],
    ),
    Template(
        "mislead-down-burst-s1",
        "misleading",
        1,
        [
            _spec("release_burst", "primary"),
            _spec("tool_down", "decoy", tool_frac=0.15),
        ],
    ),
    Template(
        "mislead-pm-burst-s1",
        "misleading",
        1,
        [
            _spec("release_burst", "primary"),
            _spec("pm_in_peak", "decoy", pm_at_peak=True),
        ],
    ),
    # ---- ood: boundary stacks and out-of-range strengths ----------------------
    # batch_cap + setup_thrash stack is not constructible here (batch
    # families fail the setup part's changeover eligibility); the stack
    # below pairs the extreme batch cap with a capacity loss instead.
    Template(
        "ood-batch-down-stack-s2",
        "ood",
        2,
        [
            _spec("batch_cap", "primary", batch_cap_wafers=10),
            _spec("tool_down", "secondary"),
        ],
    ),
    Template(
        "ood-pm-burst-s1",
        "ood",
        1,
        [
            _spec("pm_in_peak", "primary", pm_at_peak=True),
            _spec("release_burst", "secondary"),
        ],
    ),
    Template(
        "ood-setup-extreme-s2",
        "ood",
        2,
        [
            _spec("setup_thrash", "primary", setup_mult=2.0),
        ],
    ),
    Template(
        "ood-starve-partial-s1",
        "ood",
        1,
        [
            _spec("upstream_starvation", "primary", tool_frac=0.65),
        ],
    ),
    Template(
        "ood-down-total-s2",
        "ood",
        2,
        [
            _spec("tool_down", "primary", tool_frac=1.0, dur_h=3.0),
        ],
    ),
    Template(
        "ood-burst-late-s2",
        "ood",
        2,
        [
            _spec("release_burst", "primary", t0_h=9.0, dur_h=4.0),
        ],
    ),
]
