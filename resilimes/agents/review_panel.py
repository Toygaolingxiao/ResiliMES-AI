"""Qualitative review of a book the scheduler already built.

Three reviewers read the same lot and tool ids. They do not recompute KPIs
and they do not change the committed schedule. Suggestions are advice.
Nightshift down, a bad payload, or an id that is not in the plant becomes a
labeled deterministic review.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from resilimes.agents.facts import narrative_mismatches
from resilimes.agents.jsonutil import SchemaError, parse_model
from resilimes.domain.models import Critique, Plant, Schedule
from resilimes.llm.base import Completer

RoleName = Literal["process_equipment", "production_control", "risk"]
VerdictName = Literal["approve", "approve-with-changes", "reject"]

ROLES: tuple[RoleName, ...] = ("process_equipment", "production_control", "risk")

_LANE = {
    "process_equipment": "review.process",
    "production_control": "review.production",
    "risk": "review.risk",
}

_TITLES = {
    "process_equipment": "Process and equipment engineer",
    "production_control": "Production control and delivery owner",
    "risk": "Risk reviewer",
}


class Concern(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    ids: list[str] = Field(default_factory=list)


class ReviewReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    verdict: VerdictName
    concerns: list[Concern] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


def run_review_panel(
    provider: Completer,
    plant: Plant,
    schedule: Schedule,
    critique: Critique,
    *,
    allow_model: bool,
) -> dict[str, Any]:
    packet = _packet(plant, schedule, critique)
    if not allow_model:
        reviewers = [_deterministic(role, plant, schedule, critique) for role in ROLES]
        return _aggregate(reviewers, packet)

    def _run(role: RoleName) -> dict[str, Any]:
        return _one(provider, role, plant, schedule, critique, packet)

    with ThreadPoolExecutor(max_workers=len(ROLES)) as pool:
        reviewers = list(pool.map(_run, ROLES))
    return _aggregate(reviewers, packet)


def _one(
    provider: Completer,
    role: RoleName,
    plant: Plant,
    schedule: Schedule,
    critique: Critique,
    packet: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = provider.complete(_messages(role, packet), lane=_LANE[role], temperature=0.0)
    except Exception as exc:
        fallback = _deterministic(role, plant, schedule, critique)
        fallback["fallback_reason"] = str(exc)
        return fallback
    try:
        reply = parse_model(result.content, ReviewReply)
    except (SchemaError, ValueError, TypeError) as exc:
        fallback = _deterministic(role, plant, schedule, critique)
        fallback["meterless_request_id"] = result.meterless_request_id
        fallback["fallback_reason"] = str(exc)
        return fallback
    if not isinstance(reply, ReviewReply):
        fallback = _deterministic(role, plant, schedule, critique)
        fallback["meterless_request_id"] = result.meterless_request_id
        fallback["fallback_reason"] = "Review payload did not match the schema."
        return fallback
    misses = _misses(reply, packet)
    if misses:
        fallback = _deterministic(role, plant, schedule, critique)
        fallback["meterless_request_id"] = result.meterless_request_id
        fallback["hallucinated_ids"] = misses
        fallback["fallback_reason"] = "Review cited an id or number outside the plant packet."
        return fallback
    return {
        "role": role,
        "title": _TITLES[role],
        "verdict": reply.verdict,
        "concerns": [item.model_dump() for item in reply.concerns],
        "suggestions": list(reply.suggestions),
        "source": "nemotron",
        "meterless_request_id": result.meterless_request_id,
        "hallucinated_ids": [],
        "fallback_reason": "",
    }


def _deterministic(
    role: RoleName,
    plant: Plant,
    schedule: Schedule,
    critique: Critique,
) -> dict[str, Any]:
    down = [item.equipment_id for item in plant.equipment if item.status in {"DOWN", "MAINTENANCE"}]
    held = [item.job_id for item in schedule.unscheduled]
    concerns: list[dict[str, Any]] = []
    if down:
        concerns.append({"detail": f"{down[0]} is down or in maintenance.", "ids": [down[0]]})
    if held:
        concerns.append({"detail": f"{held[0]} is held.", "ids": [held[0]]})
    if critique.verdict == "reject":
        verdict: VerdictName = "reject"
    elif critique.verdict == "conditional" or held:
        verdict = "approve-with-changes"
    else:
        verdict = "approve"
    suggestions: list[str] = []
    if verdict != "approve" and held:
        suggestions.append(f"Review the hold on {held[0]} before publishing the book.")
    return {
        "role": role,
        "title": _TITLES[role],
        "verdict": verdict,
        "concerns": concerns,
        "suggestions": suggestions,
        "source": "deterministic-fallback",
        "meterless_request_id": "",
        "hallucinated_ids": [],
        "fallback_reason": "",
    }


def _aggregate(reviewers: list[dict[str, Any]], packet: dict[str, Any]) -> dict[str, Any]:
    votes = [str(item["verdict"]) for item in reviewers]
    counts: dict[str, int] = {}
    for vote in votes:
        counts[vote] = counts.get(vote, 0) + 1
    if len(counts) == 1:
        agreement = "unanimous"
        recommendation = votes[0]
    else:
        top = max(counts, key=lambda name: counts[name])
        if counts[top] > len(votes) / 2:
            agreement = "majority"
            recommendation = top
        else:
            agreement = "split"
            recommendation = next(
                name for name in ("reject", "approve-with-changes", "approve") if name in counts
            )
    sources = {str(item["source"]) for item in reviewers}
    if sources == {"nemotron"}:
        source = "nemotron"
    elif "nemotron" in sources:
        source = "mixed"
    else:
        source = "deterministic-fallback"
    return {
        "reviewers": reviewers,
        "agreement": agreement,
        "recommendation": recommendation,
        "source": source,
        "request_ids": [
            str(item.get("meterless_request_id") or "")
            for item in reviewers
            if item.get("meterless_request_id")
        ],
        "note": (
            "Qualitative review only. Suggestions do not change the committed book "
            "and reviewers do not recompute KPIs."
        ),
        "packet_ids": packet["ids"],
    }


def _packet(plant: Plant, schedule: Schedule, critique: Critique) -> dict[str, Any]:
    ids = {job.job_id for job in plant.jobs}
    ids.update(item.equipment_id for item in plant.equipment)
    ids.update(step.step for product in plant.products for step in product.route)
    held = [item.job_id for item in schedule.unscheduled]
    down = [item.equipment_id for item in plant.equipment if item.status in {"DOWN", "MAINTENANCE"}]
    return {
        "critic_verdict": critique.verdict,
        "down_tools": down,
        "held_lots": held,
        "ids": sorted(ids),
    }


def _messages(role: RoleName, packet: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"You are the {_TITLES[role]}. Give a qualitative verdict only: "
                "approve, approve-with-changes, or reject. Do not recompute KPIs, "
                "do not author a schedule, and do not invent lot, tool, or step ids. "
                'Return JSON {"verdict":"...","concerns":[{"detail":"...","ids":[]}],'
                '"suggestions":["..."]}.'
            ),
        },
        {"role": "user", "content": json.dumps({"role": role, "packet": packet})},
    ]


def _misses(reply: ReviewReply, packet: dict[str, Any]) -> list[str]:
    known = {item.upper() for item in packet["ids"]}
    blob = json.dumps(packet)
    facts = {"ids": known, "numbers": _numbers(blob)}
    text = " ".join(
        [
            reply.verdict,
            " ".join(item.detail for item in reply.concerns),
            " ".join(token for item in reply.concerns for token in item.ids),
            " ".join(reply.suggestions),
        ]
    )
    flagged = narrative_mismatches(text, facts)
    for concern in reply.concerns:
        for token in concern.ids:
            if token.upper() not in known and f"unknown id {token}" not in flagged:
                flagged.append(f"unknown id {token}")
    return flagged


def _numbers(blob: str) -> set[str]:
    found = set()
    for raw in re.findall(r"\d+(?:\.\d+)?", blob):
        if "." in raw:
            found.add(raw.rstrip("0").rstrip("."))
        else:
            found.add(raw)
    return found
