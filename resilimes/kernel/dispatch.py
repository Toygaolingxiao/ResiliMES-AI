"""Micro dispatcher. Runs when a tool is IDLE. Higher score wins.

Availability is applied before the score. A lot whose process would cross the
next PM or planned-down start is skipped even if its DPI is the highest.
Batch tools are packed, not scored one lot at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from resilimes.kernel.score import DispatchWeights, dispatch_score


@dataclass(frozen=True)
class MaintWindow:
    start_sec: float
    end_sec: float
    kind: str


@dataclass(frozen=True)
class Candidate:
    lot_id: str
    recipe: str
    process_min: float
    dpi: float
    arrival_sec: float
    setup_sec: float = 0.0
    ped_risk: float = 0.0
    cr_reference: float = 0.0
    wafers: int = 25
    requires_batch: bool = False
    batch_size: int | None = None


@dataclass
class Decision:
    trigger: str
    equipment_id: str
    selected: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    scores: list[dict[str, float | str]] = field(default_factory=list)
    interrupted_runs_avoided: int = 0
    pm_adherence: float = 1.0

    def trace(self) -> dict[str, object]:
        return {
            "trigger": self.trigger,
            "equipment_id": self.equipment_id,
            "selected": list(self.selected),
            "skips": list(self.skips),
            "filters": list(self.filters),
            "scores": list(self.scores),
            "interrupted_runs_avoided": self.interrupted_runs_avoided,
            "pm_adherence": self.pm_adherence,
        }


def next_window(now_sec: float, windows: list[MaintWindow]) -> MaintWindow | None:
    upcoming = [item for item in windows if item.end_sec > now_sec]
    if not upcoming:
        return None
    return min(upcoming, key=lambda item: item.start_sec)


def _overrun(candidate: Candidate, now_sec: float, window: MaintWindow | None) -> str | None:
    if window is None or window.start_sec <= now_sec:
        return None
    gap_min = (window.start_sec - now_sec) / 60.0
    if candidate.process_min > gap_min:
        label = "PM" if window.kind == "pm" else "down"
        return (
            f"skipped {candidate.lot_id}: {candidate.process_min:.0f} min > "
            f"{gap_min:.0f} min to {label}"
        )
    return None


def _pack(
    lots: list[Candidate],
    *,
    now_sec: float,
    max_wait_sec: float,
) -> list[Candidate] | None:
    """Greedy fill to batch_size wafers. A partial pack ships after max-wait."""
    if not lots:
        return None
    size = lots[0].batch_size or 0
    ordered = sorted(lots, key=lambda item: (item.arrival_sec, item.lot_id))
    if size <= 0:
        return ordered
    taken: list[Candidate] = []
    wafers = 0
    for lot in ordered:
        if wafers >= size:
            break
        taken.append(lot)
        wafers += lot.wafers
    if wafers >= size:
        return taken
    oldest = now_sec - ordered[0].arrival_sec
    if oldest >= max_wait_sec:
        return ordered
    return None


def choose(
    *,
    equipment_id: str,
    candidates: list[Candidate],
    now_sec: float,
    windows: list[MaintWindow] | None = None,
    weights: DispatchWeights | None = None,
    rejected: list[tuple[str, str]] | None = None,
    max_wait_sec: float = 1800.0,
    trigger: str = "tool_idle",
) -> Decision:
    """Pick the track-in set for an IDLE tool. Does not mutate a store."""
    weights = weights or DispatchWeights()
    decision = Decision(trigger=trigger, equipment_id=equipment_id)
    for lot_id, reason in rejected or []:
        decision.filters.append(f"{lot_id}: {reason}")
    window = next_window(now_sec, list(windows or []))
    feasible: list[Candidate] = []
    for candidate in candidates:
        skip = _overrun(candidate, now_sec, window)
        if skip is not None:
            decision.skips.append(skip)
            continue
        feasible.append(candidate)
    decision.interrupted_runs_avoided = len(decision.skips)
    if window is not None and any(
        now_sec + (lot.process_min * 60.0) > window.start_sec for lot in feasible
    ):
        decision.pm_adherence = 0.0
    if not feasible:
        return decision
    if any(lot.requires_batch for lot in feasible):
        grouped: dict[str, list[Candidate]] = {}
        for lot in feasible:
            if lot.requires_batch:
                grouped.setdefault(lot.recipe, []).append(lot)
        packs: list[list[Candidate]] = []
        for group in grouped.values():
            packed = _pack(group, now_sec=now_sec, max_wait_sec=max_wait_sec)
            if packed:
                packs.append(packed)
        if not packs:
            return decision
        best = max(packs, key=lambda pack: max(_score(lot, weights) for lot in pack))
        decision.selected = [lot.lot_id for lot in best]
        for lot in best:
            decision.scores.append(_row(lot, weights, selected=True))
        return decision
    ranked = sorted(feasible, key=lambda lot: (-_score(lot, weights), lot.arrival_sec, lot.lot_id))
    for lot in ranked:
        decision.scores.append(_row(lot, weights, selected=lot is ranked[0]))
    decision.selected = [ranked[0].lot_id]
    return decision


def _score(lot: Candidate, weights: DispatchWeights) -> float:
    return dispatch_score(
        dpi=lot.dpi,
        setup_sec=lot.setup_sec,
        ped=lot.ped_risk,
        weights=weights,
    )


def _row(lot: Candidate, weights: DispatchWeights, *, selected: bool) -> dict[str, float | str]:
    score = _score(lot, weights)
    return {
        "lot_id": lot.lot_id,
        "dpi": lot.dpi,
        "setup_sec": lot.setup_sec,
        "ped_risk": lot.ped_risk,
        "cr_reference": lot.cr_reference,
        "score": score,
        "selected": 1.0 if selected else 0.0,
    }


def setup_seconds(
    matrix: dict[tuple[str, str, str], float],
    station_group: str,
    current_recipe: str,
    recipe: str,
) -> float:
    """Seconds from the matrix. A missing pair is 0, not an invented setup."""
    if current_recipe == recipe:
        return 0.0
    if (station_group, current_recipe, recipe) in matrix:
        return matrix[(station_group, current_recipe, recipe)]
    return matrix.get((station_group, "", recipe), 0.0)
