"""Generated stress scenarios — pre-registered, generator-sampled.

    python -m resilimes.smt.stress_gen          # regenerate + check the spec file

Unlike the hand-written ``stress_book`` (five incidents a human picked),
this set is *sampled* by a deterministic generator from the tail of the
SMT2020 fault distribution, so nobody chose scenarios that flatter the
system:

* ``combo_down`` — two tail-repair families lose half their tools at
  once, for a repair drawn from the tail (quantile 0.85-0.99 of the
  family's exponential MTTR distribution in ``downcal``).
* ``qtime_chain_down`` — the downstream family of one of the most-used
  CQT origin->target pairs in the route set loses half its tools while
  upstream lots are in flight.
* ``hot_cluster`` — one lot is promoted VIP with a tail-tight due
  (factor 1.1-1.5 x remaining process time) and a cluster of lots
  heading to the same family is held and released together into it.
* ``down_pm_batch`` — a tail family down, a second family's PM pulled
  into the same window, and a furnace batch cap, all at once.

The committed spec file ``stress_gen_scenarios.json`` IS the
pre-registration (see docs/STRESS_GEN_PREREG.md): the generator with
``GEN_SEED`` reproduces it byte for byte, and a test pins that. Which
scenarios enter the A/B/C comparison is decided afterwards by the
no-AI gate validation (``stress_gen_validate``), never by hand: a
scenario whose rule default never trips ``rule_trigger`` in the
validation run is excluded and counted, with the count published.

Scenario application mirrors ``stress_book.apply``: forced down / PM
windows merged into the sampled calendars, one promoted hot lot, and a
``FaultPlan`` for holds and batch caps. Everything is resolved from the
fab deterministically at apply time, so the spec stays portable.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from resilimes.smt.fab import Fab
from resilimes.smt.faults import FaultPlan
from resilimes.smt.stress_book import _merge, half_tools

HOUR = 3600.0
GEN_SEED = 20261026
SCENARIO_COUNT = 16
SPEC_PATH = Path(__file__).with_name("stress_gen_scenarios.json")
ARCHETYPES = ("combo_down", "qtime_chain_down", "hot_cluster", "down_pm_batch")
TAIL_Q = (0.85, 0.99)  # repair-duration quantile band of Exp(MTTR)
HOT_FACTORS = (1.1, 1.5)  # due = factor x remaining; the tail-tight end
BATCH_CAP_WAFERS = 25


# ----------------------------------------------------------------------
def _repair_q90_h(fab: Fab, family: int) -> float:
    """90th-percentile repair hours of a family's station group."""
    mttr = fab.down_mttr.get(fab.families[family].group)
    return 0.0 if not mttr else -math.log(0.1) * mttr / HOUR


def tail_families(fab: Fab, top: int = 12) -> list[int]:
    """Families with >= 2 tools, worst (longest) tail repairs first."""
    scored = [
        (_repair_q90_h(fab, index), index)
        for index, family in enumerate(fab.families)
        if family.tools >= 2
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [index for _score, index in scored[:top]]


def cqt_pairs(fab: Fab, top: int = 10) -> list[tuple[int, int, int]]:
    """(origin family, target family, route-step count) for CQT-limited
    adjacent steps, most-used pairs first."""
    counts: dict[tuple[int, int], int] = {}
    for route in fab.routes:
        for step in range(len(route.family) - 1):
            if route.cqt_limit[step] > 0:
                pair = (route.family[step], route.family[step + 1])
                counts[pair] = counts.get(pair, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [(origin, target, n) for (origin, target), n in ranked[:top]]


def _tail_span(rng: random.Random, fab: Fab, family: int) -> tuple[float, float]:
    """(0, duration): a repair drawn from the family's MTTR tail."""
    mttr = fab.down_mttr.get(fab.families[family].group) or HOUR
    quantile = rng.uniform(*TAIL_Q)
    duration = -math.log(1.0 - quantile) * mttr
    # Capped at the 6 h validation horizon: a longer outage's recovery is
    # unobservable inside the window every arm is judged on.
    return (0.0, round(min(max(duration, HOUR), 6 * HOUR) / HOUR, 2))


def generate(fab: Fab, seed: int = GEN_SEED, count: int = SCENARIO_COUNT) -> list[dict[str, Any]]:
    """The scenario specs. Deterministic in (fab, seed, count)."""
    rng = random.Random(seed)
    tails = tail_families(fab)
    pairs = cqt_pairs(fab)
    furnaces = [i for i, fam in enumerate(fab.families) if fam.name.startswith("Diffusion")]
    archetypes = [ARCHETYPES[i % len(ARCHETYPES)] for i in range(count)]
    rng.shuffle(archetypes)
    tail_cycle = list(tails)
    rng.shuffle(tail_cycle)
    specs: list[dict[str, Any]] = []
    for index, archetype in enumerate(archetypes):
        spec: dict[str, Any] = {
            "id": f"gen_{index + 1:02d}_{archetype}",
            "archetype": archetype,
            "gen_seed": seed,
        }
        if archetype == "combo_down":
            first = tail_cycle[index % len(tail_cycle)]
            second = tail_cycle[(index + 5) % len(tail_cycle)]
            span = _tail_span(rng, fab, first)
            spec.update(
                families=[fab.families[first].name, fab.families[second].name],
                tool_fraction=0.5,
                span_h=list(span),
            )
        elif archetype == "qtime_chain_down":
            origin, target, used = pairs[index % len(pairs)]
            span = _tail_span(rng, fab, target)
            spec.update(
                origin_family=fab.families[origin].name,
                target_family=fab.families[target].name,
                pair_route_steps=used,
                tool_fraction=0.5,
                span_h=list(span),
            )
        elif archetype == "hot_cluster":
            family = tail_cycle[(index + 3) % len(tail_cycle)]
            spec.update(
                family=fab.families[family].name,
                hot_factor=round(rng.uniform(*HOT_FACTORS), 2),
                hold_lots=rng.randint(8, 20),
                hold_until_h=round(rng.uniform(0.5, 1.0), 2),
                remain_window_h=[2.0, 6.0],
            )
        else:  # down_pm_batch
            down_family = tail_cycle[(index + 1) % len(tail_cycle)]
            pm_family = tail_cycle[(index + 7) % len(tail_cycle)]
            batch_family = furnaces[index % len(furnaces)] if furnaces else down_family
            span = _tail_span(rng, fab, down_family)
            spec.update(
                down_family=fab.families[down_family].name,
                pm_family=fab.families[pm_family].name,
                batch_family=fab.families[batch_family].name,
                batch_cap_wafers=BATCH_CAP_WAFERS,
                tool_fraction=0.5,
                span_h=list(span),
            )
        specs.append(spec)
    return specs


def load_specs() -> list[dict[str, Any]]:
    return json.loads(SPEC_PATH.read_text("utf-8"))["scenarios"]


def spec_for(book: str) -> dict[str, Any]:
    for spec in load_specs():
        if spec["id"] == book:
            return spec
    raise KeyError(book)


def is_gen(book: str) -> bool:
    return any(spec["id"] == book for spec in load_specs())


# ----------------------------------------------------------------------
def _down_half(
    fab: Fab, downs: list[list[tuple[float, float]]], family_name: str, span_h: list[float]
) -> None:
    span = (span_h[0] * HOUR, span_h[1] * HOUR)
    for tool in half_tools(fab, family_name):
        downs[tool] = _merge([*downs[tool], span])


def _cluster_lots(fab: Fab, family: int, remain_window_h: list[float]) -> list[int]:
    """WIP lots whose current or next step is at ``family``, loosest first."""
    lots = []
    for lot in range(len(fab.lot_id)):
        route = fab.routes[fab.lot_route[lot]]
        step = fab.lot_step[lot]
        if family in route.family[step : step + 2]:
            lots.append(lot)
    lo, hi = remain_window_h[0] * HOUR, remain_window_h[1] * HOUR
    lots.sort(key=lambda lot: fab.routes[fab.lot_route[lot]].remain[fab.lot_step[lot]])
    return [
        lot for lot in lots if lo <= fab.routes[fab.lot_route[lot]].remain[fab.lot_step[lot]] <= hi
    ] or lots


def apply(
    fab: Fab,
    book: str,
    policy: str,
    downs: list[list[tuple[float, float]]],
    pm: list[list[tuple[float, float]]],
    kwargs: dict[str, Any],
) -> None:
    """Add the generated incident of ``book`` to ``downs``/``pm``/``kwargs``."""
    spec = spec_for(book)
    horizon = float(kwargs.get("horizon", 0.0) or math.inf)
    span = [spec["span_h"][0], min(spec["span_h"][1], horizon / HOUR)] if "span_h" in spec else None
    archetype = spec["archetype"]
    if archetype == "combo_down":
        assert span is not None
        for name in spec["families"]:
            _down_half(fab, downs, name, span)
    elif archetype == "qtime_chain_down":
        assert span is not None
        _down_half(fab, downs, spec["target_family"], span)
    elif archetype == "hot_cluster":
        family = fab.family_index[spec["family"]]
        candidates = _cluster_lots(fab, family, spec["remain_window_h"])
        if candidates:
            hot = candidates[0]
            kwargs["hot_lot"] = hot
            if policy == "resilimes":
                remain = fab.routes[fab.lot_route[hot]].remain[fab.lot_step[hot]]
                kwargs["hot_due"] = float(spec["hot_factor"]) * remain
                kwargs["promote_hot"] = True
            held = candidates[1 : 1 + int(spec["hold_lots"])]
            if held:
                kwargs["faults"] = FaultPlan(
                    hold_until={lot: float(spec["hold_until_h"]) * HOUR for lot in held}
                )
    elif archetype == "down_pm_batch":
        assert span is not None
        _down_half(fab, downs, spec["down_family"], span)
        pm_span = ((span[0] + 1.0) * HOUR, span[1] * HOUR)
        for tool in half_tools(fab, spec["pm_family"]):
            pm[tool] = _merge([*pm[tool], pm_span])
        kwargs["faults"] = FaultPlan(
            batch_family=fab.family_index[spec["batch_family"]],
            batch_cap_wafers=int(spec["batch_cap_wafers"]),
            batch_window=(span[0] * HOUR, span[1] * HOUR),
        )
    else:  # pragma: no cover - the spec file is generated, not edited
        raise KeyError(archetype)


def main() -> None:
    """Regenerate the spec file and verify the committed one matches."""
    from resilimes.smt.fab import load_fab

    specs = generate(load_fab())
    payload = {
        "generator": "resilimes.smt.stress_gen",
        "gen_seed": GEN_SEED,
        "scenarios": specs,
    }
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"
    if SPEC_PATH.exists() and SPEC_PATH.read_text("utf-8") == text:
        print(f"{SPEC_PATH.name}: up to date ({len(specs)} scenarios)")
        return
    SPEC_PATH.write_text(text, encoding="utf-8")
    print(f"{SPEC_PATH.name}: wrote {len(specs)} scenarios")


if __name__ == "__main__":
    main()
