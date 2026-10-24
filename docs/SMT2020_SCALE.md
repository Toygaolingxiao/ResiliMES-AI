# SMT2020 full-fab measurements

Public industry benchmark (SMT2020). Source: Kopp, Hassoun, Kalir, and Mönch, IEEE Trans. Semicond. Manuf. 33(4), 2020, doi 10.1109/TSM.2020.3001933. PySCFabSim-release commit `0dbff6a`, directory `datasets/SMT2020_LVHM`. This is not a recording from a production fab.

Fab: 106 station families, 1313 tools, 102 `Litho_*` tools (82 expose scanners plus 20 `Litho_REG`), 10 products, 2156 initial WIP lots, 12 station groups. `Delay_32` is included (400 tools, 147 route steps).

## The trade

X-factor dues, 48 hours, 87 lots. On-time for ResiliMES and EDD is the same at a 180, 300, 600, 705.59 minute repair. ResiliMES 87/87, 87/87, 85/87, 87/87, 87/87 (433/435 pooled), mean 99.54%. EDD 87/87, 87/87, 85/87, 87/87, 87/87 (433/435 pooled), mean 99.54%. FIFO mean 47.126%. CR mean 76.552%. ResiliMES beats FIFO and CR by a wide margin. Versus EDD it ties on pooled on-time lots, with re-cleans 53.4 against 48.8 and Q-time violations 436.8 against 479.0 (five-seed means).

Published dues, 48 hours, 56 lots. ResiliMES 32/56, 32/56, 32/56, 32/56, 31/56 (159/280 pooled), mean 56.784%. EDD 33/56, 33/56, 32/56, 33/56, 32/56 (163/280 pooled), mean 58.214%. EDD is ahead by 4 pooled lots.

Tight VIP dues rewrites the dues for the stress test. It is not the published order book. Denominator 21 lots. ResiliMES 5/21, 6/21, 6/21, 6/21, 5/21 (28/105 pooled). EDD 4/21, 4/21, 3/21, 4/21, 4/21 (19/105 pooled). FIFO 1/21, 1/21, 1/21, 0/21, 1/21 (4/105 pooled). CR 4/21, 4/21, 3/21, 4/21, 4/21 (19/105 pooled). Seed 1 weighted tardiness is 6842.1 under EDD and 3616.9 under ResiliMES. The 12-hour lithography click is one seed. It is not the 48-hour lithography study in the appendix.

Every number in this file comes from the simulator after the stale-queue fix. Before it, a lot that had already started could stay in its old family queue and start its next step on a tool of the wrong family. The trace checker and the pre-fix numbers are in [invariants.md](invariants.md). It also includes the fab-logic-r1 operation logic: every lot chosen for a batch starts, same-recipe lots batch across operation numbers under a wait rule, setup time is charged, a breakdown sends the lot in process to rework, sampled metrology is skipped by a lot-ID rule, and ResiliMES ranks by class tier first. Old against new numbers are in [FAB_LOGIC_R1.md](FAB_LOGIC_R1.md).

The tight VIP table is 24 hours. The appendix is 48 hours from 2018-01-01 00:00 UTC. Seeds: 1, 2, 3, 4, 5. Each seed draws exponential MTTF/MTTR from `downcal.txt`, one clock per tool. The same draw is shared across policies.

Macro APS places 30625 scanner steps. That step count is the stable spec. The timer is about 0.3 s on the CI VM (this run recorded 295.4 ms).

Dispatch latency is the time to choose the next lot for one idle tool, look-ahead 24 (8 when that family's queue exceeds two lots per tool). The headline p50/p95 includes empty wakes. Nonempty-queue decisions on the X-factor ResiliMES runs, seeds 1-5, were p50 0.0114-0.0125 ms and p95 0.1011-0.1181 ms on this run. It is not the full simulation time. Simulation time is the whole 48-hour run.

The WIP column is a candidate cap, not a replan. `choose()` keeps 8 lots instead of 24 after a family exceeds max(8, two lots per tool), and also keeps a lot whose slack is at or under 7200 seconds. The adjacent Wet_Etch look-ahead fired 0 times on these books. `macro_aps_ms` does not feed `dpi()`. `rank()` for resilimes uses `tiered_key`: class tier, late band, Q-time risk, setup, then slack. `dispatch_score` is no longer used there. A down tool queues the end of every covering window, so a forced outage that overlaps an MTTF draw still releases at the later end. Seeds 1-5 on-time on the books below match the figures in this file.

On-time percent uses lots whose due is at or before the horizon. A lot is on time only if its route finishes at or before the due. Lots already due at the snapshot stay in the denominator. Weighted tardiness is lot value times minutes late. An open lot is censored at the horizon. Cycle time is the mean completion time of lots that finish the route. X-factor is that completion time divided by the lot's remaining raw process time at the snapshot. Litho utilization is busy time on the 102 `Litho_*` tools divided by tools times horizon. Scanner utilization uses the 82 expose tools. Q-time violations are published CQT misses. PM avoided counts decisions, on every policy, that refused at least one lot because the process would cross a PM. PM overlaps are starts that still run across a PM.

The weekly PM FOA on the focus family is outside a 48-hour window (about 7 days). The steady and litho studies therefore show zero PM events. The PM study subtracts one offset from every day-based calendar so `Litho_FE_92_WK` opens at 2 hours. Duration and interval stay published. One FOA is stored per family, so every tool in the family shares that window.

Lithography breakdown holds `Litho_FE_92-1` (`Litho_FE_92`, largest expose family) for the published lithography MTTR of 705.59 minutes, on top of the seeded breakdowns.

Hot lot `Init_Lot_10_11` is the lowest lot id among normal-priority lots sitting four steps before an expose scanner. The ResiliMES book raises it to VIP with a due 12 hours from the snapshot. FIFO keeps the published priority.

## Tight VIP dues (constructed, 24 hours)

The published dues do not make earliest-due lose on on-time delivery. This book keeps the routes, process times, setups, and CQT limits, and replaces the dues used for scoring. Eight lots waiting at `Dielectric_BE_28` with a later CQT become VIP and are due at 8 hours. The other lots in that queue stay normal and are due at 7.2 hours, so earliest-due serves them first. Every other lot still moves through the fab and is outside the scored horizon. `Dielectric_BE_28-1` is down for the published dielectric MTTR of 604.8 minutes. The family has three tools. Horizon is 24 hours, five seeds.

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 26.666 | 3548.88 | 9.31 | 83.854 | 84.494 | 170.6 | 0.0 | 0.0 | 155.8 | 0.0002 | 0.0053 | 1.349 |
| edd | 18.098 | 7005.34 | 10.896 | 84.256 | 84.202 | 512.4 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0033 | 0.974 |
| fifo | 3.808 | 10614.14 | 12.85 | 84.22 | 84.202 | 511.4 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0032 | 0.911 |
| cr | 18.098 | 6963.74 | 8.774 | 81.39 | 81.848 | 229.4 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0034 | 1.073 |

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 5/21 | 181 | 2 | 3616.9 |
| resilimes | 2 | 6/21 | 166 | 4 | 3636.7 |
| resilimes | 3 | 6/21 | 202 | 3 | 3581.4 |
| resilimes | 4 | 6/21 | 160 | 7 | 3177.6 |
| resilimes | 5 | 5/21 | 144 | 2 | 3731.8 |
| edd | 1 | 4/21 | 509 | 16 | 6842.1 |
| edd | 2 | 4/21 | 517 | 22 | 6783.9 |
| edd | 3 | 3/21 | 522 | 17 | 7593.6 |
| edd | 4 | 4/21 | 535 | 16 | 6791.6 |
| edd | 5 | 4/21 | 479 | 11 | 7015.5 |
| fifo | 1 | 1/21 | 513 | 15 | 8773.3 |
| fifo | 2 | 1/21 | 509 | 21 | 9777.3 |
| fifo | 3 | 1/21 | 518 | 16 | 9193.5 |
| fifo | 4 | 0/21 | 533 | 16 | 9823.9 |
| fifo | 5 | 1/21 | 484 | 11 | 15502.7 |
| cr | 1 | 4/21 | 238 | 10 | 6677.7 |
| cr | 2 | 4/21 | 228 | 11 | 6754.6 |
| cr | 3 | 3/21 | 243 | 10 | 7470.7 |
| cr | 4 | 4/21 | 233 | 9 | 6896.7 |
| cr | 5 | 4/21 | 205 | 9 | 7019.0 |

Seed 1, who paid: 13 non-hot lots in that queue finish 39.8 hours later under ResiliMES than under EDD (Init_Lot_8_2 +5.11 h, Init_Lot_8_7 +3.37 h, Init_Lot_8_4 +3.33 h, Init_Lot_5_14 +3.33 h, Init_Lot_8_20 +3.19 h). Init_Lot_2_13 is 5.03 h late under EDD and 0.0 h late under ResiliMES. On-time on this seed is 19.05% under EDD and 23.81% under ResiliMES. Queue-time violations are 509 and 181.

## X-factor dues (48 hours)

This book keeps the published routes, priorities, and CQT limits. Each due is the remaining raw process time times 2.75. Horizon is 48 hours. 87 lots are due inside it. `Litho_FE_92-1` is held down for a fixed repair on top of the seeded breakdowns. The baseline is EDD. FIFO and CR are on the 600-minute row only. At a 600-minute repair, ResiliMES and EDD tie on on-time delivery at 99.54%. Scanner station families have no row in `setup.txt` and no route `STIME`, so a scanner change does not add setup. A later litho layer stays on the scanner that ran the first layer of its `SVESTN` / `FORSTEP` chain, once this run has chosen that scanner. WIP does not name a tool, so a lot that starts mid-chain is not pinned until then. If that scanner is down, the lot may run on another scanner of the family and is re-pinned there. There is no reticle id, stocker, or transfer time in the extract, and none is invented. A lot in process at a breakdown goes to rework: the work is lost, it waits 30 minutes, and then redoes the whole operation from the family queue on any qualified tool. The rework hold is a ResiliMES default, not an SMT2020 column. An adjacent Wet_Etch queue-time step is held back when the next tool cannot start inside the window. A miss sends the lot through that wet step once. That is not the published rework probability. Ten thousand exponential draws of the lithography MTTR (705.59 minutes) have mean 705.4 minutes, population standard deviation 708.7, p50 486.4, p90 1651.4. The share at or under 180 / 300 / 600 minutes is 0.233 / 0.346 / 0.575. Litho utilization at 600 minutes is 79.262% under ResiliMES and 75.708% under EDD, over all 102 `Litho_*` tools. The busiest expose family on the EDD seed-1 run is `Litho_BE_110` at 94.5% (23 tools). Tools were not removed to push that number to 90%.

| ETA min | Policy | OTD % | OTD std | Q-time | Q std | X-factor | X std | Cycle h | Cycle std | Litho util % | Litho std | Re-cleans | Gates |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 180.0 | resilimes | 99.54 | 0.92 | 431.8 | 20.449 | 1.627 | 0.062 | 23.916 | 0.816 | 78.918 | 0.516 | 53.0 | 0.0 |
| 180.0 | edd | 99.54 | 0.92 | 477.8 | 12.89 | 1.569 | 0.04 | 24.352 | 0.297 | 75.992 | 0.6 | 53.6 | 0.0 |
| 180.0 | smt_rule | 77.702 | 8.049 | 949.4 | 15.357 | 2.492 | 0.071 | 25.028 | 0.41 | 80.048 | 0.398 | 60.8 | 0.0 |
| 300.0 | resilimes | 99.54 | 0.92 | 429.6 | 22.312 | 1.626 | 0.063 | 23.834 | 0.906 | 79.548 | 0.678 | 53.8 | 0.0 |
| 300.0 | edd | 99.54 | 0.92 | 481.0 | 10.507 | 1.571 | 0.039 | 24.444 | 0.213 | 75.676 | 0.47 | 51.4 | 0.0 |
| 300.0 | smt_rule | 76.782 | 7.284 | 939.0 | 12.681 | 2.491 | 0.071 | 25.072 | 0.392 | 80.004 | 0.413 | 64.0 | 0.0 |
| 600.0 | resilimes | 99.54 | 0.92 | 436.8 | 20.653 | 1.625 | 0.063 | 23.928 | 0.807 | 79.262 | 0.623 | 53.4 | 0.0 |
| 600.0 | edd | 99.54 | 0.92 | 479.0 | 9.011 | 1.57 | 0.039 | 24.394 | 0.247 | 75.708 | 0.473 | 48.8 | 0.0 |
| 600.0 | fifo | 47.126 | 9.224 | 844.6 | 43.019 | 2.918 | 0.158 | 26.818 | 0.424 | 77.164 | 0.385 | 71.4 | 0.0 |
| 600.0 | cr | 76.552 | 8.621 | 915.8 | 21.32 | 2.515 | 0.068 | 24.424 | 0.414 | 75.304 | 0.587 | 67.4 | 0.0 |
| 600.0 | smt_rule | 77.702 | 7.85 | 947.2 | 11.461 | 2.49 | 0.072 | 25.0 | 0.427 | 79.954 | 0.465 | 60.0 | 0.0 |
| 705.59 | resilimes | 99.54 | 0.92 | 433.4 | 22.739 | 1.627 | 0.064 | 23.98 | 0.754 | 79.288 | 0.777 | 52.0 | 0.0 |
| 705.59 | edd | 99.54 | 0.92 | 475.6 | 5.953 | 1.569 | 0.04 | 24.428 | 0.242 | 75.848 | 0.461 | 49.0 | 0.0 |
| 705.59 | smt_rule | 77.242 | 8.076 | 945.0 | 8.509 | 2.492 | 0.072 | 25.072 | 0.421 | 80.048 | 0.398 | 60.6 | 0.0 |

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 87/87 | 448 | 57 | 0.0 |
| resilimes | 2 | 87/87 | 452 | 53 | 0.0 |
| resilimes | 3 | 85/87 | 410 | 50 | 3.8 |
| resilimes | 4 | 87/87 | 460 | 54 | 0.0 |
| resilimes | 5 | 87/87 | 414 | 53 | 0.0 |
| edd | 1 | 87/87 | 494 | 44 | 0.0 |
| edd | 2 | 87/87 | 477 | 48 | 0.0 |
| edd | 3 | 85/87 | 466 | 52 | 3.8 |
| edd | 4 | 87/87 | 481 | 53 | 0.0 |
| edd | 5 | 87/87 | 477 | 47 | 0.0 |
| fifo | 1 | 39/87 | 921 | 77 | 7697.9 |
| fifo | 2 | 34/87 | 844 | 60 | 26904.1 |
| fifo | 3 | 33/87 | 795 | 65 | 20226.4 |
| fifo | 4 | 55/87 | 814 | 83 | 5231.2 |
| fifo | 5 | 44/87 | 849 | 72 | 9787.3 |
| cr | 1 | 55/87 | 927 | 58 | 1788.6 |
| cr | 2 | 62/87 | 876 | 76 | 721.8 |
| cr | 3 | 77/87 | 938 | 60 | 264.0 |
| cr | 4 | 69/87 | 914 | 73 | 646.8 |
| cr | 5 | 70/87 | 924 | 70 | 651.0 |
| smt_rule | 1 | 55/87 | 955 | 56 | 1521.5 |
| smt_rule | 2 | 66/87 | 944 | 67 | 496.6 |
| smt_rule | 3 | 74/87 | 929 | 57 | 358.4 |
| smt_rule | 4 | 71/87 | 945 | 55 | 431.2 |
| smt_rule | 5 | 72/87 | 963 | 65 | 397.1 |

On-time for ResiliMES and EDD is the same at a 180, 300, 600, 705.59 minute repair.

Seed 1, who paid: no scored non-hot lot finishes later under ResiliMES than under EDD. Mean X-factor on this seed is 1.531 under EDD and 1.562 under ResiliMES. Upstream gates 0. Re-cleans 57. Spread across seeds is the population standard deviation, n=5.

## Appendix: published order book (performance)

On the published dues, a 48-hour horizon, EDD is slightly ahead of ResiliMES on on-time delivery (58.214% against 56.784%). EDD weighted tardiness is 19032.5 minutes against 19095.04. These tables are runtime and knock-on measurements. They are not the claim that earliest-due loses.

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 32/56 | 416 | 55 | 18915.1 |
| resilimes | 2 | 32/56 | 385 | 32 | 19579.8 |
| resilimes | 3 | 32/56 | 367 | 50 | 18981.3 |
| resilimes | 4 | 32/56 | 410 | 56 | 18777.2 |
| resilimes | 5 | 31/56 | 366 | 42 | 19221.8 |
| edd | 1 | 33/56 | 468 | 61 | 18420.2 |
| edd | 2 | 33/56 | 418 | 47 | 18972.0 |
| edd | 3 | 32/56 | 408 | 62 | 19419.9 |
| edd | 4 | 33/56 | 437 | 62 | 19140.7 |
| edd | 5 | 32/56 | 432 | 54 | 19209.7 |
| fifo | 1 | 20/56 | 894 | 75 | 44362.8 |
| fifo | 2 | 19/56 | 841 | 58 | 46551.1 |
| fifo | 3 | 20/56 | 807 | 66 | 45082.8 |
| fifo | 4 | 21/56 | 846 | 84 | 41925.6 |
| fifo | 5 | 21/56 | 845 | 76 | 44750.1 |
| cr | 1 | 33/56 | 430 | 52 | 17892.9 |
| cr | 2 | 32/56 | 362 | 58 | 18547.1 |
| cr | 3 | 32/56 | 399 | 50 | 18463.0 |
| cr | 4 | 32/56 | 358 | 59 | 18344.2 |
| cr | 5 | 32/56 | 370 | 46 | 18993.7 |
| smt_rule | 1 | 32/56 | 401 | 36 | 18572.5 |
| smt_rule | 2 | 32/56 | 399 | 24 | 18906.8 |
| smt_rule | 3 | 32/56 | 424 | 27 | 18402.5 |
| smt_rule | 4 | 32/56 | 358 | 19 | 18654.7 |
| smt_rule | 5 | 32/56 | 397 | 27 | 18719.3 |

### Steady fab (seeded breakdowns, published PM calendar unshifted)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.784 | 19095.04 | 27.188 | 80.57 | 80.786 | 388.8 | 0.0 | 0.0 | 225.6 | 0.0002 | 0.0052 | 2.61 |
| edd | 58.214 | 19032.5 | 26.138 | 76.794 | 77.03 | 432.6 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.003 | 1.854 |
| fifo | 36.07 | 44534.48 | 27.222 | 77.286 | 77.638 | 846.6 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.003 | 1.788 |
| cr | 57.498 | 18448.18 | 27.62 | 74.756 | 75.248 | 383.8 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0033 | 2.077 |
| smt_rule | 57.14 | 18651.16 | 27.376 | 80.19 | 80.68 | 395.8 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0046 | 3.159 |

`smt_rule` is `rule_HotLotFIRST` with `rank_HP;rank_RSETUP;rank_CR` (PRIOR at least 20 first, then higher PRIOR, then shorter setup, then lower CR). Implant_128, Implant_132, and Implant_91 use `rule_LSSU` (setup first, then that cascade). The idle-tool loop still picks the tool. `wake_LeastSetupTime` is not implemented. On published dues, smt_rule on-time 57.14% beats ResiliMES 56.784%. Weighted tardiness is 18651.16 minutes under smt_rule and 19095.04 under ResiliMES. Q-time is 395.8 against 388.8. Re-cleans are 26.6 against 47.0. On X-factor dues at a 600-minute repair, ResiliMES on-time 99.54% beats smt_rule 77.702%. Weighted tardiness is 640.96 minutes under smt_rule and 0.76 under ResiliMES. Q-time is 947.2 against 436.8. Re-cleans are 60.0 against 53.4. These rows were not tuned after the run.

### Lithography breakdown

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 19126.44 | 27.282 | 80.488 | 80.706 | 387.6 | 0.0 | 0.0 | 219.8 | 0.0002 | 0.0053 | 2.686 |
| edd | 57.498 | 19027.66 | 26.176 | 76.768 | 76.966 | 433.0 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0031 | 1.884 |

While `Litho_FE_92-1` is down, other tools in `Litho_FE_92` start 205.0 lots under ResiliMES and 201.6 under EDD (five-seed mean). The family queue peaks at 40.0 lots. The downstream queue peaks at 41.0 under ResiliMES and 41.0 under EDD. On-time uses 56.0 lots due inside the horizon, of which 10.0 are already late at the snapshot. The interactive lithography click is 12 hours and seed 1, and the two policies tie there at 2/19. That click is not this 48-hour table.

### PM avoidance (calendar shifted, durations unchanged)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 19952.5 | 27.51 | 78.39 | 78.53 | 367.6 | 74.4 | 0.0 | 223.6 | 0.0002 | 0.0052 | 2.589 |
| edd | 58.214 | 19886.58 | 26.668 | 75.044 | 75.134 | 437.6 | 92.8 | 0.0 | 0.0 | 0.0002 | 0.003 | 1.856 |

### Hot lot

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.14 | 24070.0 | 27.416 | 80.594 | 80.782 | 394.0 | 0.0 | 0.0 | 231.0 | 0.0002 | 0.0054 | 2.7 |
| fifo | 36.07 | 44534.48 | 27.222 | 77.286 | 77.638 | 846.6 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0031 | 1.797 |

`Init_Lot_10_11` completes 34.0 steps under ResiliMES and 21.6 under FIFO. Promoting it moves the on-time denominator to 57.0 lots (56.0 on the FIFO book).

## Seeds 9-13 control (regenerated by make smt-bench)

Shipped score only. Seeds 9, 10, 11, 12, 13. X-factor book: due = remaining process times 2.75, 48 hours, `Litho_FE_92-1` down 600 minutes. Published-due book: 48 hours, published dues. PM refusal applies to every policy. This table is recomputed by `make smt-bench`.

| Book | Policy | On time | Q-time | Re-cleans | Per seed |
| --- | --- | ---: | ---: | ---: | --- |
| xfactor | resilimes | 435/435 | 2185 | 280 | 87/87, 87/87, 87/87, 87/87, 87/87 |
| xfactor | edd | 435/435 | 2412 | 257 | 87/87, 87/87, 87/87, 87/87, 87/87 |
| xfactor | fifo | 243/435 | 4389 | 414 | 40/87, 53/87, 59/87, 40/87, 51/87 |
| xfactor | cr | 344/435 | 4467 | 339 | 59/87, 66/87, 77/87, 71/87, 71/87 |
| published | resilimes | 160/280 | 1920 | 218 | 32/56, 32/56, 32/56, 32/56, 32/56 |
| published | edd | 160/280 | 2170 | 294 | 32/56, 32/56, 32/56, 32/56, 32/56 |
| published | fifo | 103/280 | 4400 | 424 | 21/56, 21/56, 21/56, 20/56, 20/56 |
| published | cr | 161/280 | 1869 | 278 | 32/56, 32/56, 33/56, 32/56, 32/56 |

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

The expose-step due raised X-factor on-time and cut re-cleans and Q-time, and lost one published-due lot (156 to 155) while raising that book's Q-time and re-cleans. Reverted. `dpi()` still uses the lot due. At that one-shot `rank()` called `dispatch_score`; since fab-logic-r1 it uses `tiered_key`.

The dry-etch gate, aimed at the 44 adjacent 1-hour Dry_Etch to Wet_Etch pairs and counting lots already queued downstream, held X-factor on-time and cut that book's Q-time (2223 to 2198) and re-cleans (223 to 213). Published-due on-time stayed 156/280 and Q-time rose from 1821 to 1850. Reverted. The Wet_Etch gate remains, and it fired 0 times on the books above.

The slack exception matched the control on every seed of both books. It stays in `choose()`.

Per seed, ResiliMES on time, X-factor control: 82/87, 74/87, 87/87, 87/87, 77/87. Expose due: 82/87, 87/87, 87/87, 87/87, 77/87. Dry-etch: 82/87, 74/87, 87/87, 87/87, 77/87. Slack: same as control.

Per seed, ResiliMES on time, published control: 32/56, 31/56, 32/56, 32/56, 29/56. Expose due: 32/56, 31/56, 32/56, 32/56, 28/56. Dry-etch and slack: same as control.

Per-seed rows are in `data/smt2020/benchmark.json`. Regenerate with `make smt-bench`.
What the extract contains, and what this simulator leaves out, is [SMT2020_PROVENANCE.md](SMT2020_PROVENANCE.md).
