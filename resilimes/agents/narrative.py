"""Supervisor-facing narrative built only from schedule facts."""

from __future__ import annotations

from resilimes.domain.models import Critique, JobOutcome, KpiReport


def narrate(
    *,
    incident: str,
    before: KpiReport,
    after: KpiReport,
    outcomes: list[JobOutcome],
    committed: Critique,
    rejected: Critique,
) -> str:
    moved = [
        row
        for row in outcomes
        if row.before_equipment
        and row.after_equipment
        and row.before_equipment != row.after_equipment
    ]
    held = [
        row for row in outcomes if row.after_completion_min is None and row.after_tardiness_min > 0
    ]
    new_lots = [
        row
        for row in outcomes
        if row.before_equipment is None
        and row.before_completion_min is None
        and row.after_equipment
    ]
    parts = [incident.strip()]
    if new_lots:
        lead = new_lots[0]
        parts.append(
            f"{lead.job_id} enters the book on {lead.after_equipment} and finishes at "
            f"t={lead.after_completion_min} min, tardiness {lead.after_tardiness_min} min. "
            "Lots already running stay on their tools."
        )
    elif moved:
        lead = moved[0]
        parts.append(
            f"{lead.job_id} moves from {lead.before_equipment} to {lead.after_equipment}. "
            f"Remaining completion goes from t={lead.before_completion_min} min "
            f"to t={lead.after_completion_min} min "
            f"(tardiness {lead.before_tardiness_min} → {lead.after_tardiness_min})."
        )
    if held:
        names = ", ".join(row.job_id for row in held)
        parts.append(f"Held for a hard constraint: {names}.")
    parts.append(
        f"On-time delivery {before.on_time_delivery_pct:.1f}% → {after.on_time_delivery_pct:.1f}%. "
        f"Priority-weighted tardiness {before.weighted_tardiness_min:.0f} → "
        f"{after.weighted_tardiness_min:.0f} min. "
        f"Makespan {before.makespan_min} → {after.makespan_min} min. "
        f"Priority-1/2 lots at risk {before.lots_at_risk} → {after.lots_at_risk}."
    )
    parts.append(f"Critic on the committed schedule: {committed.verdict}. {committed.rationale}")
    if rejected.violations:
        first = rejected.violations[0]
        parts.append(f"A naive alternative was rejected ({first.constraint}): {first.detail}")
    return " ".join(parts)
