# Multi-building transport layout

Branch `fab-layout`. Module `resilimes/smt/layout.py`, transport tier in
`resilimes/smt/fab.py::transport_seconds`, switch and KPIs in
`resilimes/smt/simulate.py`, study `resilimes/smt/layout_study.py`, tests
`tests/test_fab_layout.py`.

**This is a fab rule, not SMT2020 data.** SMT2020 names no buildings or bays:
`fromto.txt` has a single Fab-to-Fab row and every `STNFAMLOC` is `Fab`. The
two-building layout below is an **EXAMPLE** chosen by the user to make
cross-building moves measurable. It is not a claim about how the SMT2020 fab
is laid out.

## Model

Main moves a lot between steps in a fixed time: 1 min inside the same STNGRP
station group (the "bay"), 3 min otherwise. With a layout on, every station
family sits in one building and the move has three fixed tiers:

| move | time |
|---|---:|
| same bay (same STNGRP group, same building) | 1 min |
| same building, other bay | 3 min |
| cross-building | 15 min (`cross_building_sec`) |

Fixed times, no inter-building conveyor capacity or queue, no vehicles (as
main). Q-time windows keep running during the move. Everything that uses the
move uses the tiered time: arrival at the next family queue (`send`), the
Q-time "need" sums of the urgent override and the deadline logic, the tool
reservation ETA, and the trace checker's `transport` invariant.

## Switch (default OFF)

| switch | meaning |
|---|---|
| `run_policy(..., layout=False)` | one building, main's two tiers |
| `run_policy(..., layout=True)` | the example two-building layout |
| `run_policy(..., layout=FabLayout(...))` | any other layout |
| `RESILIMES_FAB_LAYOUT=example` (or `two_building`) | used when `layout` is not passed; empty / `off` is off |

Off is byte-identical to main: `tests/test_fab_layout.py` checks that the 3 h
published seed-1 run, default, `layout=False` and `RESILIMES_FAB_LAYOUT=off`,
hashes to the same golden digest as main (`c75ff85`, unchanged on `a8f68fa`)
for ResiliMES and EDD (every `RunResult` field and the full event stream,
apart from timing and the new `layout` KPI dict).

## The example layout (2 buildings)

Each family's key is `"<STNGRP>/<FE|BE>"` from the front-end / back-end token
in its SMT2020 name (`Litho_FE_92` -> `Litho/FE`, `DE_BE_11` -> `Dry_Etch/BE`),
or the bare STNGRP group when the name has no token.

* **Building A (front end):** every `*_FE_*` family of every group
  (`Litho_FE`, `LithoTrack_FE`, `DE_FE`, `WE_FE`, `Diffusion_FE`, `TF_FE`,
  `TF_Met_FE`, `Dielectric_FE`, `Planar_FE`, `DefMet_FE`, `Litho_REG_FE`,
  `LithoMet_FE`), plus the untagged `Implant` group (Implant_*, EPI_*) and
  `Delay_32`. 70 families, 1,024 tools.
* **Building B (back end):** every `*_BE_*` family (`Litho_BE`,
  `LithoTrack_BE`, `DE_BE`, `WE_BE`, `Diffusion_BE`, `TF_BE`,
  `Dielectric_BE`, `Planar_BE`, `DefMet_BE`, `Litho_REG_BE`, `LithoMet_BE`).
  36 families, 289 tools.

Why: over the 10 routes, FE steps sit at a mean 34 % of the route and BE steps
at a mean 82 % (no BE step before 54 %). The untagged implant/EPI families sit
at a mean 32 % (all before 70 %) and Delay_32 at 44 %, so they go with the
front end. A STNGRP group can therefore be in both buildings (Litho FE in A,
Litho BE in B); a bay is a group inside one building.

The split is not a clean "first half / second half" of the flow: FE and BE
steps interleave between ~50 % and ~75 % of the route and some FE metrology
sits late, so a route crosses buildings 13-35 times (route 1: 29 of 520
moves). That is what the token split gives; no family was moved to reduce it.

## KPIs (`RunResult.layout`)

* `transport_moves`, `transport_min`: every simulated move between steps and
  its total minutes (main's tiers when off).
* `cross_building_moves`: moves between buildings (0 when off).
* `second_transport_min`: second transports (`docs/SCHED_FREEZE.md`) weighted
  by the move from the staged tool to the new tool. Needs freeze tracking or
  the freeze on (`FreezeConfig(track=True)`), else 0. Also in
  `sched_freeze["second_transport_min"]`.

Second transports are counted from the plan, not simulated as moves (main
moves a lot to the family queue, not to a tool port), so `transport_min` does
not include them. In the example layout no family spans two buildings, so the
staged and the new tool are always in one bay and every second transport
weighs 1 min: `second_transport_min` = second transports x 1 min. A layout
that splits one family across buildings would weigh some of them 15 min; that
needs a tool-level mapping and is not built.

## 7-day study

`RESILIMES_STUDY_WORKERS=2 python -m resilimes.smt.layout_study out/layout_168h.json`,
then `--report out/layout_168h.json`. Published book, published seeds 1-3,
168 h, ResiliMES and EDD, Q-time r2 fixes 1-3 (as `freeze_study`). Arms:

* `L0F0`: one building (main transport), freeze off
* `L1F0`: example two-building layout, freeze off
* `L1F1`: example layout, frozen zone on at its defaults (2 loads / 30 min)

Freeze tracking is on in every arm (dispatch unchanged with the freeze off), so
the freeze-off second transports are the shadow count, as in
`docs/SCHED_FREEZE.md`. Nothing was tuned: weights, due dates, seeds, freeze
limits and the 15 min are as given. 18 runs, code `3dfcaa0`, run 2026-10-24
23:02-23:06 JST. Seeds are summed (945 due lots per policy and arm).

| KPI | resilimes L0F0 | resilimes L1F0 | resilimes L1F1 | edd L0F0 | edd L1F0 | edd L1F1 |
|---|---:|---:|---:|---:|---:|---:|
| on-time % | 91.85 | 91.75 | 90.69 | 91.96 | 91.85 | 90.9 |
| on-time lots | 868/945 | 867/945 | 857/945 | 869/945 | 868/945 | 859/945 |
| completed | 1088 | 1087 | 1092 | 1560 | 1550 | 1534 |
| true Q-time % | 97.19 | 96.53 | 95.27 | 89.23 | 88.91 | 86.9 |
| weighted tardiness (min) | 61697.6 | 64503.5 | 84821.0 | 63139.0 | 65712.5 | 89987.5 |
| transport (min) | 986963.0 | 1347588.0 | 1374815.0 | 786672.0 | 1129266.0 | 1132910.0 |
| transport moves | 390013 | 392512 | 402177 | 313180 | 313954 | 315188 |
| cross-building moves | 0 | 28016 | 28117 | 0 | 26837 | 26881 |
| second transports | 391050 | 394462 | 645 | 238514 | 236887 | 390 |
| second-transport (min) | 391050.0 | 394462.0 | 645.0 | 238514.0 | 236887.0 | 390.0 |

Per seed, on-time lots / due (completed):

| policy | arm | seed 1 | seed 2 | seed 3 |
|---|---|---:|---:|---:|
| resilimes | L0F0 | 289/315 (363) | 289/315 (369) | 290/315 (356) |
| resilimes | L1F0 | 290/315 (367) | 288/315 (370) | 289/315 (350) |
| resilimes | L1F1 | 286/315 (368) | 285/315 (372) | 286/315 (352) |
| edd | L0F0 | 290/315 (529) | 289/315 (519) | 290/315 (512) |
| edd | L1F0 | 289/315 (526) | 290/315 (517) | 289/315 (507) |
| edd | L1F1 | 286/315 (522) | 286/315 (508) | 287/315 (504) |

## Verdict

* **Two buildings vs one (L1F0 vs L0F0).** Transport minutes rise 37 %
  (ResiliMES) and 44 % (EDD); about 7.1 % (ResiliMES) and 8.5 % (EDD) of moves
  cross buildings. Delivery barely moves: on-time is 1 lot lower out of 945
  for both policies, which is inside seed noise (per seed it goes +1, -1, -1
  for ResiliMES and -1, +1, -1 for EDD). True Q-time falls 0.66 pp (ResiliMES)
  and 0.32 pp (EDD), weighted tardiness rises 4.5 % and 4.1 %. With fixed
  15 min moves and no conveyor queue, the example layout costs Q-time and
  tardiness a little, not on-time. ResiliMES keeps its Q-time lead over EDD
  (96.5 % vs 88.9 %); EDD stays 1 lot ahead on on-time.
* **Freeze with two buildings (L1F1 vs L1F0).** The freeze removes almost all
  second transports: 394,462 -> 645 min (ResiliMES) and 236,887 -> 390 min
  (EDD) over 3 seeds, i.e. about 131 k and 79 k minutes of re-moves per
  simulated week (shadow, from the plan). In exchange on-time falls 10 lots
  (ResiliMES) and 9 lots (EDD) of 945, true Q-time 1.3 pp and 2.0 pp, and
  weighted tardiness rises 31 % and 37 %. That is the same direction and size
  as the one-building study in `docs/SCHED_FREEZE.md`: the layout does not
  change the freeze trade-off, because in this layout a second transport stays
  inside one bay (1 min each).
* **Limits.** 3 seeds, one book, one example layout, fixed times without
  capacity. A conveyor or vehicle limit between buildings, or a family split
  across buildings, could change the result; neither is modelled.
