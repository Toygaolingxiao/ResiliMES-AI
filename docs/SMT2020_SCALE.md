# SMT2020 full-fab measurements

Public industry benchmark (SMT2020). Source: Kopp, Hassoun, Kalir, and Mönch, IEEE Trans. Semicond. Manuf. 33(4), 2020, doi 10.1109/TSM.2020.3001933. PySCFabSim-release commit `0dbff6a`, directory `datasets/SMT2020_LVHM`. This is not a recording from a production fab.

Fab: 106 station families, 1313 tools, 102 `Litho_*` tools (82 expose scanners plus 20 `Litho_REG`), 10 products, 2156 initial WIP lots, 12 station groups. `Delay_32` is included (400 tools, 147 route steps).

## The trade

X-factor dues, 48 hours, 87 lots. On-time for ResiliMES and EDD is the same at a 180, 300, 600, 705.59 minute repair. ResiliMES 86/87, 83/87, 86/87, 87/87, 87/87 (429/435 pooled), mean 98.62%. EDD 87/87, 86/87, 86/87, 87/87, 87/87 (433/435 pooled), mean 99.54%. FIFO mean 31.032%. CR mean 71.724%. ResiliMES beats FIFO and CR by a wide margin. Versus EDD it gives up 4 of 435 pooled lots, with re-cleans 52.4 against 73.4 and Q-time violations 416.2 against 441.8 (five-seed means).

Published dues, 48 hours, 56 lots. ResiliMES 32/56, 32/56, 32/56, 32/56, 32/56 (160/280 pooled), mean 57.14%. EDD 32/56, 32/56, 32/56, 32/56, 32/56 (160/280 pooled), mean 57.14%. ResiliMES and EDD tie on pooled on-time lots.

Tight VIP dues rewrites the dues for the stress test. It is not the published order book. Denominator 21 lots. ResiliMES 4/21, 4/21, 4/21, 4/21, 4/21 (20/105 pooled). EDD 3/21, 3/21, 2/21, 2/21, 3/21 (13/105 pooled). FIFO 0/21, 0/21, 0/21, 0/21, 0/21 (0/105 pooled). CR 2/21, 2/21, 2/21, 2/21, 2/21 (10/105 pooled). Seed 1 weighted tardiness is 7696.8 under EDD and 3988.6 under ResiliMES. The 12-hour lithography click is one seed. It is not the 48-hour lithography study in the appendix.

Every number in this file comes from the simulator after the stale-queue fix. Before it, a lot that had already started could stay in its old family queue and start its next step on a tool of the wrong family. The trace checker and the pre-fix numbers are in [invariants.md](invariants.md).

The tight VIP table is 24 hours. The appendix is 48 hours from 2018-01-01 00:00 UTC. Seeds: 1, 2, 3, 4, 5. Each seed draws exponential MTTF/MTTR from `downcal.txt`, one clock per tool. The same draw is shared across policies.

Macro APS places 30625 scanner steps. That step count is the stable spec. The timer is about 0.3 s on the CI VM (this run recorded 284.6 ms).

Dispatch latency is the time to choose the next lot for one idle tool, look-ahead 24 (8 when that family's queue exceeds two lots per tool). The headline p50/p95 includes empty wakes. Nonempty-queue decisions on the X-factor ResiliMES runs, seeds 1-5, were p50 0.0099-0.0103 ms and p95 0.2425-0.2519 ms on this run. It is not the full simulation time. Simulation time is the whole 48-hour run.

The WIP column is a candidate cap, not a replan. `choose()` keeps 8 lots instead of 24 after a family exceeds max(8, two lots per tool), and also keeps a lot whose slack is at or under 7200 seconds. The adjacent Wet_Etch look-ahead fired 0 times on these books. `macro_aps_ms` does not feed `dpi()`. `rank()` calls `dispatch_score`. A down tool queues the end of every covering window, so a forced outage that overlaps an MTTF draw still releases at the later end. Seeds 1-5 on-time on the books below match the figures in this file.

On-time percent uses lots whose due is at or before the horizon. A lot is on time only if its route finishes at or before the due. Lots already due at the snapshot stay in the denominator. Weighted tardiness is lot value times minutes late. An open lot is censored at the horizon. Cycle time is the mean completion time of lots that finish the route. X-factor is that completion time divided by the lot's remaining raw process time at the snapshot. Litho utilization is busy time on the 102 `Litho_*` tools divided by tools times horizon. Scanner utilization uses the 82 expose tools. Q-time violations are published CQT misses. PM avoided counts decisions, on every policy, that refused at least one lot because the process would cross a PM. PM overlaps are starts that still run across a PM.

The weekly PM FOA on the focus family is outside a 48-hour window (about 7 days). The steady and litho studies therefore show zero PM events. The PM study subtracts one offset from every day-based calendar so `Litho_FE_92_WK` opens at 2 hours. Duration and interval stay published. One FOA is stored per family, so every tool in the family shares that window.

Lithography breakdown holds `Litho_FE_92-1` (`Litho_FE_92`, largest expose family) for the published lithography MTTR of 705.59 minutes, on top of the seeded breakdowns.

Hot lot `Init_Lot_10_11` is the lowest lot id among normal-priority lots sitting four steps before an expose scanner. The ResiliMES book raises it to VIP with a due 12 hours from the snapshot. FIFO keeps the published priority.

## Tight VIP dues (constructed, 24 hours)

The published dues do not make earliest-due lose on on-time delivery. This book keeps the routes, process times, setups, and CQT limits, and replaces the dues used for scoring. Eight lots waiting at `Dielectric_BE_28` with a later CQT become VIP and are due at 8 hours. The other lots in that queue stay normal and are due at 7.2 hours, so earliest-due serves them first. Every other lot still moves through the fab and is outside the scored horizon. `Dielectric_BE_28-1` is down for the published dielectric MTTR of 604.8 minutes. The family has three tools. Horizon is 24 hours, five seeds.

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 19.05 | 4260.56 | 9.73 | 77.388 | 72.18 | 178.6 | 0.0 | 0.0 | 130.6 | 0.0002 | 0.0067 | 1.59 |
| edd | 12.382 | 8014.66 | 11.548 | 82.002 | 77.854 | 406.6 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0034 | 0.85 |
| fifo | 0.0 | 16991.12 | 14.704 | 82.292 | 78.212 | 411.8 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0033 | 0.775 |
| cr | 9.52 | 7839.72 | 10.002 | 78.782 | 73.856 | 229.2 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0036 | 0.975 |

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 4/21 | 184 | 8 | 3988.6 |
| resilimes | 2 | 4/21 | 180 | 12 | 4125.8 |
| resilimes | 3 | 4/21 | 181 | 6 | 4451.5 |
| resilimes | 4 | 4/21 | 164 | 11 | 4181.3 |
| resilimes | 5 | 4/21 | 184 | 19 | 4555.6 |
| edd | 1 | 3/21 | 411 | 41 | 7696.8 |
| edd | 2 | 3/21 | 433 | 42 | 7627.1 |
| edd | 3 | 2/21 | 414 | 40 | 8171.2 |
| edd | 4 | 2/21 | 383 | 35 | 7719.7 |
| edd | 5 | 3/21 | 392 | 39 | 8858.5 |
| fifo | 1 | 0/21 | 407 | 39 | 16486.8 |
| fifo | 2 | 0/21 | 438 | 39 | 15218.5 |
| fifo | 3 | 0/21 | 414 | 37 | 14895.3 |
| fifo | 4 | 0/21 | 384 | 40 | 16117.2 |
| fifo | 5 | 0/21 | 416 | 37 | 22237.8 |
| cr | 1 | 2/21 | 244 | 23 | 7608.0 |
| cr | 2 | 2/21 | 231 | 19 | 7591.0 |
| cr | 3 | 2/21 | 255 | 20 | 7941.0 |
| cr | 4 | 2/21 | 213 | 22 | 7510.5 |
| cr | 5 | 2/21 | 203 | 13 | 8548.1 |

Seed 1, who paid: 13 non-hot lots in that queue finish 30.71 hours later under ResiliMES than under EDD (Init_Lot_5_5 +2.96 h, Init_Lot_8_3 +2.94 h, Init_Lot_5_14 +2.94 h, Init_Lot_5_4 +2.86 h, Init_Lot_8_9 +2.82 h). Init_Lot_2_23 is 5.45 h late under EDD and 0.0 h late under ResiliMES. On-time on this seed is 14.29% under EDD and 19.05% under ResiliMES. Queue-time violations are 411 and 184.

## X-factor dues (48 hours)

This book keeps the published routes, priorities, and CQT limits. Each due is the remaining raw process time times 2.75. Horizon is 48 hours. 87 lots are due inside it. `Litho_FE_92-1` is held down for a fixed repair on top of the seeded breakdowns. The baseline is EDD. FIFO and CR are on the 600-minute row only. At a 600-minute repair, EDD on-time is 99.54% and ResiliMES is 98.62%. Scanner station families have no row in `setup.txt` and no route `STIME`, so a scanner change does not add setup. A later litho layer stays on the scanner that ran the first layer of its `SVESTN` / `FORSTEP` chain, once this run has chosen that scanner. WIP does not name a tool, so a lot that starts mid-chain is not pinned until then. There is no reticle id, stocker, or transfer time in the extract, and none is invented. A lot in process at a breakdown keeps the remaining process, waits 15 minutes, and resumes on that tool. The 15 minutes are not an SMT2020 column. An adjacent Wet_Etch queue-time step is held back when the next tool cannot start inside the window. A miss sends the lot through that wet step once. That is not the published rework probability. Ten thousand exponential draws of the lithography MTTR (705.59 minutes) have mean 705.4 minutes, population standard deviation 708.7, p50 486.4, p90 1651.4. The share at or under 180 / 300 / 600 minutes is 0.233 / 0.346 / 0.575. Litho utilization at 600 minutes is 77.602% under ResiliMES and 78.34% under EDD, over all 102 `Litho_*` tools. The busiest expose family on the EDD seed-1 run is `Litho_FE_111` at 83.8% (20 tools). Tools were not removed to push that number to 90%.

| ETA min | Policy | OTD % | OTD std | Q-time | Q std | X-factor | X std | Cycle h | Cycle std | Litho util % | Litho std | Re-cleans | Gates |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 180.0 | resilimes | 98.62 | 1.69 | 411.8 | 16.29 | 1.668 | 0.082 | 24.36 | 0.71 | 77.718 | 0.422 | 52.2 | 0.0 |
| 180.0 | edd | 99.54 | 0.563 | 436.8 | 18.159 | 1.608 | 0.063 | 24.888 | 0.224 | 78.454 | 0.347 | 57.6 | 0.0 |
| 180.0 | smt_rule | 73.332 | 6.354 | 704.8 | 23.558 | 2.534 | 0.045 | 26.444 | 0.513 | 76.002 | 0.302 | 87.4 | 0.0 |
| 300.0 | resilimes | 98.62 | 1.69 | 414.8 | 18.883 | 1.669 | 0.083 | 24.456 | 0.649 | 77.706 | 0.468 | 54.0 | 0.0 |
| 300.0 | edd | 99.54 | 0.563 | 434.2 | 16.167 | 1.608 | 0.059 | 24.96 | 0.135 | 78.366 | 0.322 | 69.8 | 0.0 |
| 300.0 | smt_rule | 73.332 | 6.354 | 703.2 | 23.455 | 2.538 | 0.057 | 26.242 | 0.311 | 76.084 | 0.417 | 86.8 | 0.0 |
| 600.0 | resilimes | 98.62 | 1.69 | 416.2 | 20.183 | 1.67 | 0.083 | 24.338 | 0.658 | 77.602 | 0.414 | 52.4 | 0.0 |
| 600.0 | edd | 99.54 | 0.563 | 441.8 | 20.663 | 1.61 | 0.064 | 24.928 | 0.205 | 78.34 | 0.435 | 73.4 | 0.0 |
| 600.0 | fifo | 31.032 | 0.724 | 782.2 | 31.441 | 3.043 | 0.15 | 23.604 | 0.82 | 76.504 | 0.154 | 118.0 | 0.0 |
| 600.0 | cr | 71.724 | 5.843 | 742.4 | 22.241 | 2.531 | 0.037 | 25.994 | 0.342 | 74.924 | 0.494 | 114.0 | 0.0 |
| 600.0 | smt_rule | 73.562 | 6.461 | 700.0 | 18.407 | 2.535 | 0.049 | 26.402 | 0.404 | 76.132 | 0.381 | 88.0 | 0.0 |
| 705.59 | resilimes | 98.62 | 1.69 | 419.2 | 21.018 | 1.668 | 0.083 | 24.364 | 0.696 | 77.632 | 0.373 | 44.8 | 0.0 |
| 705.59 | edd | 99.54 | 0.563 | 444.2 | 22.176 | 1.611 | 0.062 | 24.944 | 0.127 | 78.464 | 0.365 | 68.0 | 0.0 |
| 705.59 | smt_rule | 72.412 | 6.973 | 698.2 | 19.25 | 2.536 | 0.056 | 26.33 | 0.378 | 76.112 | 0.452 | 82.0 | 0.0 |

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 86/87 | 450 | 41 | 283.0 |
| resilimes | 2 | 83/87 | 392 | 70 | 659.9 |
| resilimes | 3 | 86/87 | 403 | 45 | 779.2 |
| resilimes | 4 | 87/87 | 426 | 50 | 0.0 |
| resilimes | 5 | 87/87 | 410 | 56 | 0.0 |
| edd | 1 | 87/87 | 452 | 51 | 0.0 |
| edd | 2 | 86/87 | 425 | 89 | 627.8 |
| edd | 3 | 86/87 | 410 | 87 | 778.4 |
| edd | 4 | 87/87 | 461 | 76 | 0.0 |
| edd | 5 | 87/87 | 461 | 64 | 0.0 |
| fifo | 1 | 27/87 | 812 | 129 | 28292.3 |
| fifo | 2 | 27/87 | 815 | 128 | 34776.1 |
| fifo | 3 | 26/87 | 751 | 119 | 34946.2 |
| fifo | 4 | 27/87 | 739 | 100 | 26616.8 |
| fifo | 5 | 28/87 | 794 | 114 | 28100.8 |
| cr | 1 | 57/87 | 775 | 111 | 1699.4 |
| cr | 2 | 60/87 | 719 | 96 | 972.4 |
| cr | 3 | 72/87 | 716 | 108 | 1079.5 |
| cr | 4 | 61/87 | 748 | 123 | 950.8 |
| cr | 5 | 62/87 | 754 | 132 | 915.7 |
| smt_rule | 1 | 55/87 | 732 | 102 | 1708.1 |
| smt_rule | 2 | 64/87 | 699 | 67 | 732.2 |
| smt_rule | 3 | 72/87 | 678 | 96 | 867.9 |
| smt_rule | 4 | 67/87 | 687 | 80 | 748.1 |
| smt_rule | 5 | 62/87 | 704 | 95 | 1231.3 |

On-time for ResiliMES and EDD is the same at a 180, 300, 600, 705.59 minute repair.

Seed 1, who paid: 1 non-hot lot, 4.72 extra hours (Init_Lot_1_16 +4.72 h). Mean X-factor on this seed is 1.553 under EDD and 1.588 under ResiliMES. Upstream gates 0. Re-cleans 41. Spread across seeds is the population standard deviation, n=5.

## Appendix: published order book (performance)

On the published dues, a 48-hour horizon, ResiliMES and EDD tie on on-time delivery. ResiliMES weighted tardiness is 20063.78 minutes against 20265.92. These tables are runtime and knock-on measurements. They are not the claim that earliest-due loses.

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 32/56 | 395 | 21 | 19311.9 |
| resilimes | 2 | 32/56 | 389 | 32 | 20202.6 |
| resilimes | 3 | 32/56 | 380 | 26 | 20641.2 |
| resilimes | 4 | 32/56 | 380 | 18 | 20031.5 |
| resilimes | 5 | 32/56 | 378 | 25 | 20131.7 |
| edd | 1 | 32/56 | 451 | 38 | 20239.0 |
| edd | 2 | 32/56 | 456 | 55 | 19616.1 |
| edd | 3 | 32/56 | 437 | 39 | 20795.7 |
| edd | 4 | 32/56 | 448 | 35 | 20886.2 |
| edd | 5 | 32/56 | 449 | 36 | 19792.6 |
| fifo | 1 | 19/56 | 793 | 104 | 47757.5 |
| fifo | 2 | 18/56 | 716 | 112 | 49316.5 |
| fifo | 3 | 17/56 | 740 | 116 | 50234.8 |
| fifo | 4 | 19/56 | 727 | 93 | 47570.3 |
| fifo | 5 | 19/56 | 769 | 111 | 47859.3 |
| cr | 1 | 32/56 | 413 | 42 | 20061.8 |
| cr | 2 | 31/56 | 414 | 45 | 20629.1 |
| cr | 3 | 32/56 | 430 | 55 | 19782.1 |
| cr | 4 | 31/56 | 409 | 42 | 20672.9 |
| cr | 5 | 32/56 | 406 | 45 | 20647.9 |
| smt_rule | 1 | 32/56 | 435 | 8 | 19969.0 |
| smt_rule | 2 | 31/56 | 439 | 8 | 21549.1 |
| smt_rule | 3 | 32/56 | 433 | 10 | 20246.7 |
| smt_rule | 4 | 32/56 | 422 | 8 | 20258.3 |
| smt_rule | 5 | 32/56 | 428 | 7 | 19761.0 |

### Steady fab (seeded breakdowns, published PM calendar unshifted)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 20063.78 | 27.232 | 76.146 | 71.76 | 384.4 | 0.0 | 0.0 | 121.4 | 0.0002 | 0.0068 | 2.864 |
| edd | 57.14 | 20265.92 | 26.156 | 78.736 | 74.604 | 448.2 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0036 | 1.722 |
| fifo | 32.858 | 48547.68 | 24.694 | 76.318 | 70.734 | 749.0 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0032 | 1.592 |
| cr | 56.428 | 20358.76 | 28.496 | 73.726 | 67.842 | 414.4 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0035 | 1.825 |
| smt_rule | 56.784 | 20356.82 | 27.68 | 76.034 | 70.434 | 431.4 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0043 | 2.258 |

`smt_rule` is `rule_HotLotFIRST` with `rank_HP;rank_RSETUP;rank_CR` (PRIOR at least 20 first, then higher PRIOR, then shorter setup, then lower CR). Implant_128, Implant_132, and Implant_91 use `rule_LSSU` (setup first, then that cascade). The idle-tool loop still picks the tool. `wake_LeastSetupTime` is not implemented. On published dues, ResiliMES on-time 57.14% beats smt_rule 56.784%. Weighted tardiness is 20356.82 minutes under smt_rule and 20063.78 under ResiliMES. Q-time is 431.4 against 384.4. Re-cleans are 8.2 against 24.4. On X-factor dues at a 600-minute repair, ResiliMES on-time 98.62% beats smt_rule 73.562%. Weighted tardiness is 1057.52 minutes under smt_rule and 344.42 under ResiliMES. Q-time is 700.0 against 416.2. Re-cleans are 88.0 against 52.4. These rows were not tuned after the run.

### Lithography breakdown

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.784 | 20091.88 | 27.192 | 75.954 | 71.6 | 385.8 | 0.0 | 0.0 | 114.2 | 0.0002 | 0.0069 | 2.893 |
| edd | 57.14 | 20047.28 | 26.104 | 78.858 | 74.762 | 442.2 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0034 | 1.687 |

While `Litho_FE_92-1` is down, other tools in `Litho_FE_92` start 247.8 lots under ResiliMES and 247.8 under EDD (five-seed mean). The family queue peaks at 40.0 lots. The downstream queue peaks at 208.6 under ResiliMES and 252.8 under EDD. On-time uses 56.0 lots due inside the horizon, of which 10.0 are already late at the snapshot. The interactive lithography click is 12 hours and seed 1, and the two policies tie there at 2/19. That click is not this 48-hour table.

### PM avoidance (calendar shifted, durations unchanged)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 21083.04 | 27.682 | 74.85 | 70.618 | 370.0 | 46.2 | 0.0 | 142.6 | 0.0002 | 0.0066 | 2.765 |
| edd | 57.14 | 21727.64 | 27.006 | 76.886 | 73.094 | 438.2 | 50.2 | 0.0 | 0.0 | 0.0002 | 0.0033 | 1.665 |

### Hot lot

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 54.388 | 25292.32 | 27.292 | 76.116 | 71.74 | 386.0 | 0.0 | 0.0 | 118.0 | 0.0002 | 0.0067 | 2.829 |
| fifo | 32.858 | 48547.68 | 24.694 | 76.318 | 70.734 | 749.0 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0031 | 1.542 |

`Init_Lot_10_11` completes 37.0 steps under ResiliMES and 23.0 under FIFO. Promoting it moves the on-time denominator to 57.0 lots (56.0 on the FIFO book).

## Seeds 9-13 control (regenerated by make smt-bench)

Shipped score only. Seeds 9, 10, 11, 12, 13. X-factor book: due = remaining process times 2.75, 48 hours, `Litho_FE_92-1` down 600 minutes. Published-due book: 48 hours, published dues. PM refusal applies to every policy. This table is recomputed by `make smt-bench`.

| Book | Policy | On time | Q-time | Re-cleans | Per seed |
| --- | --- | ---: | ---: | ---: | --- |
| xfactor | resilimes | 432/435 | 2114 | 185 | 86/87, 86/87, 87/87, 86/87, 87/87 |
| xfactor | edd | 434/435 | 2261 | 403 | 86/87, 87/87, 87/87, 87/87, 87/87 |
| xfactor | fifo | 138/435 | 3750 | 531 | 22/87, 29/87, 31/87, 28/87, 28/87 |
| xfactor | cr | 318/435 | 3774 | 574 | 57/87, 65/87, 69/87, 63/87, 64/87 |
| published | resilimes | 157/280 | 1917 | 112 | 32/56, 32/56, 32/56, 32/56, 29/56 |
| published | edd | 160/280 | 2220 | 174 | 32/56, 32/56, 32/56, 32/56, 32/56 |
| published | fifo | 95/280 | 3560 | 505 | 19/56, 20/56, 18/56, 19/56, 19/56 |
| published | cr | 155/280 | 2055 | 222 | 31/56, 31/56, 31/56, 31/56, 31/56 |

## Seeds 9-13 arm decisions (pre-fix lab note, not regenerated by make smt-bench)

The rows below are the one-shot recorded before `make smt-bench` regenerated the control, and before the stale-queue fix in [invariants.md](invariants.md). They were measured on the simulator that let a lot start a step on a tool of the wrong family. The expose-due and dry-etch arms are not in the code, so this command does not recompute them. Do not read the lab-note control as the current score. The current score is the regenerated table above.

Registered before that one-shot. Seeds 9, 10, 11, 12, 13. X-factor book: due = remaining process times 2.75, 48 hours, 87 lots due, `Litho_FE_92-1` down 600 minutes. Published-due book: 48 hours, 56 lots due. Policies: ResiliMES, EDD, FIFO, CR. Slack threshold 7200 seconds. Keep a ResiliMES arm only when, on both books, the on-time lot count is not lower and re-cleans are not higher and Q-time violations are not higher than the control. EDD, FIFO, and CR matched the control on every arm.

Control in this lab note is the score shipped at that one-shot: lot due inside `dpi()`, the Wet_Etch gate, and the candidate cap. Sums are five seeds.

| Book | Arm | Decision | On time | Q-time | Re-cleans |
| --- | --- | --- | ---: | ---: | ---: |
| X-factor | control |  | 407/435 | 2223 | 223 |
| X-factor | expose due inside dpi() | revert | 420/435 | 2148 | 208 |
| X-factor | dry-etch queue gate | revert | 407/435 | 2198 | 213 |
| X-factor | slack at or under 7200 s stays | keep | 407/435 | 2223 | 223 |
| Published | control |  | 156/280 | 1821 | 131 |
| Published | expose due inside dpi() | revert | 155/280 | 1862 | 147 |
| Published | dry-etch queue gate | revert | 156/280 | 1850 | 131 |
| Published | slack at or under 7200 s stays | keep | 156/280 | 1821 | 131 |

The expose-step due raised X-factor on-time and cut re-cleans and Q-time, and lost one published-due lot (156 to 155) while raising that book's Q-time and re-cleans. Reverted. `dpi()` still uses the lot due. `rank()` still calls `dispatch_score`.

The dry-etch gate, aimed at the 44 adjacent 1-hour Dry_Etch to Wet_Etch pairs and counting lots already queued downstream, held X-factor on-time and cut that book's Q-time (2223 to 2198) and re-cleans (223 to 213). Published-due on-time stayed 156/280 and Q-time rose from 1821 to 1850. Reverted. The Wet_Etch gate remains, and it fired 0 times on the books above.

The slack exception matched the control on every seed of both books. It stays in `choose()`.

Per seed, ResiliMES on time, X-factor control: 82/87, 74/87, 87/87, 87/87, 77/87. Expose due: 82/87, 87/87, 87/87, 87/87, 77/87. Dry-etch: 82/87, 74/87, 87/87, 87/87, 77/87. Slack: same as control.

Per seed, ResiliMES on time, published control: 32/56, 31/56, 32/56, 32/56, 29/56. Expose due: 32/56, 31/56, 32/56, 32/56, 28/56. Dry-etch and slack: same as control.

Per-seed rows are in `data/smt2020/benchmark.json`. Regenerate with `make smt-bench`.
What the extract contains, and what this simulator leaves out, is [SMT2020_PROVENANCE.md](SMT2020_PROVENANCE.md).
