# fab-logic-r1: SMT2020 operation logic

Branch `fab-logic-r1`, from `main` at 6b8c868. Full SMT2020 scale only: 1,313 tools, 2,156 lots. Weights, due dates, tool sets, and seeds are unchanged. The one structural change to priority is the tiered key in item 4. Commits are small and one per item.

## What changed

### 1. DIFF batching (c731650)

- Lots batch when their step on the tool family has the same recipe, whatever their route or operation number. The old `try_start` kept only the lots on the head lot's step number. The other chosen lots were dropped from the start without being dispatched; about half the chosen batch lots were lost this way. Each member now keeps and advances its own route step, and every chosen lot starts (`batch_all_started`).
- The batch runs for the longest member's process time.
- Members are ordered by the policy's own rank, so the highest-priority lot leads and fills first.
- Wait rule. At or above BATCHMN the batch starts. Under BATCHMN it waits only while enough same-recipe lots are in process at the feeding step and will finish inside the window. It never waits more than `BATCH_MAX_WAIT_SEC` = 1,800 s after the oldest ready member, or `HOT_BATCH_WAIT_SEC` = 600 s once a hot or VIP lot is ready in the batch. Every under-BATCHMN start logs its reason: `hot_cap`, `max_wait`, or `no_arrivals` (`batch_min`). The extract has no max-wait field, so both caps are ResiliMES defaults.
- Found on the way: the setup time was looked up after the recipe switch, so it was always 0. It is now charged in the process time from the recipe the tool held. This is a large part of the longer step cycle below.

Under-BATCHMN start reasons, published book, seed 1:

| Policy | hot_cap | max_wait | no_arrivals |
| --- | ---: | ---: | ---: |
| resilimes | 7 | 97 | 119 |
| edd | 1 | 73 | 135 |
| fifo | 1 | 53 | 136 |
| cr | 2 | 75 | 110 |
| smt_rule | 5 | 64 | 96 |

### 2. Metrology sampling (27ee7e2)

A step with `StepPercent` p < 100 is sampled. With n = lot number (the trailing number of the lot ID) + STEP, the lot is measured when floor((n + 1) p / 100) > floor(n p / 100). That selects exactly p of every 100 consecutive lot numbers, evenly spaced (p = 10 is every tenth lot), and the STEP offset spreads the measured lots differently on each layer. The rule is `measured()` in `resilimes/smt/fab.py`. An unmeasured lot skips the step with no queue or process time. If the skipped step was the target of an open Q-time window, the window closes without a check (`qtime_skipped`). The lot's step at the snapshot is never skipped. Before this change every lot visited every metrology step.

### 3. Breakdown (5da1454)

- No lot starts on a tool inside a breakdown window (`down_start` stays 0).
- A lot in process when its tool breaks leaves the tool at once. It waits `REWORK_SEC` = 1,800 s (disposition plus strip/clean, a ResiliMES default) and then redoes the whole operation from the family queue on any qualified tool. Before, it resumed on the broken tool after the repair.
- No lot stays on a down tool (`stuck_on_down`).
- A later litho layer whose dedicated scanner is down may start on another scanner of the family and is re-pinned there. Idle siblings are woken at the breakdown.

### 4. Tiered priority (18d91bf)

The ResiliMES policy's weighted `dispatch_score` is replaced by a lexicographic key: `(class tier, late, -PED, setup seconds, slack)`. Class tier is VIP, then hot, then normal, from SMT2020 PRIOR. Then late lots before on-time lots, then Q-time risk, then setup avoidance, then slack. DPI-style terms only order lots inside a tier. The old score had a 60 s slack floor that made every late lot score 61, so a late normal lot tied with or outranked a VIP lot. That cap is gone. This is a structural change, not a weight change.

Mean queue wait per started step, published book, seeds 1-5, minutes:

| Policy | VIP | hot | normal |
| --- | ---: | ---: | ---: |
| resilimes | 5.7 | 5.8 | 55.1 |
| edd | 8.4 | 12.5 | 51.8 |
| fifo | 123.4 | 54.6 | 73.5 |
| cr | 6.0 | 11.5 | 59.5 |
| smt_rule | 6.2 | 6.2 | 60.7 |

Isolated on the same code before sampling (old rank against tiered key, published, seeds 1-5): VIP wait went from 8.6 to 4.8 minutes and hot wait from 5.3 to 4.6 minutes. Normal wait was unchanged, and weighted tardiness rose about 2%.

## Invariants

Thirteen checks: family, route_order, tool_overlap, rework_redo, stuck_on_down, dedication, down_start, pm_overlap, batch, batch_all_started, batch_min, qtime_recount, sampling. New in this branch: rework_redo (replaces resume_tool), stuck_on_down, batch_all_started, batch_min, sampling; dedication allows the re-pin only while the pinned scanner is down. The sweep is 4 books by 5 policies by seeds 1-5. All checks are 0 on all 100 runs. The per-book table is in [invariants.md](invariants.md).

## Old against new

Old is `main` at 6b8c868. New is this branch. Seeds 1-5 means, same books and seeds. On time is lots on time over lots with a due date.

| Book | Policy | On time old → new | OTD % old → new | Weighted tardiness min old → new | Q-time old → new | Re-cleans old → new | Completed routes old → new |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Published dues, 48 h | resilimes | 160/280 → 159/280 | 57.14 → 56.784 | 20063.78 → 19095.04 | 384.4 → 388.8 | 24.4 → 47.0 | 147.4 → 150.6 |
| Published dues, 48 h | edd | 160/280 → 163/280 | 57.14 → 58.214 | 20265.92 → 19032.5 | 448.2 → 432.6 | 40.6 → 57.2 | 159.0 → 161.4 |
| Published dues, 48 h | fifo | 92/280 → 101/280 | 32.858 → 36.07 | 48547.68 → 44534.48 | 749.0 → 846.6 | 107.2 → 71.8 | 73.0 → 97.6 |
| Published dues, 48 h | cr | 158/280 → 161/280 | 56.428 → 57.498 | 20358.76 → 18448.18 | 414.4 → 383.8 | 45.8 → 53.0 | 66.4 → 65.4 |
| Published dues, 48 h | smt_rule | 159/280 → 160/280 | 56.784 → 57.14 | 20356.82 → 18651.16 | 431.4 → 395.8 | 8.2 → 26.6 | 63.8 → 61.2 |
| Lithography breakdown, 48 h | resilimes | 159/280 → 160/280 | 56.784 → 57.14 | 20091.88 → 19126.44 | 385.8 → 387.6 | 25.2 → 46.4 | 147.2 → 151.0 |
| Lithography breakdown, 48 h | edd | 160/280 → 161/280 | 57.14 → 57.498 | 20047.28 → 19027.66 | 442.2 → 433.0 | 40.0 → 54.6 | 158.6 → 161.8 |
| PM-enforced, 48 h | resilimes | 160/280 → 160/280 | 57.14 → 57.14 | 21083.04 → 19952.5 | 370.0 → 367.6 | 26.2 → 47.8 | 146.6 → 148.0 |
| PM-enforced, 48 h | edd | 160/280 → 163/280 | 57.14 → 58.214 | 21727.64 → 19886.58 | 438.2 → 437.6 | 40.2 → 57.4 | 155.8 → 158.4 |
| Hot lot, 48 h | resilimes | 155/285 → 160/285 | 54.388 → 56.14 | 25292.32 → 24070.0 | 386.0 → 394.0 | 26.6 → 50.6 | 148.0 → 151.8 |
| Tight VIP, 24 h | resilimes | 20/105 → 28/105 | 19.05 → 26.666 | 4260.56 → 3548.88 | 178.6 → 170.6 | 11.2 → 3.6 | 25.2 → 25.6 |
| Tight VIP, 24 h | edd | 13/105 → 19/105 | 12.382 → 18.098 | 8014.66 → 7005.34 | 406.6 → 512.4 | 39.4 → 16.4 | 38.6 → 38.2 |
| Tight VIP, 24 h | fifo | 0/105 → 4/105 | 0.0 → 3.808 | 16991.12 → 10614.14 | 411.8 → 511.4 | 38.4 → 15.8 | 37.2 → 37.0 |
| Tight VIP, 24 h | cr | 10/105 → 19/105 | 9.52 → 18.098 | 7839.72 → 6963.74 | 229.2 → 229.4 | 19.4 → 9.8 | 25.4 → 24.0 |
| X-factor, 600 min repair, 48 h | resilimes | 429/435 → 433/435 | 98.62 → 99.54 | 344.42 → 0.76 | 416.2 → 436.8 | 52.4 → 53.4 | 152.0 → 152.4 |
| X-factor, 600 min repair, 48 h | edd | 433/435 → 433/435 | 99.54 → 99.54 | 281.24 → 0.76 | 441.8 → 479.0 | 73.4 → 48.8 | 166.0 → 166.0 |
| X-factor, 600 min repair, 48 h | fifo | 135/435 → 205/435 | 31.032 → 47.126 | 30546.44 → 13969.38 | 782.2 → 844.6 | 118.0 → 71.4 | 74.2 → 99.2 |
| X-factor, 600 min repair, 48 h | cr | 312/435 → 333/435 | 71.724 → 76.552 | 1123.56 → 814.44 | 742.4 → 915.8 | 114.0 → 67.4 | 96.4 → 89.0 |
| X-factor, 600 min repair, 48 h | smt_rule | 320/435 → 338/435 | 73.562 → 77.702 | 1057.52 → 640.96 | 700.0 → 947.2 | 88.0 → 60.0 | 98.2 → 92.0 |

Held-out seeds 9-13, sums:

| Book | Policy | On time old → new | Q-time old → new | Re-cleans old → new |
| --- | --- | --- | --- | --- |
| xfactor | resilimes | 432/435 → 435/435 | 2114 → 2185 | 185 → 280 |
| xfactor | edd | 434/435 → 435/435 | 2261 → 2412 | 403 → 257 |
| xfactor | fifo | 138/435 → 243/435 | 3750 → 4389 | 531 → 414 |
| xfactor | cr | 318/435 → 344/435 | 3774 → 4467 | 574 → 339 |
| published | resilimes | 157/280 → 160/280 | 1917 → 1920 | 112 → 218 |
| published | edd | 160/280 → 160/280 | 2220 → 2170 | 174 → 294 |
| published | fifo | 95/280 → 103/280 | 3560 → 4400 | 505 → 424 |
| published | cr | 155/280 → 161/280 | 2055 → 1869 | 222 → 278 |

Operation counters, published book, seeds 1-5 means. Old dropped about half the chosen batch lots and had no setup, rework, or sampling counters:

| Policy (published, seeds 1-5 mean) | Batch starts | Lots in batches | Lots per batch | Dropped | Setup min | Reworks | Rework lot-min | Re-pins | Skipped metrology steps | Mean step cycle min old → new |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| resilimes | 480.8 | 1631.6 | 3.39 | 0.0 | 51209.4 | 265.2 | 7956.0 | 20.0 | 4750.6 | 108.022 → 121.836 |
| edd | 457.2 | 1505.8 | 3.29 | 0.0 | 69880.6 | 242.2 | 7266.0 | 14.8 | 4328.4 | 113.382 → 120.316 |
| fifo | 454.6 | 1494.6 | 3.29 | 0.0 | 69688.4 | 242.0 | 7260.0 | 16.0 | 4540.4 | 136.512 → 142.892 |
| cr | 457.0 | 1606.8 | 3.52 | 0.0 | 71112.8 | 247.4 | 7422.0 | 19.4 | 4514.6 | 118.306 → 128.256 |
| smt_rule | 477.4 | 1755.2 | 3.68 | 0.0 | 43274.0 | 259.0 | 7770.0 | 27.4 | 4864.4 | 123.066 → 128.172 |

### Honest reading

- **EDD beats ResiliMES on the published book.** On-time is 163/280 (58.21%) for EDD against 159/280 (56.78%) for ResiliMES. CR (161) and smt_rule (160) are also ahead of ResiliMES. EDD's weighted tardiness is also slightly lower (19,032.5 against 19,095.0 minutes). Before this branch ResiliMES and EDD tied at 160.
- On PM-enforced, EDD is ahead by 3 lots (163 against 160). On litho breakdown, EDD is ahead by 1.
- ResiliMES wins the tight VIP book clearly: 28/105 against 19/105 for EDD and CR.
- On X-factor (600-minute repair), ResiliMES and EDD tie at 433/435 (99.54%). ResiliMES has fewer Q-time violations (436.8 against 479.0) but more re-cleans (53.4 against 48.8). Before, ResiliMES had fewer re-cleans; that is reversed.
- ResiliMES re-cleans on the published book roughly doubled (24.4 to 47.0). The tiered key puts class before Q-time risk, so a VIP or hot lot can now go first while a normal lot's Q-time window runs out.
- Every policy's step cycle is longer, mainly because setup time is now real and lots in process at a breakdown pay the rework hold.

## Pull against push

The simulator is closed: a fixed WIP snapshot is dispatched by pull (a tool takes the next lot when it frees up). To test release control we ran three arms on the published book, seeds 1-5 (scratch experiment, not in the repo). The table is on-time over lots due inside the horizon:

| Policy | Closed pull (current) | Push: release the `order.txt` lots at their release times | CONWIP: one released lot in for each lot that finishes its route |
| --- | ---: | ---: | ---: |
| resilimes | 56.78% | 57.14% | 57.14% |
| edd | 58.21% | 58.21% | 58.21% |

The differences are at most one lot, which is noise. In a 48-hour window the snapshot WIP dominates: released lots start at step 1, their dues fall after the horizon, and they compete with snapshot lots only at early steps. Recommendation: keep pull dispatch. Release control (CONWIP or a WIP cap) matters only in an open system over several weeks, where WIP can grow; that is the first unmodelled item below.

## Unmodelled items

| Item | In the extract | Effect on these KPIs | Effort |
| --- | --- | --- | --- |
| Open system, multi-week horizon with `order.txt` releases | release table yes | high: throughput, cycle time, WIP growth, and release policy are not measurable in 48 h closed | medium |
| Operators and load/unload | no columns | high for the human-like operation view; gates starts by people | medium |
| Transport between bays (AMHS) | no columns | medium: a delay per step; contention needs a vehicle model | medium to high |
| Random process-time noise | no | medium: tests robustness of every policy | low |
| Cascading or overlap on track and litho | no | medium on litho throughput | high |
| Staggered PM planning | PM calendar yes | low to medium; a planning lever, not dispatch | medium |
| Minimum run before a setup change (campaigns) | no | low to medium on implant | low |

Recommended next, one or two:

1. **Open system with a multi-week horizon.** Release `order.txt` lots, run two to four weeks, report throughput and cycle time. This is the only way to answer pull against push with real evidence.
2. **Operators with load and unload.** An operator pool per bay that must load and unload each start. It brings the simulator closer to how a fab floor runs and gives the console a person-level view. Values would be documented ResiliMES assumptions, since SMT2020 has no operator data.

## UI and operation-logic suggestions

Not built in this branch. No zh/ja wording was changed.

- A tool-first operator screen per bay: for each tool, its state (running, idle, down, PM), the lot on it, and the next three lots with one short reason each ("VIP", "late", "same recipe, no setup").
- A batch-forming card: members, wafers against BATCHMN, the wait reason, and a countdown to the cap ("waiting for 2 lots from step 41, starts by 14:32 at the latest").
- A breakdown card: which lot was interrupted, that it went to rework, when the hold ends, and which tool picked it up.
- Sampling shown plainly in the lot timeline: "skipped overlay measure (10% sample, not selected)".
- Fewer numbers on the first screen: lead with on-time and at-risk VIP/hot lots, and move weighted tardiness and counters to a details panel.
- An event log in plain sentences, in operator order, instead of raw event names.

## Run time and worker count

One full-scale run peaks near 90 MB RSS and about 3 s. The box has 8 cores and about 4 GB of memory, with about 3.4 GB free. With 6 worker processes the benchmark finished in 93 s with no swap; the invariant sweep, which records full traces, ran on 4 workers in 86 s. Defaults are `RESILIMES_BENCH_WORKERS=6` and `RESILIMES_SWEEP_WORKERS=4`. Set either to 1 for a serial run. Wall-clock fields inside a run read a little higher under a busy pool.
