"""Non-LLM search baseline: seeded sampling of the shift-lead lever space.

``SearchCompleter`` answers the sim-select *plan* lane the way a plain
stochastic search would: starting only from the lots, tools and engine
options in the payload, it samples candidate plans in the same typed DSL
the model proposes in (``keep_pin`` / ``reroute`` / ``boost`` /
``defer_pm`` / ``start_batch``), with a fixed seed, and lets the twin and
the do-no-harm Pareto rule judge them. It is NOT a model — no weights, no
language, no reasoning — and it says so everywhere: ``mocked`` is True,
the provider name is ``lever-search`` and every plan's ``why`` is labelled.

Its only job is to be the honest same-budget baseline of the
``sim_search`` study arm: the LLM arms get up to ``MAX_PLANS`` proposals
per escalated exception, so the search gets exactly the same budget. If
Nemotron's proposals cannot beat seeded sampling of the same lever space
under the same twin, the gain is not in the proposals.

Deterministic: the per-call RNG is seeded from the completer seed and a
hash of the payload, so the same seed on the same payload reproduces the
same plans byte for byte, while different exceptions still sample
differently. Pair it with ``selector="pareto"``: it never selects (the
select lane gets an empty, labelled no-op), because a sampler choosing
its own samples would quietly become the thing it is meant to baseline.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from typing import Any

from resilimes.llm.base import LlmResult

# Lane names must match resilimes.agents.sim_select (kept local so the llm
# package does not import the agents layer).
PLAN_LANE = "shift_lead_plan"
SELECT_LANE = "shift_lead_select"

DEFAULT_SEED = 20261026
LEVER_TYPES = ("keep_pin", "reroute", "boost", "defer_pm", "start_batch")
_PM_SHIFTS_MIN = (60, 120, 180, 240, 360, 540, -60, -120, -240)
_BOOST_TTLS_MIN = (30.0, 45.0, 60.0)
_CLASS_RANK = {"VIP": 0, "hot": 1, "normal": 2}


class SearchCompleter:
    """Seeded lever-space sampler with the ``Completer`` call shape."""

    name = "lever-search"
    mocked = True

    def __init__(self, seed: int = DEFAULT_SEED, max_plans: int = 4) -> None:
        self.seed = int(seed)
        self.max_plans = max(1, int(max_plans))

    def model_for(self, lane: str) -> str:
        # Not a model: the honest label is the sampler itself.
        return self.name

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        lane: str,
        temperature: float = 0.2,
    ) -> LlmResult:
        del temperature
        started = time.perf_counter()
        if lane == PLAN_LANE:
            plans = self._plans(_payload(messages))
            content = json.dumps({"plans": plans}, ensure_ascii=False)
        elif lane == SELECT_LANE:
            # This arm is wired with selector="pareto", so being asked to
            # select is a wiring mistake. Answer with a safe no-op (the
            # caller falls back to the rule default), never with a pick.
            content = json.dumps(
                {
                    "plans": [],
                    "note": (
                        "lever-search is not a model and never selects; "
                        "pair it with selector='pareto'"
                    ),
                }
            )
        else:
            raise ValueError(f"lever-search only answers the {PLAN_LANE} lane, not {lane!r}")
        return LlmResult(
            content=content,
            model=self.model_for(lane),
            provider=self.name,
            lane=lane,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            mocked=True,
        )

    # ------------------------------------------------------------------
    def _rng(self, payload: dict[str, Any]) -> random.Random:
        """Seeded by the completer seed plus a stable hash of the payload,
        so one seed reproduces one payload exactly but exceptions differ."""
        canonical = json.dumps(
            {
                "kind": payload.get("kind"),
                "lots": [
                    row.get("lot") for row in payload.get("lots", []) if isinstance(row, dict)
                ],
                "tools": [
                    row.get("tool") for row in payload.get("tools", []) if isinstance(row, dict)
                ],
                "facts": payload.get("facts"),
                "situation": payload.get("situation"),
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(f"{self.seed}:{canonical}".encode()).digest()
        return random.Random(int.from_bytes(digest[:8], "big"))

    def _plans(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_k = payload.get("max_plans")
        k = int(raw_k) if isinstance(raw_k, (int, float)) and raw_k else self.max_plans
        # Hard sampler cap; high enough for the D arm's K=50 budget.
        k = max(1, min(k, 64))
        rng = self._rng(payload)
        groups = _candidate_groups(payload, rng)
        picked = _pick(groups, k, rng)
        return [
            {
                "id": f"P{index + 1}",
                "levers": levers,
                "why": f"lever-search (not a model): seeded sample ({group})",
            }
            for index, (group, levers) in enumerate(picked)
        ]


# ----------------------------------------------------------------------
def _payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    raw = messages[-1].get("content") if messages else ""
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _slack(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) else 1e9


def _boost(lots: list[str], ttl_min: float | None = None) -> dict[str, Any]:
    lever: dict[str, Any] = {"type": "boost", "lots": list(lots)}
    if ttl_min is not None:
        lever["ttl_min"] = ttl_min
    return lever


def _boost_group(lots: list[dict[str, Any]], rng: random.Random) -> list[list[dict[str, Any]]]:
    """Boosts of different subsets in different orders, plus TTL variants
    and seeded random subsets — the sampler's main source of diversity."""
    names = [str(row["lot"]) for row in lots]
    if not names:
        return []
    orders = {
        "qtime": sorted(lots, key=lambda row: _slack(row, "qtime_slack_min")),
        "due": sorted(lots, key=lambda row: _slack(row, "due_slack_min")),
        "class": sorted(
            lots,
            key=lambda row: (
                _CLASS_RANK.get(str(row.get("class")), 2),
                _slack(row, "due_slack_min"),
            ),
        ),
    }
    out: list[list[dict[str, Any]]] = []
    for rows in orders.values():
        ordered = [str(row["lot"]) for row in rows]
        for take in (3, 5, 8):
            subset = ordered[: min(take, len(ordered))]
            if subset:
                out.append([_boost(subset)])
    top = [str(row["lot"]) for row in orders["qtime"][: min(5, len(names))]]
    for ttl in _BOOST_TTLS_MIN:
        out.append([_boost(top, ttl)])
    for _ in range(4):
        size = rng.randint(1, min(8, len(names)))
        out.append([_boost(rng.sample(names, size), rng.choice(_BOOST_TTLS_MIN))])
    return out


def _candidate_groups(
    payload: dict[str, Any], rng: random.Random
) -> list[tuple[str, list[list[dict[str, Any]]]]]:
    """Candidate plans grouped by shape; only payload lots/tools are used,
    and lever kinds are restricted to where PlanBuilder accepts them."""
    kind = payload.get("kind")
    lots = [row for row in payload.get("lots", []) if isinstance(row, dict) and row.get("lot")]
    names = [str(row["lot"]) for row in lots]
    tools = [
        str(row["tool"])
        for row in payload.get("tools", [])
        if isinstance(row, dict) and row.get("tool")
    ]
    raw_facts = payload.get("facts")
    facts: dict[str, Any] = raw_facts if isinstance(raw_facts, dict) else {}
    groups: list[tuple[str, list[list[dict[str, Any]]]]] = []

    boost = _boost_group(lots, rng)
    if boost:
        groups.append(("boost", boost))

    if kind == "breakdown" and names:
        urgent = [
            str(row["lot"])
            for row in lots
            if row.get("class") != "normal" or row.get("qtime_slack_min") is not None
        ]
        rest = [name for name in names if name not in urgent]
        reroute: list[list[dict[str, Any]]] = []
        keep_pin: list[list[dict[str, Any]]] = []
        if urgent:
            reroute.append([{"type": "reroute", "lots": urgent}])
        reroute.append([{"type": "reroute", "lots": names}])
        for _ in range(2):
            size = rng.randint(1, len(names))
            reroute.append([{"type": "reroute", "lots": rng.sample(names, size)}])
        keep_pin.append([{"type": "keep_pin", "lots": names}])
        if rest:
            keep_pin.append([{"type": "keep_pin", "lots": rest}])
        for hours in (2.0, 4.0):
            keep_pin.append([{"type": "keep_pin", "lots": names, "hours": hours}])
        groups.append(("reroute", reroute))
        groups.append(("keep_pin", keep_pin))
        if urgent and rest:
            groups.append(
                (
                    "reroute+keep_pin",
                    [
                        [
                            {"type": "reroute", "lots": urgent},
                            {"type": "keep_pin", "lots": rest},
                        ]
                    ],
                )
            )

    if kind == "pm_conflict":
        tool = facts.get("tool")
        if isinstance(tool, str) and tool in tools:
            shifts = list(_PM_SHIFTS_MIN)
            rng.shuffle(shifts)
            groups.append(
                (
                    "defer_pm",
                    [[{"type": "defer_pm", "tool": tool, "shift_min": shift}] for shift in shifts],
                )
            )

    if kind == "batch_underfill":
        found = re.search(r"recipe (\d+)", str(payload.get("situation", "")))
        if found:
            recipe = int(found.group(1))
            start = {"type": "start_batch", "recipe": recipe}
            plans = [[start]]
            if names:
                top = names[: min(3, len(names))]
                plans.append([start, _boost(top)])
            groups.append(("start_batch", plans))

    # Randomized filler: boost subsets x TTLs x a companion lever, so
    # large budgets (the D arm's K=50) are reachable on every kind. The
    # caller's dedup collapses repeats; all draws use the seeded RNG.
    if names:
        fill: list[list[dict[str, Any]]] = []
        total = sum(len(plans) for _name, plans in groups)
        attempts = 0
        while total < 72 and attempts < 400:
            attempts += 1
            size = rng.randint(1, min(8, len(names)))
            levers: list[dict[str, Any]] = [
                _boost(rng.sample(names, size), ttl_min=rng.choice([15, 30, 45, 60, 90, 120]))
            ]
            roll = rng.random()
            if kind == "breakdown" and roll < 0.35:
                levers.append(
                    {
                        "type": "keep_pin",
                        "lots": rng.sample(names, rng.randint(1, len(names))),
                    }
                )
            elif kind == "pm_conflict" and roll < 0.5:
                tool = facts.get("tool")
                if isinstance(tool, str) and tool in tools:
                    levers.append(
                        {
                            "type": "defer_pm",
                            "tool": tool,
                            "shift_min": rng.choice(list(_PM_SHIFTS_MIN)),
                        }
                    )
            fill.append(levers)
            total += 1
        if fill:
            groups.append(("boost_fill", fill))

    return groups


def _pick(
    groups: list[tuple[str, list[list[dict[str, Any]]]]], k: int, rng: random.Random
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Round-robin across the groups (seeded group order, seeded order
    inside each group) so the K samples span the lever shapes instead of
    K near-identical boosts; duplicates collapse by their lever JSON."""
    shuffled: list[tuple[str, list[list[dict[str, Any]]]]] = []
    for name, plans in groups:
        plans = list(plans)
        rng.shuffle(plans)
        shuffled.append((name, plans))
    order = list(range(len(shuffled)))
    rng.shuffle(order)
    seen: set[str] = set()
    picked: list[tuple[str, list[dict[str, Any]]]] = []
    cursor = [0] * len(shuffled)
    while len(picked) < k:
        progressed = False
        for index in order:
            if len(picked) >= k:
                break
            name, plans = shuffled[index]
            while cursor[index] < len(plans):
                plan = plans[cursor[index]]
                cursor[index] += 1
                key = json.dumps(plan, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                picked.append((name, plan))
                progressed = True
                break
        if not progressed:
            break
    return picked
