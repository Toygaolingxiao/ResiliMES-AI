"""Multi-building fab layout (fab rule, not SMT2020 data). Default OFF.

SMT2020 names no buildings or bays: ``fromto.txt`` has one Fab-to-Fab row and
every STNFAMLOC is ``Fab``. With the layout off, transport is main's fixed move
(``fab.transport_seconds``): same STNGRP bay 1 min, other bay 3 min.

With a layout on, every station family sits in one building and the move has
three tiers (fixed times, no inter-building conveyor capacity or queue):

* same bay (same STNGRP group, same building): 1 min
* same building, other bay: 3 min
* cross-building: ``cross_building_sec`` (15 min in the example)

The mapping key of a family is ``"<STNGRP>/<FE|BE>"`` when the family name
carries a front-end or back-end token (``Litho_FE_92`` -> ``Litho/FE``,
``DE_BE_11`` -> ``Dry_Etch/BE``), else the bare STNGRP group (``Implant``,
``Delay_32``). Every family of the fab must resolve to a building.

Switch: ``run_policy(..., layout=...)`` (``False`` off, ``True`` the example,
or a ``FabLayout``); unset reads ``RESILIMES_FAB_LAYOUT`` (``example`` or
``two_building``; empty / ``off`` is off).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resilimes.smt.fab import Fab

CROSS_BUILDING_SEC = 15 * 60.0

_SECTION = re.compile(r"(?:^|_)(FE|BE)(?:_|$)", re.IGNORECASE)


@dataclass(frozen=True)
class FabLayout:
    """Building of every ``"<STNGRP>/<FE|BE>"`` (or bare STNGRP) key."""

    name: str
    building: dict[str, str] = field(default_factory=dict)
    cross_building_sec: float = CROSS_BUILDING_SEC


# EXAMPLE layout chosen by the user, a fab rule and not SMT2020 data. Two
# buildings, front end in A and back end in B. The split follows the FE/BE
# token SMT2020 puts in the family names: FE steps sit at a mean 34% of the
# route, BE steps at a mean 82% (none before 54%). Families without a token
# are the implant/EPI tools (Implant, mean 32% of the route, all before 70%) and
# the Delay_32 station (mean 44%): both go to the front-end building A.
EXAMPLE_TWO_BUILDINGS = FabLayout(
    name="example_two_buildings",
    building={
        "Def_Met/BE": "B",
        "Def_Met/FE": "A",
        "Delay_32": "A",
        "Dielectric/BE": "B",
        "Dielectric/FE": "A",
        "Diffusion/BE": "B",
        "Diffusion/FE": "A",
        "Dry_Etch/BE": "B",
        "Dry_Etch/FE": "A",
        "Implant": "A",
        "Litho/BE": "B",
        "Litho/FE": "A",
        "Litho_Met/BE": "B",
        "Litho_Met/FE": "A",
        "Planar/BE": "B",
        "Planar/FE": "A",
        "TF/BE": "B",
        "TF/FE": "A",
        "TF_Met/FE": "A",
        "Wet_Etch/BE": "B",
        "Wet_Etch/FE": "A",
    },
)
LAYOUTS = {"example": EXAMPLE_TWO_BUILDINGS, EXAMPLE_TWO_BUILDINGS.name: EXAMPLE_TWO_BUILDINGS}
LAYOUTS["two_building"] = EXAMPLE_TWO_BUILDINGS


def family_key(group: str, name: str) -> str:
    """``"<STNGRP>/<FE|BE>"`` from the family name's token, else the group."""
    hit = _SECTION.search(name)
    return f"{group}/{hit.group(1).upper()}" if hit else group


def family_buildings(fab: Fab, layout: FabLayout) -> list[str]:
    """Building of every station family; KeyError names an unmapped family."""
    out: list[str] = []
    for fam in fab.families:
        key = family_key(fam.group, fam.name)
        if key not in layout.building:
            raise KeyError(f"layout {layout.name}: no building for {fam.name} ({key})")
        out.append(layout.building[key])
    return out


def resolve(layout: FabLayout | bool | str | None) -> FabLayout | None:
    """``None`` reads RESILIMES_FAB_LAYOUT; False/'off' is off; True the example."""
    if layout is None:
        layout = os.environ.get("RESILIMES_FAB_LAYOUT", "").strip()
    if isinstance(layout, FabLayout):
        return layout
    if layout is True:
        return EXAMPLE_TWO_BUILDINGS
    if layout is False or layout == "" or str(layout).lower() in ("0", "off", "none", "false"):
        return None
    try:
        return LAYOUTS[str(layout)]
    except KeyError:
        raise ValueError(f"Unknown fab layout {layout!r}; known: {sorted(LAYOUTS)}") from None
