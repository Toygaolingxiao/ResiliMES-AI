"""Dynamic priority and the idle-tool score.

Stage 2 publishes a Dynamic Priority Index. Stage 3 uses that index as the only
value/urgency term. Critical ratio and the hot-lot bonus are not added again.

DPI and CR describe the same due date, so adding both would count it twice.
CR = (due - now) / remaining process time. Remaining slack = due - now -
remaining process time. CR < 1 exactly when slack is negative. DPI keeps the
slack form (capped once the lot is late) and folds hot, VIP, margin, and
engineering into LotValue. The dispatcher then adds only tool-local terms:
setup cost from the setup matrix, and PED/Q-time risk.

Written micro score, before sign orientation::

    S = w*DPI - w_setup*SetupCost - w_ped*PEDRisk

High PED risk must raise the score, so the implemented term is ``+ w_ped·PEDRisk``.
Lower slack raises DPI, which raises S. A lower CR is the same urgency seen
through the ratio; it is reported as ``cr_reference`` and is not a term.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# One minute. At or below this, 1/slack is the cap instead of growing without
# bound or turning negative.
SLACK_FLOOR_SEC = 60.0
# Urgency = SCALE / slack_sec, which is 1/slack measured in hours.
URGENCY_SCALE_SEC = 3600.0


@dataclass(frozen=True)
class DpiWeights:
    """Weights inside the index. They are not repeated in the dispatcher."""

    w1_value: float = 1.0
    w2_urgency: float = 1.0


@dataclass(frozen=True)
class DispatchWeights:
    """Idle-tool weights. Setup is per second, so a minute of setup costs ``60 * w_setup``."""

    w_dpi: float = 1.0
    w_setup: float = 1.0 / 60.0
    w_ped: float = 1.0
    ped_k: float = 6.0


@dataclass(frozen=True)
class Dpi:
    index: float
    lot_value: float
    slack_sec: float
    urgency: float
    late: bool
    cr_reference: float


def lot_value(order_class: str, margin_tier: str = "unpriced") -> float:
    """Relative value. Tiers are weights, not SMT2020 prices.

    ``unpriced`` adds nothing: SMT2020 has no margin. ``high`` is an explicit
    derived override. Engineering is a labeled class, unused by the SMT orders.
    """
    base = {"VIP": 3.0, "hot": 2.0, "engineering": 1.5, "normal": 1.0}.get(order_class, 1.0)
    if margin_tier == "high":
        return base + 1.0
    return base


def order_class_from_priority(priority: int) -> str:
    """SMT2020 PRIOR is higher-is-hotter. The HOTLOT column is ``no`` even then."""
    if priority >= 30:
        return "VIP"
    if priority >= 20:
        return "hot"
    if priority >= 10:
        return "normal"
    if priority <= 1:
        return "VIP"
    if priority <= 2:
        return "hot"
    return "normal"


def urgency_of(slack_sec: float) -> tuple[float, bool]:
    """``(urgency, late)``. Slack at or below the floor uses the cap.

    A negative slack would make ``1/slack`` negative and would prefer the late
    lot last. The cap keeps it at the top of the urgency scale, and ``late``
    records that the theoretical process time already misses the due date.
    """
    late = slack_sec <= 0.0
    if slack_sec <= SLACK_FLOOR_SEC:
        return URGENCY_SCALE_SEC / SLACK_FLOOR_SEC, late
    return URGENCY_SCALE_SEC / slack_sec, late


def dynamic_priority(
    *,
    due_sec: float,
    now_sec: float,
    remaining_sec: float,
    order_class: str,
    margin_tier: str = "unpriced",
    weights: DpiWeights | None = None,
) -> Dpi:
    """DPI = w1·LotValue + w2·(1 / RemainingSlack), with the slack guard."""
    weights = weights or DpiWeights()
    remaining = remaining_sec if remaining_sec > 1e-9 else 1e-9
    slack = due_sec - now_sec - remaining
    urgency, late = urgency_of(slack)
    value = lot_value(order_class, margin_tier)
    return Dpi(
        index=weights.w1_value * value + weights.w2_urgency * urgency,
        lot_value=value,
        slack_sec=slack,
        urgency=urgency,
        late=late,
        cr_reference=(due_sec - now_sec) / remaining,
    )


def ped_risk(remaining_sec: float | None, limit_sec: float | None, k: float) -> float:
    """Grows as remaining/limit falls. Zero at or outside the window."""
    if remaining_sec is None or limit_sec is None or limit_sec <= 0:
        return 0.0
    ratio = remaining_sec / limit_sec
    if ratio >= 1.0:
        return 0.0
    return math.exp(k * (1.0 - ratio)) - 1.0


def dispatch_score(
    *,
    dpi: float,
    setup_sec: float,
    ped: float,
    weights: DispatchWeights | None = None,
) -> float:
    """Higher is dispatched first. PED is added. CR and hot are not terms."""
    weights = weights or DispatchWeights()
    return weights.w_dpi * dpi - weights.w_setup * setup_sec + weights.w_ped * ped


CLASS_TIER = {"VIP": 0, "hot": 1}


def class_tier(order_class: str) -> int:
    """0 VIP, 1 hot, 2 everything else. From SMT2020 PRIOR via the class."""
    return CLASS_TIER.get(order_class, 2)


def tiered_key(
    *,
    order_class: str,
    slack_sec: float,
    setup_sec: float,
    ped: float,
) -> tuple[float, ...]:
    """Lexicographic dispatch order. Smaller is dispatched first.

    1. class tier (VIP, hot, normal). Nothing in a lower tier can outrank it.
    2. late band: a lot whose remaining theoretical process already misses its
       due date goes before an on-time lot of the same tier.
    3. queue-time risk (PED), then setup avoidance (seconds of setup).
    4. remaining slack, ascending. That is the DPI urgency order inside a
       tier, without the 60 s slack floor that made every late lot tie at the
       cap (a late normal lot scored 61 and outranked an on-time VIP).
    No weights: the terms never trade against each other.
    """
    late = 0.0 if slack_sec <= 0.0 else 1.0
    return (float(class_tier(order_class)), late, -ped, setup_sec, slack_sec)


def score_terms(
    *,
    dpi: float,
    setup_sec: float,
    ped: float,
    cr_reference: float,
    weights: DispatchWeights | None = None,
) -> dict[str, float]:
    """Term breakdown. ``cr_reference`` is explanatory and has coefficient 0."""
    weights = weights or DispatchWeights()
    return {
        "dpi": dpi,
        "w_dpi_dpi": weights.w_dpi * dpi,
        "setup_sec": setup_sec,
        "w_setup_setup": -weights.w_setup * setup_sec,
        "ped_risk": ped,
        "w_ped_ped": weights.w_ped * ped,
        "cr_reference": cr_reference,
        "score": dispatch_score(dpi=dpi, setup_sec=setup_sec, ped=ped, weights=weights),
    }
