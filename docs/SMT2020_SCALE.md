# SMT2020 full-fab measurements

Public industry benchmark (SMT2020). Source: Kopp, Hassoun, Kalir, and Mönch, IEEE Trans. Semicond. Manuf. 33(4), 2020, doi 10.1109/TSM.2020.3001933. PySCFabSim-release commit `0dbff6a`, directory `datasets/SMT2020_LVHM`. This is not a recording from a production fab.

Fab: 106 station families, 1313 tools, 102 `Litho_*` tools (82 expose scanners plus 20 `Litho_REG`), 10 products, 2156 initial WIP lots, 12 station groups. `Delay_32` is included (400 tools, 147 route steps).

## The trade

X-factor dues, 48 hours, 87 lots. On-time is the same at a 180, 300, 600, or 705.59 minute repair. ResiliMES 87/87, 83/87, 86/87, 87/87, 81/87 (424/435 pooled), mean 97.47%. EDD 87/87, 86/87, 86/87, 87/87, 87/87 (433/435 pooled), mean 99.54%. FIFO mean 20.688%. CR mean 71.722%. ResiliMES beats FIFO and CR by a wide margin. Versus EDD it gives up about 2 of 87 lots, with fewer re-cleans (38 vs 56; means 38 and 55.6) and fewer Q-time violations (430 vs 451.6). Seed 2 misses are three lots at `Diffusion_BE_123`. Seed 5 misses are five lots at `Dielectric_BE_28` (`Init_Lot_2_7`, `Init_Lot_2_8`, `Init_Lot_2_13`, `Init_Lot_2_23`, `Init_Lot_8_20`) plus `Init_Lot_1_10` at `WE_BE_14`. `Init_Lot_2_23` is on time under EDD and late under ResiliMES on seeds 5 and 6 (2.67 h and 4.26 h). Seed 6 is outside the five-seed means.

Published dues, 48 hours, 56 lots. ResiliMES 31/56, 31/56, 32/56, 32/56, 32/56 (158/280 pooled), mean 56.428%. EDD 31/56, 32/56, 32/56, 32/56, 32/56 (159/280 pooled), mean 56.784%. EDD is slightly ahead. Seed 1 ties at 31/56.

Tight VIP dues rewrites the dues for the stress test. It is not the published order book. Denominator 21 lots. ResiliMES 4/21, 4/21, 4/21, 4/21, 4/21 (20/105 pooled). EDD 3/21, 3/21, 2/21, 2/21, 3/21 (13/105 pooled). FIFO 0/21, 0/21, 0/21, 0/21, 0/21 (0/105 pooled). CR 2/21, 2/21, 2/21, 2/21, 2/21 (10/105 pooled). Seed 1 weighted tardiness is 7679.4 under EDD and 4043.8 under ResiliMES. The 12-hour lithography click is a seed-1 tie, 2/19. It is not the 48-hour lithography study in the appendix.

The tight VIP table is 24 hours. The appendix is 48 hours from 2018-01-01 00:00 UTC. Seeds: 1, 2, 3, 4, 5. Each seed draws exponential MTTF/MTTR from `downcal.txt`, one clock per tool. The same draw is shared across policies.

Macro APS (backward due, then earliest free expose scanner, 30625 scanner steps): **286.0 ms**.

Dispatch latency is the time to choose the next lot for one idle tool, look-ahead 24 (8 when that family's queue exceeds two lots per tool). The headline p50/p95 includes empty wakes. Nonempty-queue decisions on the X-factor ResiliMES runs, seeds 1-5, are p50 0.0090-0.0107 ms and p95 0.244-0.250 ms. It is not the full simulation time. Simulation time is the whole 48-hour run.

The WIP column is a candidate cap, not a replan. `choose()` keeps 8 lots instead of 24 after a family exceeds max(8, two lots per tool), and also keeps a lot whose slack is at or under 7200 seconds. The adjacent Wet_Etch look-ahead fired 0 times on these books. `macro_aps_ms` does not feed `dpi()`. `rank()` calls `dispatch_score`. A down tool queues the end of every covering window, so a forced outage that overlaps an MTTF draw still releases at the later end. Seeds 1-5 on-time on the books below match the figures in this file.

On-time percent uses lots whose due is at or before the horizon. A lot is on time only if its route finishes at or before the due. Lots already due at the snapshot stay in the denominator. Weighted tardiness is lot value times minutes late. An open lot is censored at the horizon. Cycle time is the mean completion time of lots that finish the route. X-factor is that completion time divided by the lot's remaining raw process time at the snapshot. Litho utilization is busy time on the 102 `Litho_*` tools divided by tools times horizon. Scanner utilization uses the 82 expose tools. Q-time violations are published CQT misses. PM avoided is a ResiliMES decision that refused at least one lot because the process would cross a PM. PM overlaps are baseline starts that run across a PM.

The weekly PM FOA on the focus family is outside a 48-hour window (about 7 days). The steady and litho studies therefore show zero PM events. The PM study subtracts one offset from every day-based calendar so `Litho_FE_92_WK` opens at 2 hours. Duration and interval stay published. One FOA is stored per family, so every tool in the family shares that window.

Lithography breakdown holds `Litho_FE_92-1` (`Litho_FE_92`, largest expose family) for the published lithography MTTR of 705.59 minutes, on top of the seeded breakdowns.

Hot lot `Init_Lot_10_11` is the lowest lot id among normal-priority lots sitting four steps before an expose scanner. The ResiliMES book raises it to VIP with a due 12 hours from the snapshot. FIFO keeps the published priority.

## Tight VIP dues (constructed, 24 hours)

The published dues do not make earliest-due lose on on-time delivery. This book keeps the routes, process times, setups, and CQT limits, and replaces the dues used for scoring. Eight lots waiting at `Dielectric_BE_28` with a later CQT become VIP and are due at 8 hours. The other lots in that queue stay normal and are due at 7.2 hours, so earliest-due serves them first. Every other lot still moves through the fab and is outside the scored horizon. `Dielectric_BE_28-1` is down for the published dielectric MTTR of 604.8 minutes. The family has three tools. Horizon is 24 hours, five seeds.

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 19.05 | 4329.38 | 9.738 | 77.69 | 72.514 | 176 | 0 | 0 | 134.8 | 0.0002 | 0.006 | 1.467 |
| edd | 12.382 | 7985.74 | 11.654 | 82.008 | 77.862 | 413.8 | 0 | 0 | 0 | 0.0002 | 0.0028 | 0.754 |
| fifo | 0.0 | 19042.4 | 14.614 | 82.166 | 78.058 | 421.4 | 0 | 0 | 0 | 0.0002 | 0.0027 | 0.685 |
| cr | 9.52 | 10372.78 | 10.87 | 79.464 | 74.708 | 223.2 | 0 | 0 | 0 | 0.0002 | 0.0029 | 0.859 |

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 4/21 | 187 | 7 | 4043.8 |
| resilimes | 2 | 4/21 | 182 | 14 | 4125.8 |
| resilimes | 3 | 4/21 | 184 | 5 | 4585.0 |
| resilimes | 4 | 4/21 | 164 | 7 | 4337.6 |
| resilimes | 5 | 4/21 | 163 | 16 | 4554.7 |
| edd | 1 | 3/21 | 415 | 39 | 7679.4 |
| edd | 2 | 3/21 | 437 | 42 | 7627.1 |
| edd | 3 | 2/21 | 424 | 40 | 8171.2 |
| edd | 4 | 2/21 | 384 | 34 | 7719.7 |
| edd | 5 | 3/21 | 409 | 37 | 8731.3 |
| fifo | 1 | 0/21 | 422 | 39 | 16237.9 |
| fifo | 2 | 0/21 | 438 | 40 | 15565.3 |
| fifo | 3 | 0/21 | 426 | 38 | 15417.4 |
| fifo | 4 | 0/21 | 395 | 40 | 16725.4 |
| fifo | 5 | 0/21 | 426 | 37 | 31266.0 |
| cr | 1 | 2/21 | 233 | 3 | 7927.0 |
| cr | 2 | 2/21 | 217 | 26 | 8010.4 |
| cr | 3 | 2/21 | 241 | 19 | 8257.9 |
| cr | 4 | 2/21 | 205 | 17 | 7754.2 |
| cr | 5 | 2/21 | 220 | 11 | 19914.4 |

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

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 87/87 | 418 | 31 | 0.0 |
| resilimes | 2 | 83/87 | 413 | 35 | 873.5 |
| resilimes | 3 | 86/87 | 428 | 53 | 778.5 |
| resilimes | 4 | 87/87 | 448 | 25 | 0.0 |
| resilimes | 5 | 81/87 | 443 | 46 | 638.8 |
| edd | 1 | 87/87 | 428 | 24 | 0.0 |
| edd | 2 | 86/87 | 433 | 65 | 850.8 |
| edd | 3 | 86/87 | 441 | 66 | 778.4 |
| edd | 4 | 87/87 | 478 | 62 | 0.0 |
| edd | 5 | 87/87 | 478 | 61 | 0.0 |
| fifo | 1 | 16/87 | 808 | 101 | 44750.9 |
| fifo | 2 | 16/87 | 773 | 104 | 47701.8 |
| fifo | 3 | 15/87 | 681 | 97 | 48776.8 |
| fifo | 4 | 27/87 | 749 | 103 | 26350.3 |
| fifo | 5 | 16/87 | 815 | 93 | 44635.2 |
| cr | 1 | 57/87 | 726 | 107 | 1748.9 |
| cr | 2 | 63/87 | 700 | 119 | 1092.4 |
| cr | 3 | 68/87 | 705 | 116 | 1276.5 |
| cr | 4 | 62/87 | 718 | 122 | 977.6 |
| cr | 5 | 62/87 | 745 | 169 | 930.3 |

On-time at 180, 300, 600, and 705.59 minutes is the same row for ResiliMES and for EDD. Seed 2 misses are three lots at `Diffusion_BE_123`. Seed 5 misses are `Init_Lot_2_7`, `Init_Lot_2_8`, `Init_Lot_2_13`, `Init_Lot_2_23`, and `Init_Lot_8_20` at `Dielectric_BE_28`, plus `Init_Lot_1_10` at `WE_BE_14`. `Init_Lot_2_23` is on time under EDD and late under ResiliMES on seeds 5 and 6 (2.67 h and 4.26 h). Seed 6 is outside the five-seed means.

Seed 1, who paid: no scored non-hot lot finishes later under ResiliMES than under EDD. Mean X-factor on this seed is 1.665 under EDD and 1.64 under ResiliMES. Upstream gates 0. Re-cleans 31. Spread across seeds is the sample standard deviation, n=5.

## Appendix: published order book (performance)

On the published dues, a 48-hour horizon, EDD is slightly ahead of ResiliMES on on-time delivery (56.784% against 56.428%). EDD weighted tardiness is 21525.68 minutes against 21988.14. These tables are runtime and knock-on measurements. They are not the claim that earliest-due loses.

Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.

| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |
| --- | ---: | ---: | ---: | ---: | ---: |
| resilimes | 1 | 31/56 | 384 | 20 | 21791.6 |
| resilimes | 2 | 31/56 | 396 | 23 | 22465.0 |
| resilimes | 3 | 32/56 | 369 | 28 | 21981.7 |
| resilimes | 4 | 32/56 | 386 | 24 | 21868.4 |
| resilimes | 5 | 32/56 | 395 | 31 | 21834.0 |
| edd | 1 | 31/56 | 426 | 42 | 20816.6 |
| edd | 2 | 32/56 | 401 | 45 | 20672.9 |
| edd | 3 | 32/56 | 435 | 42 | 21936.5 |
| edd | 4 | 32/56 | 391 | 39 | 22784.5 |
| edd | 5 | 32/56 | 421 | 54 | 21417.9 |
| fifo | 1 | 16/56 | 778 | 86 | 52447.6 |
| fifo | 2 | 15/56 | 740 | 111 | 52697.9 |
| fifo | 3 | 14/56 | 739 | 107 | 54159.0 |
| fifo | 4 | 15/56 | 723 | 72 | 51894.2 |
| fifo | 5 | 14/56 | 768 | 80 | 52165.3 |
| cr | 1 | 18/56 | 295 | 11 | 24812.0 |
| cr | 2 | 22/56 | 322 | 14 | 21676.4 |
| cr | 3 | 20/56 | 336 | 22 | 21987.7 |
| cr | 4 | 20/56 | 310 | 11 | 21553.7 |
| cr | 5 | 15/56 | 314 | 16 | 24588.6 |

### Steady fab (seeded breakdowns, published PM calendar unshifted)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.428 | 21988.14 | 25.876 | 76.208 | 71.63 | 386 | 0 | 0 | 156.2 | 0.0002 | 0.0058 | 2.296 |
| edd | 56.784 | 21525.68 | 26.068 | 79.12 | 74.508 | 414.8 | 0 | 0 | 0 | 0.0002 | 0.0027 | 1.268 |
| fifo | 26.43 | 52672.8 | 27.018 | 76.22 | 70.632 | 749.6 | 0 | 0 | 0 | 0.0002 | 0.0025 | 1.29 |
| cr | 33.928 | 22923.68 | 29.412 | 73.538 | 67.606 | 315.4 | 0 | 0 | 0 | 0.0002 | 0.0027 | 1.384 |

### Lithography breakdown

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 56.428 | 21844.54 | 26.282 | 75.886 | 71.306 | 395.6 | 0 | 0 | 155.8 | 0.0002 | 0.0057 | 2.283 |
| edd | 56.784 | 21436.12 | 25.61 | 79.07 | 74.514 | 419.4 | 0 | 0 | 0 | 0.0002 | 0.0027 | 1.262 |

While `Litho_FE_92-1` is down, other tools in `Litho_FE_92` start 250.4 lots under ResiliMES and 250.8 under EDD (five-seed mean). The family queue peaks at 40 lots. The downstream queue peaks at 375.4 under ResiliMES and 486.2 under EDD. On-time uses 56 lots due inside the horizon, of which 10 are already late at the snapshot. The interactive lithography click is 12 hours and seed 1, and the two policies tie there at 2/19. That click is not this 48-hour table.

### PM avoidance (calendar shifted, durations unchanged)

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 55.0 | 22795.84 | 26.85 | 74.39 | 69.902 | 367 | 54.2 | 0 | 154.6 | 0.0002 | 0.0057 | 2.286 |
| edd | 56.784 | 21525.68 | 26.068 | 79.12 | 74.508 | 414.8 | 0 | 495.6 | 0 | 0.0002 | 0.0027 | 1.267 |

### Hot lot

| Policy | OTD % | Weighted tardiness min | Cycle h | Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| resilimes | 55.09 | 27588.48 | 26.628 | 76.602 | 71.934 | 389.2 | 0 | 0 | 151.2 | 0.0002 | 0.0058 | 2.331 |
| fifo | 26.43 | 52672.8 | 27.018 | 76.22 | 70.632 | 749.6 | 0 | 0 | 0 | 0.0002 | 0.0024 | 1.282 |

`Init_Lot_10_11` completes 37 steps under ResiliMES and 23 under FIFO. Promoting it moves the on-time denominator to 57 lots (56 on the FIFO book).

## Seeds 9-13 (one run, then keep or revert)

Registered before the run. Seeds 9, 10, 11, 12, 13. X-factor book: due = remaining process times 2.75, 48 hours, 87 lots due, `Litho_FE_92-1` down 600 minutes. Published-due book: 48 hours, 56 lots due. Policies: ResiliMES, EDD, FIFO, CR. Slack threshold 7200 seconds. Keep a ResiliMES arm only when, on both books, the on-time lot count is not lower and re-cleans are not higher and Q-time violations are not higher than the control. EDD, FIFO, and CR matched the control on every arm.

Control is the shipped score: lot due inside `dpi()`, the Wet_Etch gate, and the candidate cap. Sums are five seeds.

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
