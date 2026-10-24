"""Stage 1. A release plan and two coarse checks. Not an ERP.

SMT2020 ``order.txt`` supplies the product, the release interval, the priority,
and the contract due date. ``RPT#`` is the AutoSched repeat count for a long
run, not the number of lots in the horizon. Customers and margin tiers are
derived and labeled; SMT2020 has no price and no customer master.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemandOrder:
    order_id: str
    product_id: str
    qty_wafers: int
    interval_min: float
    order_class: str
    customer: str
    margin_tier: str


def release_count(interval_min: float, horizon_min: float) -> int:
    """How many releases fall in ``[0, horizon)``, including the one at 0."""
    if interval_min <= 0 or horizon_min <= 0:
        return 0
    count = 0
    tick = 0.0
    while tick < horizon_min - 1e-9:
        count += 1
        tick += interval_min
    return count


def master_schedule(
    orders: list[DemandOrder],
    *,
    horizon_min: float,
    shift_min: float = 12 * 60,
) -> list[dict[str, object]]:
    """Lots to release per product per shift. One lot per SMT release."""
    shifts = max(1, int(horizon_min // shift_min))
    rows: list[dict[str, object]] = []
    for order in orders:
        total = release_count(order.interval_min, horizon_min)
        released = 0
        for index in range(shifts):
            start = index * shift_min
            end = min(horizon_min, start + shift_min)
            in_shift = 0
            tick = 0.0
            while tick < horizon_min - 1e-9:
                if start <= tick < end:
                    in_shift += 1
                tick += order.interval_min
            released += in_shift
            rows.append(
                {
                    "order_id": order.order_id,
                    "product_id": order.product_id,
                    "order_class": order.order_class,
                    "customer": order.customer,
                    "margin_tier": order.margin_tier,
                    "shift_index": index,
                    "lots": in_shift,
                    "wafers": in_shift * order.qty_wafers,
                    "provenance": "smt2020 release interval; customer and margin are derived",
                }
            )
        if released != total:
            raise RuntimeError(f"MPS dropped a release of {order.order_id}")
    return rows


def litho_capacity_gap(
    *,
    demand_min: float,
    scanner_tools: int,
    horizon_min: float,
) -> dict[str, float]:
    """Coarse gap: litho minutes required minus scanner-minutes available."""
    capacity = float(scanner_tools) * horizon_min
    return {
        "demand_min": demand_min,
        "capacity_min": capacity,
        "gap_min": demand_min - capacity,
    }


def material_check(
    releases: dict[str, int],
    bom: dict[str, list[tuple[str, float]]],
    on_hand: dict[str, float],
) -> list[dict[str, object]]:
    """Rough MRP. A product with no BOM row is unchecked, not short."""
    rows: list[dict[str, object]] = []
    for product, lots in sorted(releases.items()):
        needs = bom.get(product)
        if not needs:
            rows.append(
                {
                    "product_id": product,
                    "material_id": "",
                    "status": "unchecked",
                    "detail": "no BOM row for this product",
                }
            )
            continue
        for material_id, qty in needs:
            required = qty * lots
            have = on_hand.get(material_id, 0.0)
            rows.append(
                {
                    "product_id": product,
                    "material_id": material_id,
                    "required": required,
                    "on_hand": have,
                    "status": "short" if have < required else "covered",
                }
            )
    return rows
