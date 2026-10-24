# SMT2020 provenance

Public industry benchmark (SMT2020), PySCFabSim-release commit `0dbff6a`, directory `datasets/SMT2020_LVHM`. This is not a recording from a production fab. Counts below were checked against `data/smt2020` in this repository.

The scored studies run 24 hours (tight VIP) or 48 hours (X-factor and the published-due appendix). Interactive lithography, hot-lot, PM, WIP, and queue-time clicks stay at 12 hours. Chamber-level tools, AMHS, and a full batching discrete-event model are out of scope.

## Modeled, simplified, not modeled

| SMT2020 feature | Modeled | Simplified mapping | Not modeled |
| --- | --- | --- | --- |
| Routes | All 10 routes. 4,013 steps. Shortest route 242 steps, longest 583. | A lot is ready for the next step when the current step ends. `LTIME` and `ULTIME` are not added to `PTIME`. | Future releases from `order.txt` (`REPEAT` about 258 minutes) are not started inside the horizon. The load is the 2,156-lot WIP snapshot. |
| Batching | 135 `per_batch` steps. Lots of 25 wafers pack up to `BATCHMX`. A short pack ships after 30 minutes. | Not a furnace discrete-event model. No temperature ramp, boat, or cascade. `BATCH_MAX_WAIT_SEC=1800` is ours. The `BatchInterval` column in the extract is empty. | Chamber slots. |
| MTTF / MTTR | `downcal.txt`. Exponential MTTF and MTTR, one clock per tool, shared across policies. 10,000 draws of the lithography MTTR (mean 705.59 minutes): mean 705.4, population standard deviation 708.7, p50 486.4, p90 1,651.4. Share at or under 180 / 300 / 600 minutes: 0.233 / 0.346 / 0.575. The X-factor schedule is also run at those three repairs plus the published mean. On-time delivery does not move. | PM duration is the published MTTR mean, not a draw. 213 piece-count calendars are not wall-clock windows. The family-wide shift that opens `Litho_FE_92_WK` at 2 hours is our assumption: the extract stores one FOA per family, and that FOA sits about 7 days out until the same offset is subtracted from every day-based calendar. | |
| Rework | | A missed adjacent Wet_Etch queue-time limit sends the lot back through that wet step once, then continues. It is not held. | `REWORK` is set on 52 `Litho_REG` steps (examples 0.7, 1.0, 1.7, `RWKTYPE` lot). That column is not sampled. |
| Queue time | 264 CQT limits, 181 of them adjacent. The largest adjacent pairs are Dry_Etch to Wet_Etch (44), Planar to Dielectric (39), Dielectric to Dielectric (39), TF to Planar (26). | Upstream gating is only the 27 adjacent Wet_Etch pairs (15 into Diffusion, 12 into Litho). On the X-factor book that gate fired 0 times. A non-wet miss is counted and the lot continues. There is no clean-to-deposition pair in the extract. | |
| Scanner setup | Expose steps have no route `STIME`. `setup.txt` names only `DE_BE_13`, `DE_BE_66`, `Implant_128`, `Implant_132`, and `Implant_91`. A scanner change adds 0 seconds. | | |
| Dedication and qualification | `SVESTN=yes` and `FORSTEP`: 73 forward links, 99 litho steps, every link inside one station family. A later layer uses the scanner this run chose for the first layer of the chain. | The station family is the qualification. The files have no finer product-layer by scanner matrix. WIP has no tool column, so a lot that starts mid-chain is not pinned until this run processes a dedicated step. | Reticle copies, stocker versus tool location, and reticle transfer time. `fromto.txt` is one Fab-to-Fab row (uniform 7.5 minutes) and is not applied. |
| Lot in process at a breakdown | Elapsed process stops at the breakdown. The remaining process resumes on that same tool after 15 minutes. | The 15-minute wait is our assumption. It is not an SMT2020 column. The WIP snapshot has no step-start time, so no lot begins the horizon already partial. | |
| Who paid | Tight VIP reports the 13 normal lots in the dielectric queue. X-factor reports non-VIP lots due inside the horizon. The figure is extra hours of lateness against EDD. | | |
| Baselines | SMT2020 lithography and the X-factor book use EDD. FIFO and critical ratio are on the same runs. | | The six-lot bay still compares a frozen assignment on `litho_down`. That bay also charges a scanner-family setup and a 5-minute reticle mount. `LOT-1001` still restarts a full step. Those tests were not retuned. |
| Scale preset | | 1,000 synthetic lots, 14 days of slack, up to 24 priority-1 lots pinned blocked on LITHO-03. It ties EDD. Makespan is not the SMT2020 headline. | Not the public benchmark. |

## What the review asked, and what the runs showed

The six-lot `litho_down` baseline does pin a lot to a down scanner while another qualified scanner can run it. The SMT2020 lithography scenario does not. Its before-policy is EDD.

On published dues, 48 hours, five seeds, EDD beats ResiliMES on on-time: 58.21% (163/280; 33, 33, 32, 33, 32 of 56) against 56.78% (159/280; 32, 32, 32, 32, 31 of 56). EDD weighted tardiness is 19,032.5 minutes against 19,095.04. ResiliMES has fewer Q-time violations (388.8 against 432.6) and re-cleans (47.0 against 57.2).

The X-factor book sets each due to remaining raw process time times 2.75. At a 600-minute repair, five-seed on-time is EDD 99.54% and ResiliMES 99.54% (population standard deviation 0.92 each; both 433/435, both miss two lots on seed 3). X-factor is about 1.57 (EDD) against 1.63 (ResiliMES). Queue-time violations are 479.0 against 436.8. Re-cleans are 48.8 against 53.4, so ResiliMES re-cleans more on this book. FIFO is 47.126% on time. Critical ratio is 76.552%. The same on-time numbers appear at 180, 300, and 705.59 minutes. Litho utilization is 75.708% (EDD) and 79.262% (ResiliMES) of the 102 `Litho_*` tools. The busiest expose family on the EDD seed-1 trace is `Litho_BE_110` at 94.5% (23 tools). Tools were not removed to force 90%. Seed 1 of that book: both are 87/87.

The book where EDD loses is still the constructed tight VIP stress. Five seeds, 24 hours: ResiliMES on-time 26.666% (28/105) against EDD 18.098% (19/105), FIFO 3.808%, critical ratio 18.098%. Weighted tardiness 3,548.88 minutes against 7,005.34. Queue-time violations 170.6 against 512.4. Seed 1: `Init_Lot_2_13` is 5.03 hours late under EDD and on time under ResiliMES. The 13 normal lots in that queue give up 39.8 hours. The largest single additions are `Init_Lot_8_2` 5.11 h, `Init_Lot_8_7` 3.37 h, `Init_Lot_8_4` 3.33 h, `Init_Lot_5_14` 3.33 h, and `Init_Lot_8_20` 3.19 h. That stress uses constructed dues on a real three-tool dielectric queue, a real CQT, and the published dielectric MTTR. It is not a frozen-tool pin, and it does not add a reticle the extract does not contain.

All of these numbers are after the stale-queue fix described in [invariants.md](invariants.md) and the fab-logic-r1 operation logic (batching, rework, sampling, tiered priority, setup charge) in [FAB_LOGIC_R1.md](FAB_LOGIC_R1.md).

Per-seed rows are in `data/smt2020/benchmark.json`.
