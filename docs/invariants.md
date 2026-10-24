# SMT simulator invariants and the stale-queue fix

## What was wrong

`try_start` cleared `waiting[lot]` for a started lot but left it in `queues[fam]`. When the step finished, `finish_lot` set the lot waiting again for its next step, in another family. The stale entry in the old family's queue then looked live again, so an idle tool of the old family could start the lot's next step. The guard in `try_start` compared only the step index, not the family. The rule was the same for every policy, so every policy in the benchmark (ResiliMES, EDD, FIFO, CR, `smt_rule`) was affected.

## The fix

All three changes are in `resilimes/smt/simulate.py`:

- `try_start` removes the lots it started from `queues[fam]`.
- `live(fam)` keeps a lot only when it is waiting and the family of its current step is `fam` (`step_family`).
- The per-lot guard in `try_start` also checks `step_family(lot) == fam`.

Weights, due dates, tool sets, and seeds are unchanged. This is a correctness fix, not tuning.

## The checker

`resilimes/smt/invariants.py` replays the events recorded by `run_policy(..., record=True)`. It is a check on the simulator's own trace, not a second simulator. Every start is checked for:

| Check | Meaning |
| --- | --- |
| `family` | the tool belongs to the station family of the lot's current step |
| `route_order` | a lot starts only its next step, once, and never while already in process |
| `tool_overlap` | a tool starts a piece only when it holds nothing |
| `resume_tool` | an interrupted lot resumes on the tool that held it |
| `dedication` | a later litho layer runs on the scanner of its first layer |
| `down_start` | no start inside a breakdown window |
| `pm_overlap` | no processing window crosses a PM window |
| `batch` | a multi-lot start is a batch step, one recipe, within capacity |
| `qtime_recount` | Q-time violations recounted from the trace (strict `>`) match the reported count |

Run it on the full fab:

```
make smt-invariants        # python -m resilimes.smt.invariant_sweep
```

It runs the published, X-factor (600-minute repair), PM-enforced, and tight VIP books for seeds 1-5 and all five policies. It prints one line per run and a totals table, and exits 1 if any check fails. `tests/test_smt_invariants.py` has a regression test for the stale queue on every policy, a full-fab trace test, and tests that the checker flags wrong-family, down, PM, and Q-time cases.

## Violation counts, seeds 1-5 summed

Only `family` was ever nonzero. The other eight checks were 0 before and after on every run. Before the fix, `qtime_recount` also matched in every run.

| Book | Policy | `family` before | `family` after | Starts after |
| --- | --- | ---: | ---: | ---: |
| published | resilimes | 1,762 | 0 | 177,490 |
| published | edd | 1,905 | 0 | 185,541 |
| published | fifo | 795 | 0 | 187,018 |
| published | cr | 1,516 | 0 | 182,891 |
| published | smt_rule | 1,819 | 0 | 185,997 |
| xfactor_eta600 | resilimes | 1,393 | 0 | 181,675 |
| xfactor_eta600 | edd | 1,453 | 0 | 185,991 |
| xfactor_eta600 | fifo | 777 | 0 | 187,247 |
| xfactor_eta600 | cr | 737 | 0 | 182,750 |
| xfactor_eta600 | smt_rule | 829 | 0 | 184,466 |
| pm_enforced | resilimes | 1,676 | 0 | 174,790 |
| pm_enforced | edd | 1,760 | 0 | 181,615 |
| pm_enforced | fifo | 795 | 0 | 183,380 |
| pm_enforced | cr | 1,585 | 0 | 179,795 |
| pm_enforced | smt_rule | 1,718 | 0 | 183,385 |
| tight_vip | resilimes | 500 | 0 | 94,679 |
| tight_vip | edd | 230 | 0 | 97,137 |
| tight_vip | fifo | 304 | 0 | 97,262 |
| tight_vip | cr | 498 | 0 | 95,271 |
| tight_vip | smt_rule | 504 | 0 | 95,877 |

Per seed, published book, `family` before the fix: ResiliMES 350, 381, 319, 404, 308. EDD 389, 395, 357, 380, 384. FIFO 171, 148, 143, 182, 151. CR 313, 275, 277, 362, 289. `smt_rule` 363, 395, 323, 387, 351.

## Old vs new metrics, seeds 1-5

Old is the simulator before the fix: the `benchmark.json` checked in at commit 6ec1148, the parent of this fix series. New is after the fix, same seeds and books. Means are five-seed means. Q-time and re-cleans are per-run means.

| Book | Policy | On time, pooled (per seed) old | new | OTD % old → new | Weighted tardiness min old → new | Q-time old → new | Re-cleans old → new |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X-factor, 600 min repair, 48 h | resilimes | 424/435 (87, 83, 86, 87, 81) | 429/435 (86, 83, 86, 87, 87) | 97.47 → 98.62 | 458.16 → 344.42 | 430.0 → 416.2 | 38.0 → 52.4 |
| X-factor, 600 min repair, 48 h | edd | 433/435 (87, 86, 86, 87, 87) | 433/435 (87, 86, 86, 87, 87) | 99.54 → 99.54 | 325.84 → 281.24 | 451.6 → 441.8 | 55.6 → 73.4 |
| X-factor, 600 min repair, 48 h | fifo | 90/435 (16, 16, 15, 27, 16) | 135/435 (27, 27, 26, 27, 28) | 20.688 → 31.032 | 42443.0 → 30546.44 | 765.2 → 782.2 | 99.6 → 118.0 |
| X-factor, 600 min repair, 48 h | cr | 312/435 (57, 63, 68, 62, 62) | 312/435 (57, 60, 72, 61, 62) | 71.722 → 71.724 | 1205.14 → 1123.56 | 718.8 → 742.4 | 126.6 → 114.0 |
| X-factor, 600 min repair, 48 h | smt_rule | 305/435 (42, 60, 71, 66, 66) | 320/435 (55, 64, 72, 67, 62) | 70.116 → 73.562 | 2124.84 → 1057.52 | 670.4 → 700.0 | 70.2 → 88.0 |
| Published dues, 48 h | resilimes | 158/280 (31, 31, 32, 32, 32) | 160/280 (32, 32, 32, 32, 32) | 56.428 → 57.14 | 21988.14 → 20063.78 | 386.0 → 384.4 | 25.2 → 24.4 |
| Published dues, 48 h | edd | 159/280 (31, 32, 32, 32, 32) | 160/280 (32, 32, 32, 32, 32) | 56.784 → 57.14 | 21525.68 → 20265.92 | 414.8 → 448.2 | 44.4 → 40.6 |
| Published dues, 48 h | fifo | 74/280 (16, 15, 14, 15, 14) | 92/280 (19, 18, 17, 19, 19) | 26.43 → 32.858 | 52672.8 → 48547.68 | 749.6 → 749.0 | 91.2 → 107.2 |
| Published dues, 48 h | cr | 95/280 (18, 22, 20, 20, 15) | 158/280 (32, 31, 32, 31, 32) | 33.928 → 56.428 | 22923.68 → 20358.76 | 315.4 → 414.4 | 14.8 → 45.8 |
| Published dues, 48 h | smt_rule | 79/280 (19, 14, 13, 16, 17) | 159/280 (32, 31, 32, 32, 32) | 28.214 → 56.784 | 24232.66 → 20356.82 | 348.8 → 431.4 | 25.0 → 8.2 |
| Lithography breakdown, 48 h | resilimes | 158/280 (31, 31, 32, 32, 32) | 159/280 (32, 32, 32, 32, 31) | 56.428 → 56.784 | 21844.54 → 20091.88 | 395.6 → 385.8 | 27.0 → 25.2 |
| Lithography breakdown, 48 h | edd | 159/280 (32, 32, 32, 32, 31) | 160/280 (32, 32, 32, 32, 32) | 56.784 → 57.14 | 21436.12 → 20047.28 | 419.4 → 442.2 | 41.0 → 40.0 |
| PM-enforced (calendar shifted), 48 h | resilimes | 154/280 (32, 30, 31, 31, 30) | 160/280 (32, 32, 32, 32, 32) | 55.0 → 57.14 | 22795.84 → 21083.04 | 367.0 → 370.0 | 26.0 → 26.2 |
| PM-enforced (calendar shifted), 48 h | edd | 156/280 (32, 31, 31, 31, 31) | 160/280 (32, 32, 32, 32, 32) | 55.716 → 57.14 | 22564.8 → 21727.64 | 439.8 → 438.2 | 31.6 → 40.2 |
| Hot lot, 48 h | resilimes | 157/285 (31, 31, 32, 32, 31) | 155/285 (29, 32, 32, 31, 31) | 55.09 → 54.388 | 27588.48 → 25292.32 | 389.2 → 386.0 | 24.8 → 26.6 |
| Hot lot, 48 h | fifo | 74/280 (16, 15, 14, 15, 14) | 92/280 (19, 18, 17, 19, 19) | 26.43 → 32.858 | 52672.8 → 48547.68 | 749.6 → 749.0 | 91.2 → 107.2 |
| Tight VIP, 24 h | resilimes | 20/105 (4, 4, 4, 4, 4) | 20/105 (4, 4, 4, 4, 4) | 19.05 → 19.05 | 4329.38 → 4260.56 | 176.0 → 178.6 | 9.8 → 11.2 |
| Tight VIP, 24 h | edd | 13/105 (3, 3, 2, 2, 3) | 13/105 (3, 3, 2, 2, 3) | 12.382 → 12.382 | 7985.74 → 8014.66 | 413.8 → 406.6 | 38.4 → 39.4 |
| Tight VIP, 24 h | fifo | 0/105 (0, 0, 0, 0, 0) | 0/105 (0, 0, 0, 0, 0) | 0.0 → 0.0 | 19042.4 → 16991.12 | 421.4 → 411.8 | 38.8 → 38.4 |
| Tight VIP, 24 h | cr | 10/105 (2, 2, 2, 2, 2) | 10/105 (2, 2, 2, 2, 2) | 9.52 → 9.52 | 10372.78 → 7839.72 | 223.2 → 229.2 | 15.2 → 19.4 |

Seeds 9-13 control, sums over five seeds:

| Book | Policy | On time old → new | Q-time old → new | Re-cleans old → new |
| --- | --- | --- | --- | --- |
| xfactor | resilimes | 407/435 → 432/435 | 2223 → 2114 | 223 → 185 |
| xfactor | edd | 434/435 → 434/435 | 2447 → 2261 | 283 → 403 |
| xfactor | fifo | 89/435 → 138/435 | 3756 → 3750 | 455 → 531 |
| xfactor | cr | 301/435 → 318/435 | 3577 → 3774 | 557 → 574 |
| published | resilimes | 156/280 → 157/280 | 1821 → 1917 | 131 → 112 |
| published | edd | 158/280 → 160/280 | 1952 → 2220 | 206 → 174 |
| published | fifo | 72/280 → 95/280 | 3647 → 3560 | 444 → 505 |
| published | cr | 82/280 → 155/280 | 1602 → 2055 | 68 → 222 |

## What changed in the story

- Published dues: EDD was slightly ahead (159 vs 158 of 280). After the fix the two tie at 160/280, and ResiliMES is slightly ahead on weighted tardiness.
- X-factor dues: the EDD lead shrinks from 9 to 4 of 435 pooled lots. ResiliMES re-cleans rose (38 to 52.4) but stay below EDD (73.4). On the console click (seed 1), EDD is now 87/87 and ResiliMES 86/87.
- Tight VIP: on-time is unchanged on every policy. `Init_Lot_2_23` is still the save (5.45 h late under EDD).
- FIFO, CR, and `smt_rule` gain the most, because the stale queue had let tools start lots of other families in arrival order. `smt_rule` on published dues goes from 28.2% to 56.8% on-time.
- The seeds 9-13 arm decisions (expose due in `dpi()`, dry-etch gate, slack exception) in [SMT2020_SCALE.md](SMT2020_SCALE.md) were measured before the fix and are labeled a pre-fix lab note. They were not rerun.
