# SMT2020 full-fab measurements

Public industry benchmark (SMT2020). Source: Kopp, Hassoun, Kalir, and Mönch, IEEE Trans. Semicond. Manuf. 33(4), 2020, doi 10.1109/TSM.2020.3001933. PySCFabSim-release commit `0dbff6a`, directory `datasets/SMT2020_LVHM`. This is not a recording from a production fab.

Fab: 106 station families, 1313 tools, 102 `Litho_*` tools (82 expose scanners plus 20 `Litho_REG`), 10 products, 2156 initial WIP lots, 12 station groups. `Delay_32` is included (400 tools, 147 route steps).

The tight VIP table is 24 hours. The appendix is 48 hours from 2018-01-01 00:00 UTC. Seeds: 1, 2, 3, 4, 5. Each seed draws exponential MTTF/MTTR from `downcal.txt`, one clock per tool. The same draw is shared across policies.

Macro APS (backward due, then earliest free expose scanner, 30625 scanner steps): **286.0 ms**.

Dispatch latency is the time to choose the next lot for one idle tool, look-ahead 24 (8 when that family's queue exceeds two lots per tool). It is not the full simulation time. Simulation time is the whole 48-hour run.

On-time percent uses lots whose due is at or before the horizon. A lot is on time only if its route finishes at or before the due. Lots already due at the snapshot stay in the denominator. Weighted tardiness is lot value times minutes late. An open lot is censored at the horizon. Cycle time is the mean completion time of lots that finish the route. X-factor is that completion time divided by the lot's remaining raw process time at the snapshot. Litho utilization is busy time on the 102 `Litho_*` tools divided by tools times horizon. Scanner utilization uses the 82 expose tools. Q-time violations are published CQT misses. PM avoided is a ResiliMES decision that refused at least one lot because the process would cross a PM. PM overlaps are baseline starts that run across a PM.

The weekly PM FOA on the focus family is outside a 48-hour window (about 7 days). The steady and litho studies therefore show zero PM events. The PM study subtracts one offset from every day-based calendar so `Litho_FE_92_WK` opens at 2 hours. Duration and interval stay published. One FOA is stored per family, so every tool in the family shares that window.

Lithography breakdown holds `Litho_FE_92-1` (`Litho_FE_92`, largest expose family) for the published lithography MTTR of 705.59 minutes, on top of the seeded breakdowns.

Hot lot `Init_Lot_10_11` is the lowest lot id among normal-priority lots sitting four steps before an expose scanner. The ResiliMES book raises it to VIP with a due 12 hours from the snapshot. FIFO keeps the published priority.

## Tight VIP dues (constructed, 24 hours)

The published dues do not make earliest-due lose on on-time delivery. This book keeps the routes, process times, setups, and CQT limits, and replaces the dues used for scoring. Eight lots waiting at `Dielectric_BE_28` with a later CQT become VIP and are due at 8 hours. The other lots in that queue stay normal and are due at 7.2 hours, so earliest-due serves them first. Every other lot still moves through the fab and is outside the scored horizon. `Dielectric_BE_28-1` is down for the published dielectric MTTR of 604.8 minutes. The family has three tools. Horizon is 24 hours, five seeds.

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 19.05 | 4329.38 | 9.738 | 77.69 | 72.514 | 176 | 0 | 0 | 134.8 | 0.0002 | 0.006 | 1.467 |
| edd | 12.382 | 7985.74 | 11.654 | 82.008 | 77.862 | 413.8 | 0 | 0 | 0 | 0.0002 | 0.0028 | 0.754 |
| fifo | 0.0 | 19042.4 | 14.614 | 82.166 | 78.058 | 421.4 | 0 | 0 | 0 | 0.0002 | 0.0027 | 0.685 |
| cr | 9.52 | 10372.78 | 10.87 | 79.464 | 74.708 | 223.2 | 0 | 0 | 0 | 0.0002 | 0.0029 | 0.859 |

Seed 1, who paid: 13 non-hot lots in that queue finish 31.72 hours later under ResiliMES than under EDD (Init_Lot_8_20 +3.61 h, Init_Lot_8_9 +3.22 h, Init_Lot_8_3 +3.02 h, Init_Lot_5_5 +2.98 h, Init_Lot_5_14 +2.98 h). Init_Lot_2_23 is 5.43 h late under EDD and 0.0 h late under ResiliMES. On-time on this seed is 14.29% under EDD and 19.05% under ResiliMES. Queue-time violations are 415 and 187.

## X-factor dues (48 hours)

This book keeps the published routes, priorities, and CQT limits. Each due is the remaining raw process time times 2.75. Horizon is 48 hours. 87 lots are due inside it. `Litho_FE_92-1` is held down for a fixed repair on top of the seeded breakdowns. The baseline is EDD. FIFO and CR are on the 600-minute row only. At a 600-minute repair, EDD on-time is 99.54% and ResiliMES is 97.47%. Scanner station families have no row in `setup.txt` and no route `STIME`, so a scanner change does not add setup. A later litho layer stays on the scanner that ran the first layer of its `SVESTN` / `FORSTEP` chain, once this run has chosen that scanner. WIP does not name a tool, so a lot that starts mid-chain is not pinned until then. There is no reticle id, stocker, or transfer time in the extract, and none is invented. A lot in process at a breakdown keeps the remaining process, waits 15 minutes, and resumes on that tool. The 15 minutes are not an SMT2020 column. An adjacent Wet_Etch queue-time step is held back when the next tool cannot start inside the window. A miss sends the lot through that wet step once. That is not the published rework probability. Ten thousand exponential draws of the lithography MTTR (705.59 minutes) have mean 705.4 minutes, sample std 708.7, p50 486.4, p90 1651.4. The share at or under 180 / 300 / 600 minutes is 0.233 / 0.346 / 0.575. Litho utilization at 600 minutes is 78.076% under ResiliMES and 79.294% under EDD, over all 102 `Litho_*` tools. The busiest expose family on the EDD seed-1 run is `Litho_BE_110` at 85.5% (23 tools). Tools were not removed to push that number to 90%.

| ETA min | Policy | OTD % | OTD std | Q-time | Q std | X-factor | X std | Cycle h | Cycle std | Litho util % | Litho std | Re-cleans | Gates |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 180.0 | resilimes | 97.47 | 2.76 | 435.6 | 13.245 | 1.694 | 0.057 | 23.67 | 0.409 | 78.032 | 0.785 | 49.8 | 0 |
| 180.0 | edd | 99.54 | 0.563 | 457.6 | 19.704 | 1.694 | 0.043 | 23.402 | 0.619 | 79.12 | 0.482 | 53.2 | 0 |
| 300.0 | resilimes | 97.47 | 2.76 | 432.2 | 9.239 | 1.695 | 0.06 | 23.498 | 0.428 | 78.212 | 0.709 | 44.4 | 0 |
| 300.0 | edd | 99.54 | 0.563 | 460.2 | 35.21 | 1.699 | 0.041 | 23.854 | 0.574 | 79.214 | 0.48 | 57.2 | 0 |
| 600.0 | resilimes | 97.47 | 2.76 | 430 | 13.638 | 1.692 | 0.061 | 23.582 | 0.435 | 78.076 | 0.528 | 38 | 0 |
| 600.0 | edd | 99.54 | 0.563 | 451.6 | 21.951 | 1.7 | 0.038 | 23.874 | 0.418 | 79.294 | 0.192 | 55.6 | 0 |
| 600.0 | fifo | 20.688 | 5.19 | 765.2 | 48.425 | 3.406 | 0.265 | 24.91 | 1.025 | 76.344 | 0.294 | 99.6 | 0 |
| 600.0 | cr | 71.722 | 4.02 | 718.8 | 16.017 | 2.536 | 0.048 | 26.154 | 0.349 | 75.488 | 0.59 | 126.6 | 0 |
| 705.59 | resilimes | 97.47 | 2.76 | 429 | 13.206 | 1.695 | 0.061 | 23.596 | 0.4 | 78.128 | 0.565 | 46.6 | 0 |
| 705.59 | edd | 99.54 | 0.563 | 454.2 | 18.915 | 1.701 | 0.038 | 24.004 | 0.525 | 79.208 | 0.427 | 60.4 | 0 |

Seed 1, who paid: no scored non-hot lot finishes later under ResiliMES than under EDD. Mean X-factor on this seed is 1.665 under EDD and 1.64 under ResiliMES. Upstream gates 0. Re-cleans 31. Spread across seeds is the sample standard deviation, n=5.

## Appendix: published order book (performance)

On the published dues, a 48-hour horizon, EDD is slightly ahead of ResiliMES on on-time delivery (56.784% against 56.428%). EDD weighted tardiness is 21525.68 minutes against 21988.14. These tables are runtime and knock-on measurements. They are not the claim that earliest-due loses.

### Steady fab (seeded breakdowns, published PM calendar unshifted)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.428 | 21988.14 | 25.876 | 76.208 | 71.63 | 386 | 0 | 0 | 156.2 | 0.0002 | 0.0058 | 2.296 |
| edd | 56.784 | 21525.68 | 26.068 | 79.12 | 74.508 | 414.8 | 0 | 0 | 0 | 0.0002 | 0.0027 | 1.268 |
| fifo | 26.43 | 52672.8 | 27.018 | 76.22 | 70.632 | 749.6 | 0 | 0 | 0 | 0.0002 | 0.0025 | 1.29 |
| cr | 33.928 | 22923.68 | 29.412 | 73.538 | 67.606 | 315.4 | 0 | 0 | 0 | 0.0002 | 0.0027 | 1.384 |

### Lithography breakdown

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.428 | 21844.54 | 26.282 | 75.886 | 71.306 | 395.6 | 0 | 0 | 155.8 | 0.0002 | 0.0057 | 2.283 |
| edd | 56.784 | 21436.12 | 25.61 | 79.07 | 74.514 | 419.4 | 0 | 0 | 0 | 0.0002 | 0.0027 | 1.262 |

While `Litho_FE_92-1` is down, other tools in `Litho_FE_92` start 250.4 lots under ResiliMES and 250.8 under EDD (five-seed mean). The family queue peaks at 40 lots. The downstream queue peaks at 375.4 under ResiliMES and 486.2 under EDD. On-time uses 56 lots due inside the horizon, of which 10 are already late at the snapshot.

### PM avoidance (calendar shifted, durations unchanged)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 55.0 | 22795.84 | 26.85 | 74.39 | 69.902 | 367 | 54.2 | 0 | 154.6 | 0.0002 | 0.0057 | 2.286 |
| edd | 56.784 | 21525.68 | 26.068 | 79.12 | 74.508 | 414.8 | 0 | 495.6 | 0 | 0.0002 | 0.0027 | 1.267 |

### Hot lot

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 55.09 | 27588.48 | 26.628 | 76.602 | 71.934 | 389.2 | 0 | 0 | 151.2 | 0.0002 | 0.0058 | 2.331 |
| fifo | 26.43 | 52672.8 | 27.018 | 76.22 | 70.632 | 749.6 | 0 | 0 | 0 | 0.0002 | 0.0024 | 1.282 |

`Init_Lot_10_11` completes 37 steps under ResiliMES and 23 under FIFO. Promoting it moves the on-time denominator to 57 lots (56 on the FIFO book).

Per-seed rows are in `data/smt2020/benchmark.json`. Regenerate with `make smt-bench`.
What the extract contains, and what this simulator leaves out, is [SMT2020_PROVENANCE.md](SMT2020_PROVENANCE.md).
