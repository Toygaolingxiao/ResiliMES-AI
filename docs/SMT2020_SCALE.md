# SMT2020 full-fab measurements

Public industry benchmark (SMT2020). Source: Kopp, Hassoun, Kalir, and Mönch, IEEE Trans. Semicond. Manuf. 33(4), 2020, doi 10.1109/TSM.2020.3001933. PySCFabSim-release commit `0dbff6a`, directory `datasets/SMT2020_LVHM`. This is not a recording from a production fab.

Fab: 106 station families, 1313 tools, 102 `Litho_*` tools (82 expose scanners plus 20 `Litho_REG`), 10 products, 2156 initial WIP lots, 12 station groups. `Delay_32` is included (400 tools, 147 route steps).

## The trade

X-factor dues, 48 hours, 87 lots. On-time for ResiliMES and EDD is the same at a 180, 300, 600, 705.59 minute repair. ResiliMES 87/87, 87/87, 83/87, 87/87, 87/87 (431/435 pooled), mean 99.08%. EDD 87/87, 87/87, 85/87, 87/87, 87/87 (433/435 pooled), mean 99.54%. FIFO mean 45.288%. CR mean 76.092%. ResiliMES beats FIFO and CR by a wide margin. Versus EDD it gives up 2 of 435 pooled lots, with re-cleans 44.2 against 55.0 and Q-time violations 231.2 against 470.2 (five-seed means).

Published dues, 48 hours, 56 lots. ResiliMES 32/56, 32/56, 32/56, 32/56, 32/56 (160/280 pooled), mean 57.14%. EDD 33/56, 32/56, 32/56, 32/56, 32/56 (161/280 pooled), mean 57.498%. EDD is ahead by 1 pooled lots.

Tight VIP dues rewrites the dues for the stress test. It is not the published order book. Denominator 21 lots. ResiliMES 6/21, 5/21, 5/21, 6/21, 5/21 (27/105 pooled). EDD 3/21, 3/21, 1/21, 3/21, 3/21 (13/105 pooled). FIFO 1/21, 0/21, 0/21, 0/21, 0/21 (1/105 pooled). CR 3/21, 3/21, 2/21, 3/21, 3/21 (14/105 pooled). Seed 1 weighted tardiness is 7471.6 under EDD and 3573.8 under ResiliMES. The 12-hour lithography click is one seed. It is not the 48-hour lithography study in the appendix.

Every number in this file comes from the simulator after the stale-queue fix. Before it, a lot that had already started could stay in its old family queue and start its next step on a tool of the wrong family. The trace checker and the pre-fix numbers are in [invariants.md](invariants.md). It also includes the fab-logic-r1 operation logic: every lot chosen for a batch starts, same-recipe lots batch across operation numbers under a wait rule, setup time is charged, a breakdown sends the lot in process to rework, sampled metrology is skipped by a lot-ID rule, and ResiliMES ranks by class tier first. Old against new numbers are in [FAB_LOGIC_R1.md](FAB_LOGIC_R1.md).

The tight VIP table is 24 hours. The appendix is 48 hours from 2018-01-01 00:00 UTC. Seeds: 1, 2, 3, 4, 5. Each seed draws exponential MTTF/MTTR from `downcal.txt`, one clock per tool. The same draw is shared across policies.

Macro APS places 30625 scanner steps. That step count is the stable spec. The timer is about 0.3 s on the CI VM (this run recorded 336.9 ms).

Dispatch latency is the time to choose the next lot for one idle tool, look-ahead 24 (8 when that family's queue exceeds two lots per tool). The headline p50/p95 includes empty wakes. Nonempty-queue decisions on the X-factor ResiliMES runs, seeds 1-5, were p50 0.0142-0.0156 ms and p95 0.1307-0.15 ms on this run. It is not the full simulation time. Simulation time is the whole 48-hour run.

The WIP column is a candidate cap, not a replan. `choose()` keeps 8 lots instead of 24 after a family exceeds max(8, two lots per tool), and also keeps a lot whose slack is at or under 7200 seconds. The adjacent Wet_Etch look-ahead fired 0 times on these books. `macro_aps_ms` does not feed `dpi()`. `rank()` for resilimes uses `tiered_key`: class tier, late band, Q-time risk, setup, then slack. `dispatch_score` is no longer used there. A down tool queues the end of every covering window, so a forced outage that overlaps an MTTF draw still releases at the later end. Seeds 1-5 on-time on the books below match the figures in this file.

On-time percent uses lots whose due is at or before the horizon. A lot is on time only if its route finishes at or before the due. Lots already due at the snapshot stay in the denominator. Weighted tardiness is lot value times minutes late. An open lot is censored at the horizon. Cycle time is the mean completion time of lots that finish the route. X-factor is that completion time divided by the lot's remaining raw process time at the snapshot. Litho utilization is busy time on the 102 `Litho_*` tools divided by tools times horizon. Scanner utilization uses the 82 expose tools. Q-time violations are published CQT misses. PM avoided counts decisions, on every policy, that refused at least one lot because the process would cross a PM. PM overlaps are starts that still run across a PM.

The weekly PM FOA on the focus family is outside a 48-hour window (about 7 days). The steady and litho studies therefore show zero PM events. The PM study subtracts one offset from every day-based calendar so `Litho_FE_92_WK` opens at 2 hours. Duration and interval stay published. One FOA is stored per family, so every tool in the family shares that window.

Lithography breakdown holds `Litho_FE_92-1` (`Litho_FE_92`, largest expose family) for the published lithography MTTR of 705.59 minutes, on top of the seeded breakdowns.

Hot lot `Init_Lot_10_11` is the lowest lot id among normal-priority lots sitting four steps before an expose scanner. The ResiliMES book raises it to VIP with a due 12 hours from the snapshot. FIFO keeps the published priority.

## Tight VIP dues (constructed, 24 hours)

The published dues do not make earliest-due lose on on-time delivery. This book keeps the routes, process times, setups, and CQT limits, and replaces the dues used for scoring. Eight lots waiting at `Dielectric_BE_28` with a later CQT become VIP and are due at 8 hours. The other lots in that queue stay normal and are due at 7.2 hours, so earliest-due serves them first. Every other lot still moves through the fab and is outside the scored horizon. `Dielectric_BE_28-1` is down for the published dielectric MTTR of 604.8 minutes. The family has three tools. Horizon is 24 hours, five seeds.

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 25.714 | 3661.74 | 9.806 | 83.91 | 84.682 | 68.0 | 0.0 | 0.0 | 159.2 | 0.0002 | 0.0064 | 1.55 |
| edd | 12.384 | 7730.18 | 11.066 | 83.766 | 83.744 | 504.8 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0033 | 0.998 |
| fifo | 0.952 | 11366.68 | 13.036 | 83.778 | 83.77 | 502.6 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0032 | 0.928 |
| cr | 13.336 | 7682.04 | 9.162 | 80.718 | 81.164 | 228.8 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0035 | 1.088 |

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 6/21 | 97 | 7 | 3573.8 |
| resilimes | 2 | 5/21 | 65 | 5 | 3617.2 |
| resilimes | 3 | 5/21 | 67 | 6 | 3820.8 |
| resilimes | 4 | 6/21 | 57 | 2 | 3577.9 |
| resilimes | 5 | 5/21 | 54 | 4 | 3719.0 |
| edd | 1 | 3/21 | 501 | 21 | 7471.6 |
| edd | 2 | 3/21 | 513 | 22 | 7392.0 |
| edd | 3 | 1/21 | 523 | 10 | 8645.8 |
| edd | 4 | 3/21 | 519 | 16 | 7501.1 |
| edd | 5 | 3/21 | 468 | 13 | 7640.4 |
| fifo | 1 | 1/21 | 507 | 19 | 9338.9 |
| fifo | 2 | 0/21 | 504 | 22 | 10480.3 |
| fifo | 3 | 0/21 | 513 | 14 | 10207.6 |
| fifo | 4 | 0/21 | 518 | 16 | 10535.7 |
| fifo | 5 | 0/21 | 471 | 13 | 16270.9 |
| cr | 1 | 3/21 | 232 | 13 | 7390.8 |
| cr | 2 | 3/21 | 236 | 11 | 7408.9 |
| cr | 3 | 2/21 | 244 | 11 | 7811.9 |
| cr | 4 | 3/21 | 229 | 8 | 8095.8 |
| cr | 5 | 3/21 | 203 | 5 | 7702.8 |

Seed 1, who paid: 13 non-hot lots in that queue finish 36.68 hours later under ResiliMES than under EDD (Init_Lot_8_4 +3.13 h, Init_Lot_5_5 +3.12 h, Init_Lot_8_6 +3.07 h, Init_Lot_5_4 +3.01 h, Init_Lot_8_7 +2.98 h). Init_Lot_2_13 is 5.66 h late under EDD and 0.0 h late under ResiliMES. On-time on this seed is 14.29% under EDD and 28.57% under ResiliMES. Queue-time violations are 501 and 97.

## X-factor dues (48 hours)

This book keeps the published routes, priorities, and CQT limits. Each due is the remaining raw process time times 2.75. Horizon is 48 hours. 87 lots are due inside it. `Litho_FE_92-1` is held down for a fixed repair on top of the seeded breakdowns. The baseline is EDD. FIFO and CR are on the 600-minute row only. At a 600-minute repair, EDD on-time is 99.54% and ResiliMES is 99.08%. Scanner station families have no row in `setup.txt` and no route `STIME`, so a scanner change does not add setup. A later litho layer stays on the scanner that ran the first layer of its `SVESTN` / `FORSTEP` chain, once this run has chosen that scanner. WIP does not name a tool, so a lot that starts mid-chain is not pinned until then. If that scanner is down, the lot may run on another scanner of the family and is re-pinned there. There is no reticle id, stocker, or transfer time in the extract, and none is invented. A lot in process at a breakdown goes to rework: the work is lost, it waits 30 minutes, and then redoes the whole operation from the family queue on any qualified tool. The rework hold is a ResiliMES default, not an SMT2020 column. An adjacent Wet_Etch queue-time step is held back when the next tool cannot start inside the window. A miss sends the lot through that wet step once. That is not the published rework probability. Ten thousand exponential draws of the lithography MTTR (705.59 minutes) have mean 705.4 minutes, population standard deviation 708.7, p50 486.4, p90 1651.4. The share at or under 180 / 300 / 600 minutes is 0.233 / 0.346 / 0.575. Litho utilization at 600 minutes is 79.062% under ResiliMES and 75.77% under EDD, over all 102 `Litho_*` tools. The busiest expose family on the EDD seed-1 run is `Litho_BE_110` at 94.5% (23 tools). Tools were not removed to push that number to 90%.

| ETA min | Policy | OTD % | OTD std | Q-time | Q std | X-factor | X std | Cycle h | Cycle std | Litho util % | Litho std | Re-cleans | Gates |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 180.0 | resilimes | 99.08 | 1.84 | 226.8 | 12.106 | 1.741 | 0.076 | 24.36 | 0.886 | 78.912 | 0.543 | 42.4 | 0.0 |
| 180.0 | edd | 99.54 | 0.92 | 468.6 | 11.164 | 1.59 | 0.042 | 24.686 | 0.28 | 75.512 | 0.524 | 50.4 | 0.0 |
| 180.0 | smt_rule | 76.782 | 6.718 | 938.0 | 17.447 | 2.501 | 0.073 | 25.01 | 0.517 | 79.754 | 0.438 | 62.4 | 0.0 |
| 300.0 | resilimes | 99.08 | 1.84 | 226.0 | 11.832 | 1.739 | 0.072 | 24.288 | 0.879 | 79.08 | 0.263 | 43.8 | 0.0 |
| 300.0 | edd | 99.54 | 0.92 | 473.0 | 12.791 | 1.589 | 0.041 | 24.724 | 0.258 | 75.654 | 0.582 | 53.0 | 0.0 |
| 300.0 | smt_rule | 74.712 | 5.95 | 935.6 | 18.683 | 2.506 | 0.071 | 25.056 | 0.45 | 79.728 | 0.538 | 63.4 | 0.0 |
| 600.0 | resilimes | 99.08 | 1.84 | 231.2 | 12.335 | 1.738 | 0.079 | 24.306 | 1.073 | 79.062 | 0.373 | 44.2 | 0.0 |
| 600.0 | edd | 99.54 | 0.92 | 470.2 | 11.089 | 1.59 | 0.042 | 24.622 | 0.243 | 75.77 | 0.706 | 55.0 | 0.0 |
| 600.0 | fifo | 45.288 | 8.435 | 836.4 | 39.525 | 2.941 | 0.156 | 26.742 | 0.589 | 76.76 | 0.4 | 69.4 | 0.0 |
| 600.0 | cr | 76.092 | 7.175 | 900.8 | 28.729 | 2.508 | 0.067 | 24.378 | 0.425 | 75.264 | 0.507 | 67.8 | 0.0 |
| 600.0 | smt_rule | 74.942 | 6.142 | 941.4 | 16.596 | 2.502 | 0.073 | 25.088 | 0.439 | 79.72 | 0.497 | 64.2 | 0.0 |
| 705.59 | resilimes | 99.08 | 1.84 | 229.6 | 19.714 | 1.744 | 0.076 | 24.616 | 0.867 | 78.986 | 0.457 | 41.8 | 0.0 |
| 705.59 | edd | 99.54 | 0.92 | 472.6 | 8.015 | 1.591 | 0.043 | 24.69 | 0.248 | 75.602 | 0.562 | 52.8 | 0.0 |
| 705.59 | smt_rule | 74.942 | 6.228 | 938.2 | 19.934 | 2.503 | 0.073 | 25.184 | 0.41 | 79.812 | 0.467 | 60.4 | 0.0 |

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 87/87 | 244 | 48 | 0.0 |
| resilimes | 2 | 87/87 | 233 | 37 | 0.0 |
| resilimes | 3 | 83/87 | 229 | 45 | 57.5 |
| resilimes | 4 | 87/87 | 241 | 43 | 0.0 |
| resilimes | 5 | 87/87 | 209 | 48 | 0.0 |
| edd | 1 | 87/87 | 492 | 52 | 0.0 |
| edd | 2 | 87/87 | 467 | 50 | 0.0 |
| edd | 3 | 85/87 | 465 | 56 | 3.9 |
| edd | 4 | 87/87 | 466 | 60 | 0.0 |
| edd | 5 | 87/87 | 461 | 57 | 0.0 |
| fifo | 1 | 40/87 | 901 | 74 | 7944.1 |
| fifo | 2 | 33/87 | 836 | 59 | 26819.8 |
| fifo | 3 | 33/87 | 789 | 61 | 20145.8 |
| fifo | 4 | 53/87 | 803 | 80 | 5445.0 |
| fifo | 5 | 38/87 | 853 | 73 | 10657.4 |
| cr | 1 | 56/87 | 920 | 53 | 1568.2 |
| cr | 2 | 64/87 | 844 | 78 | 742.5 |
| cr | 3 | 75/87 | 919 | 69 | 406.8 |
| cr | 4 | 67/87 | 908 | 71 | 661.7 |
| cr | 5 | 69/87 | 913 | 68 | 659.6 |
| smt_rule | 1 | 56/87 | 945 | 55 | 1836.2 |
| smt_rule | 2 | 64/87 | 935 | 66 | 714.0 |
| smt_rule | 3 | 70/87 | 915 | 59 | 340.7 |
| smt_rule | 4 | 65/87 | 966 | 74 | 546.4 |
| smt_rule | 5 | 71/87 | 946 | 67 | 500.3 |

On-time for ResiliMES and EDD is the same at a 180, 300, 600, 705.59 minute repair.

Seed 1, who paid: no scored non-hot lot finishes later under ResiliMES than under EDD. Mean X-factor on this seed is 1.548 under EDD and 1.694 under ResiliMES. Upstream gates 0. Re-cleans 48. Spread across seeds is the population standard deviation, n=5.

## Appendix: published order book (performance)

On the published dues, a 48-hour horizon, EDD is slightly ahead of ResiliMES on on-time delivery (57.498% against 57.14%). EDD weighted tardiness is 19702.34 minutes against 20098.34. These tables are runtime and knock-on measurements. They are not the claim that earliest-due loses.

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 32/56 | 196 | 35 | 19842.7 |
| resilimes | 2 | 32/56 | 178 | 46 | 20336.2 |
| resilimes | 3 | 32/56 | 185 | 44 | 20107.6 |
| resilimes | 4 | 32/56 | 215 | 44 | 20074.7 |
| resilimes | 5 | 32/56 | 165 | 31 | 20130.5 |
| edd | 1 | 33/56 | 456 | 50 | 19514.6 |
| edd | 2 | 32/56 | 405 | 48 | 19406.0 |
| edd | 3 | 32/56 | 411 | 52 | 19994.3 |
| edd | 4 | 32/56 | 427 | 63 | 19847.6 |
| edd | 5 | 32/56 | 409 | 53 | 19749.2 |
| fifo | 1 | 20/56 | 900 | 75 | 44761.9 |
| fifo | 2 | 19/56 | 844 | 58 | 47018.1 |
| fifo | 3 | 19/56 | 781 | 66 | 45915.1 |
| fifo | 4 | 22/56 | 817 | 79 | 41832.9 |
| fifo | 5 | 21/56 | 838 | 73 | 44668.8 |
| cr | 1 | 32/56 | 446 | 47 | 18623.9 |
| cr | 2 | 32/56 | 397 | 57 | 18972.7 |
| cr | 3 | 32/56 | 383 | 48 | 19559.4 |
| cr | 4 | 32/56 | 376 | 60 | 19256.7 |
| cr | 5 | 32/56 | 372 | 47 | 19370.3 |
| smt_rule | 1 | 32/56 | 416 | 36 | 19125.3 |
| smt_rule | 2 | 32/56 | 382 | 23 | 19590.9 |
| smt_rule | 3 | 32/56 | 371 | 23 | 19203.1 |
| smt_rule | 4 | 32/56 | 370 | 18 | 19367.2 |
| smt_rule | 5 | 32/56 | 381 | 23 | 19418.6 |

### Steady fab (seeded breakdowns, published PM calendar unshifted)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 20098.34 | 27.85 | 79.758 | 79.962 | 187.8 | 0.0 | 0.0 | 217.8 | 0.0002 | 0.0064 | 3.14 |
| edd | 57.498 | 19702.34 | 26.2 | 76.516 | 76.7 | 421.6 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0031 | 1.899 |
| fifo | 36.072 | 44839.36 | 27.306 | 76.712 | 77.074 | 836.0 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0032 | 1.867 |
| cr | 57.14 | 19156.6 | 27.624 | 74.646 | 75.108 | 394.8 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0034 | 2.162 |
| smt_rule | 57.14 | 19341.02 | 27.76 | 79.86 | 80.354 | 384.0 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0046 | 3.12 |

`smt_rule` is `rule_HotLotFIRST` with `rank_HP;rank_RSETUP;rank_CR` (PRIOR at least 20 first, then higher PRIOR, then shorter setup, then lower CR). Implant_128, Implant_132, and Implant_91 use `rule_LSSU` (setup first, then that cascade). The idle-tool loop still picks the tool. `wake_LeastSetupTime` is not implemented. On published dues, smt_rule and ResiliMES tie on on-time at 57.14%. Weighted tardiness is 19341.02 minutes under smt_rule and 20098.34 under ResiliMES. Q-time is 384.0 against 187.8. Re-cleans are 24.6 against 40.0. On X-factor dues at a 600-minute repair, ResiliMES on-time 99.08% beats smt_rule 74.942%. Weighted tardiness is 787.52 minutes under smt_rule and 11.5 under ResiliMES. Q-time is 941.4 against 231.2. Re-cleans are 64.2 against 44.2. These rows were not tuned after the run.

### Lithography breakdown

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 20199.32 | 28.132 | 80.094 | 80.342 | 187.2 | 0.0 | 0.0 | 210.4 | 0.0002 | 0.0063 | 3.063 |
| edd | 57.498 | 19644.52 | 26.11 | 76.484 | 76.694 | 424.6 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0032 | 1.93 |

While `Litho_FE_92-1` is down, other tools in `Litho_FE_92` start 214.6 lots under ResiliMES and 199.6 under EDD (five-seed mean). The family queue peaks at 40.0 lots. The downstream queue peaks at 41.0 under ResiliMES and 41.0 under EDD. On-time uses 56.0 lots due inside the horizon, of which 10.0 are already late at the snapshot. The interactive lithography click is 12 hours and seed 1, and the two policies tie there at 2/19. That click is not this 48-hour table.

### PM avoidance (calendar shifted, durations unchanged)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.14 | 20842.4 | 28.222 | 78.044 | 78.254 | 195.6 | 75.8 | 0.0 | 236.8 | 0.0002 | 0.0061 | 2.909 |
| edd | 57.856 | 20716.14 | 26.744 | 74.842 | 74.946 | 433.6 | 92.4 | 0.0 | 0.0 | 0.0002 | 0.0031 | 1.88 |

### Hot lot

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.14 | 25027.18 | 28.006 | 79.932 | 80.124 | 190.4 | 0.0 | 0.0 | 210.0 | 0.0002 | 0.0064 | 3.057 |
| fifo | 36.072 | 44839.36 | 27.306 | 76.712 | 77.074 | 836.0 | 0.0 | 0.0 | 0.0 | 0.0002 | 0.0032 | 1.849 |

`Init_Lot_10_11` completes 34.0 steps under ResiliMES and 21.6 under FIFO. Promoting it moves the on-time denominator to 57.0 lots (56.0 on the FIFO book).

### Lot transport (published book, with and without)

Every table above moves a lot 1 min to a family in the same STNGRP bay and 3 min to another bay, for every policy. This ablation turns the move off and changes nothing else.

| Policy | On-time with | On-time without | Q-time with | Q-time without | Re-cleans with | Re-cleans without | Cycle h with | Cycle h without |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 57.1% | 57.5% | 187.8 | 192.8 | 40.0 | 38.0 | 27.85 | 27.77 |
| edd | 57.5% | 58.2% | 421.6 | 432.6 | 53.2 | 57.2 | 26.20 | 26.14 |
| fifo | 36.1% | 36.1% | 836.0 | 846.6 | 70.2 | 71.8 | 27.31 | 27.22 |
| cr | 57.1% | 57.5% | 394.8 | 383.8 | 51.8 | 53.0 | 27.62 | 27.62 |
| smt_rule | 57.1% | 57.1% | 384.0 | 395.8 | 24.6 | 26.6 | 27.76 | 27.38 |

## Seeds 9-13 control (regenerated by make smt-bench)

Shipped score only. Seeds 9, 10, 11, 12, 13. X-factor book: due = remaining process times 2.75, 48 hours, `Litho_FE_92-1` down 600 minutes. Published-due book: 48 hours, published dues. PM refusal applies to every policy. This table is recomputed by `make smt-bench`.

| Book | Policy | On time | Q-time | Re-cleans | Per seed |
| --- | --- | ---: | ---: | ---: | --- |
| xfactor | resilimes | 435/435 | 1173 | 230 | 87/87, 87/87, 87/87, 87/87, 87/87 |
| xfactor | edd | 435/435 | 2435 | 265 | 87/87, 87/87, 87/87, 87/87, 87/87 |
| xfactor | fifo | 246/435 | 4349 | 425 | 44/87, 51/87, 59/87, 40/87, 52/87 |
| xfactor | cr | 338/435 | 4374 | 358 | 58/87, 68/87, 76/87, 68/87, 68/87 |
| published | resilimes | 160/280 | 936 | 214 | 32/56, 32/56, 32/56, 32/56, 32/56 |
| published | edd | 160/280 | 2175 | 307 | 32/56, 32/56, 32/56, 32/56, 32/56 |
| published | fifo | 104/280 | 4342 | 402 | 22/56, 21/56, 21/56, 20/56, 20/56 |
| published | cr | 159/280 | 1860 | 269 | 32/56, 32/56, 31/56, 32/56, 32/56 |

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
