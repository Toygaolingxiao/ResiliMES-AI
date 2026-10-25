# Hard Q-time (default on)

Q-time compliance comes first. A schedule with an **avoidable** Q-time
violation is infeasible: it is discarded, not compared on on-time or
throughput. A configuration is a candidate only with zero avoidable
violations. Q-time-blind rules (EDD, FIFO, CR, `smt_rule`) are shown only as
an industry reference row with their avoidable-violation count, never as a
target to beat.

Hard Q-time gating is **on by default** for ResiliMES with the planning layer
(`default_hard_qtime` in `resilimes/smt/simulate.py`). `RESILIMES_HARD_QTIME=0`
or `make_sim(..., hard_qtime=False)` turns it off for experiments only;
`RESILIMES_HARD_QTIME=1` forces it on for any policy. Only dataset values are
used: CQT limits, process times, batch sizes and recipes, transport and the PM
calendar. No weights, due dates or seeds were tuned. Code:
`resilimes/smt/hard_qtime.py`, hooks in `resilimes/smt/simulate.py`, study in
`resilimes/smt/hard_qtime_study.py`.

## Mechanism

1. **Whole-segment gate.** A lot may start a CQT origin only if every family
   of its CQT segment (each measured intermediate step and the target) can
   still start it in time. Per family, the committed load plus the
   candidate's is checked earliest-deadline-first twice: a fluid check, then a
   whole-run check where a tool is held for a full run, a batch run is shared
   only by `batch_min` lots of the **same recipe**, and a run never starts
   inside a PM. Only the current down state is used, never future breakdowns.
   Members of one batch start are admitted jointly (`admit_batch`). Missed
   and re-cleaned lots back at an origin are gated like any other lot (they
   stay expedited, so they go first once feasible).
2. **Miss classification** (`miss_class`, `RunResult.qtime_miss_class`):
   * `unavoidable_disruption`: target down or in PM while the lot waited,
     breakdown rework, transport.
   * `unavoidable_breakdown`: a breakdown started on the lot's current family
     or its target family after the origin start (the admission) and before
     the deadline. The gate cannot see a future breakdown.
   * `avoidable`: any other miss (queueing, upstream, batch fill).
   Windows already open in the t=0 WIP are counted separately as inherited.
3. **Expedite, not exclude.** A lot that misses its window (any class,
   inherited included) is flagged as a hot lot until its target step starts.
   Inside its class tier the order is: in-window lots that lose the window
   unless they start now, other in-window lots by slack, missed lots (oldest
   miss first), then everyone else. A missed lot never takes the capacity a
   still-feasible window was admitted against. Count and recovery time
   (miss to target start) are reported.

## Study

`python -m resilimes.smt.hard_qtime_study OUT.json`, report with `--report`.
Published book, seeds 1-3, 7 days, closed fab. Totals over 3 seeds unless
"/run".

### Gate fix: misses before and after (planning + hard, seeds 1-3, 7 d)

"Before" is the earlier gate (fluid check only, recipe-blind batch sharing,
missed / re-cleaned lots not re-gated). "After" is this code.

| Miss class (3 seeds) | Before | After |
|---|---:|---:|
| avoidable: admitted, queueing at target | 302 | 92 |
| avoidable: admitted, still upstream | 17 | 19 |
| avoidable: re-cleaned lot restarted ungated | 15 | 0 |
| **avoidable total** | **334** | **111** |
| unavoidable: breakdown after admission | 217 | 46 |
| unavoidable: target down / PM, transport, rework | 96 | 19 |
| completed / run | 459.3 | 486.7 |
| expedited lots | 905 | 564 |

(The "before" split comes from the diagnostic classifier of the gate-fix
work; "after" equals `qtime_miss_class` of the study.)

### Current default vs references

| KPI (3 seeds) | planning + hard (default) | planning + off (experiment switch) | EDD (off): industry reference |
|---|---:|---:|---:|
| status | infeasible: 111 avoidable | infeasible: 855 avoidable | **infeasible: 1737 avoidable** |
| avoidable violations | 111 (43 / 43 / 25) | 855 | 1737 |
| unavoidable exceptions | 65 | 873 | 1408 |
|   breakdown after admission | 46 | 796 | 1125 |
|   down / PM, rework, transport | 19 | 77 | 283 |
| inherited windows missed (t=0 WIP) | 426 | 446 | 565 |
| expedited (hot) lots | 564 | - | - |
|   recovered by 7 d | 519 | - | - |
|   time to recover, mean / p90 max (min) | 1396 / 3143 | - | - |
| completed / run | 486.7 | 503.7 | 520.0 |
| on-time % | 82.12 | 91.96 | 91.96 |
| weighted tardiness (min/run) | 44,008 | 20,950 | 21,046 |
| true Q-time % | 99.26 | 94.62 | 89.23 |

## Honest reading

* No configuration is Q-time-feasible yet. The default has the fewest
  avoidable violations (111 over 3 seeds, about 37 per 7-day run against
  1737 for EDD); it is the candidate being worked on, not a finished one.
* The remaining avoidable misses sit almost all at the batch diffusion
  furnaces (`Diffusion_BE_123`, `Diffusion_FE_94`). At the miss every furnace
  is running lots that were never gated (no open window at that step). The
  gate counts only committed load against free tool time; ungated starts
  can take that time before the admitted lot arrives.
* Two fixes for that were tried and rejected (seeds 1-3, 7 d): holding tools
  from ungated starts when they would break the committed plan gridlocked
  the fab (about 80 lots completed per run); adding arrival (release) times
  to the check cut output to 267-336 lots per run without reducing misses.
  Neither is in this code.
* Q-time-first costs delivery today: 17 fewer lots per run than the gate-off
  experiment, 9.8 pp on-time and about 2x weighted tardiness. These are the
  price of the current gate, not a comparison target.
* Seed 3 scored about half as many windows in the true-Q-time replay as
  seeds 1-2 (5,041 vs about 9,600); the per-seed miss counts above are from
  the sim and not affected, but the true Q-time % for seed 3 should be read
  with care.
