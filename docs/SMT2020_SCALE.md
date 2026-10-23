# SMT2020 full-fab measurements

Source: Kopp, Hassoun, Kalir, and Mönch, IEEE Trans. Semicond. Manuf. 33(4), 2020, doi 10.1109/TSM.2020.3001933. PySCFabSim-release commit `0dbff6a`, directory `datasets/SMT2020_LVHM`.

Fab: 106 station families, 1313 tools, 102 `Litho_*` tools (82 expose scanners plus 20 `Litho_REG`), 10 products, 2156 initial WIP lots, 12 station groups. `Delay_32` is included (400 tools, 147 route steps).

Horizon: 48 hours from 2018-01-01 00:00 UTC. Seeds: 1, 2, 3, 4, 5. Each seed draws exponential MTTF/MTTR from `downcal.txt`, one clock per tool. The same draw is shared across policies.

Macro APS (backward due, then earliest free expose scanner, 30625 scanner steps): **312.8 ms**.

Dispatch latency is the time to choose the next lot for one idle tool, look-ahead 24 (8 when that family's queue exceeds two lots per tool). It is not the full simulation time. Simulation time is the whole 48-hour run.

On-time percent uses lots whose due is at or before the horizon. A lot is on time only if its route finishes at or before the due. Lots already due at the snapshot stay in the denominator. Weighted tardiness is lot value times minutes late. An open lot is censored at the horizon. Cycle time is the mean completion time of lots that finish the route. Litho utilization is busy time on the 102 `Litho_*` tools divided by tools times horizon. Scanner utilization uses the 82 expose tools. Q-time violations are published CQT misses. PM avoided is a ResiliMES decision that refused at least one lot because the process would cross a PM. PM overlaps are baseline starts that run across a PM.

The weekly PM FOA on the focus family is outside a 48-hour window (about 7 days). The steady and litho studies therefore show zero PM events. The PM study subtracts one offset from every day-based calendar so `Litho_FE_92_WK` opens at 2 hours. Duration and interval stay published. One FOA is stored per family, so every tool in the family shares that window.

Lithography breakdown holds `Litho_FE_92-1` (`Litho_FE_92`, largest expose family) for the published lithography MTTR of 705.59 minutes, on top of the seeded breakdowns.

Hot lot `Init_Lot_10_11` is the lowest lot id among normal-priority lots sitting four steps before an expose scanner. The ResiliMES book raises it to VIP with a due 12 hours from the snapshot. FIFO keeps the published priority.

## Steady fab (seeded breakdowns, published PM calendar unshifted)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 22263.6 | 27.084 | 76.248 | 71.942 | 369.4 | 0.0 | 0.0 | 194.8 | 0.004 | 0.138 | 1.379 |
| edd | 57.14 | 21611.14 | 25.898 | 74.09 | 69.546 | 418.2 | 0.0 | 0.0 | 0.0 | 0.001 | 0.033 | 0.427 |
| fifo | 25.358 | 53890.0 | 27.126 | 73.33 | 67.864 | 647.4 | 0.0 | 0.0 | 0.0 | 0.001 | 0.013 | 0.321 |
| cr | 27.858 | 23365.74 | 29.636 | 68.882 | 63.7 | 305.2 | 0.0 | 0.0 | 0.0 | 0.002 | 0.04 | 0.483 |

## Lithography breakdown

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 21743.8 | 26.376 | 75.938 | 71.584 | 373.0 | 0.0 | 0.0 | 183.6 | 0.004 | 0.138 | 1.378 |
| edd | 57.14 | 21590.56 | 26.222 | 73.858 | 69.414 | 406.2 | 0.0 | 0.0 | 0.0 | 0.001 | 0.033 | 0.423 |

While `Litho_FE_92-1` is down, other tools in `Litho_FE_92` start 225.2 lots under ResiliMES and 218.0 under EDD (five-seed mean). The family queue peaks at 40.0 lots. The downstream queue peaks at 442.6 under ResiliMES and 398.8 under EDD. On-time uses 56.0 lots due inside the horizon, of which 10.0 are already late at the snapshot.

## PM avoidance (calendar shifted, durations unchanged)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 55.36 | 22730.5 | 27.296 | 74.574 | 70.392 | 326.8 | 40.6 | 0.0 | 184.6 | 0.004 | 0.144 | 1.364 |
| edd | 57.14 | 21611.14 | 25.898 | 74.09 | 69.546 | 418.2 | 0.0 | 450.4 | 0.0 | 0.001 | 0.033 | 0.427 |

## Hot lot

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.14 | 27842.48 | 26.734 | 76.114 | 71.734 | 382.6 | 0.0 | 0.0 | 190.6 | 0.004 | 0.139 | 1.406 |
| fifo | 25.358 | 53890.0 | 27.126 | 73.33 | 67.864 | 647.4 | 0.0 | 0.0 | 0.0 | 0.001 | 0.013 | 0.318 |

`Init_Lot_10_11` completes 37.0 steps under ResiliMES and 22.8 under FIFO. Promoting it moves the on-time denominator to 57.0 lots (56.0 on the FIFO book).

Per-seed rows are in `data/smt2020/benchmark.json`. Regenerate with `make smt-bench`.
