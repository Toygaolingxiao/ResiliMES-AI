# SMT2020 provenance

Public industry benchmark (SMT2020), PySCFabSim-release commit `0dbff6a`, directory `datasets/SMT2020_LVHM`. This is not a recording from a production fab. Counts below were checked against `data/smt2020` in this repository.

The scored studies run 24 hours (tight VIP) or 48 hours (X-factor and the published-due appendix). Interactive lithography, hot-lot, PM, WIP, and queue-time clicks stay at 12 hours. Chamber-level tools, AMHS, and a full batching discrete-event model are out of scope.

## Modeled, simplified, not modeled

| SMT2020 feature | Modeled | Simplified mapping | Not modeled |
| --- | --- | --- | --- |
| Routes | All 10 routes. 4,013 steps. Shortest route 242 steps, longest 583. | A lot is ready for the next step when the current step ends. `LTIME` and `ULTIME` are not added to `PTIME`. | Future releases from `order.txt` (`REPEAT` about 258 minutes) are not started inside the horizon. The load is the 2,156-lot WIP snapshot. |
| Batching | 135 `per_batch` steps. Lots of 25 wafers pack up to `BATCHMX`. A short pack ships after 30 minutes. | Not a furnace discrete-event model. No temperature ramp, boat, or cascade. | Chamber slots. |
| MTTF / MTTR | `downcal.txt`. Exponential MTTF and MTTR, one clock per tool, shared across policies. 10,000 draws of the lithography MTTR (mean 705.59 minutes): sample mean 705.4, std 708.7, p50 486.4, p90 1,651.4. Share at or under 180 / 300 / 600 minutes: 0.233 / 0.346 / 0.575. The X-factor schedule is also run at those three repairs plus the published mean. On-time delivery does not move. | PM duration is the published MTTR mean, not a draw. 213 piece-count calendars are not wall-clock windows. | |
| Rework | | A missed adjacent Wet_Etch queue-time limit sends the lot back through that wet step once, then continues. It is not held. | `REWORK` is set on 52 `Litho_REG` steps (examples 0.7, 1.0, 1.7, `RWKTYPE` lot). That column is not sampled. |
| Queue time | 264 CQT limits, 181 of them adjacent. The largest adjacent pairs are Dry_Etch to Wet_Etch (44), Planar to Dielectric (39), Dielectric to Dielectric (39), TF to Planar (26). | Upstream gating is only the 27 adjacent Wet_Etch pairs (15 into Diffusion, 12 into Litho). On the X-factor book that gate fired 0 times. A non-wet miss is counted and the lot continues. There is no clean-to-deposition pair in the extract. | |
| Scanner setup | Expose steps have no route `STIME`. `setup.txt` names only `DE_BE_13`, `DE_BE_66`, `Implant_128`, `Implant_132`, and `Implant_91`. A scanner change adds 0 seconds. | | |
| Dedication and qualification | `SVESTN=yes` and `FORSTEP`: 73 forward links, 99 litho steps, every link inside one station family. A later layer uses the scanner this run chose for the first layer of the chain. | The station family is the qualification. The files have no finer product-layer by scanner matrix. WIP has no tool column, so a lot that starts mid-chain is not pinned until this run processes a dedicated step. | Reticle copies, stocker versus tool location, and reticle transfer time. `fromto.txt` is one Fab-to-Fab row (uniform 7.5 minutes) and is not applied. |
| Lot in process at a breakdown | Elapsed process stops at the breakdown. The remaining process resumes on that same tool after 15 minutes. | The 15 minutes are not an SMT2020 column. The WIP snapshot has no step-start time, so no lot begins the horizon already partial. | |
| Who paid | Tight VIP reports the 13 normal lots in the dielectric queue. X-factor reports non-VIP lots due inside the horizon. The figure is extra hours of lateness against EDD. | | |
| Baselines | SMT2020 lithography and the X-factor book use EDD. FIFO and critical ratio are on the same runs. | | The six-lot bay still compares a frozen assignment on `litho_down`. That bay also charges a scanner-family setup and a 5-minute reticle mount. `LOT-1001` still restarts a full step. Those tests were not retuned. |
| Scale preset | | 1,000 synthetic lots, 14 days of slack, up to 24 priority-1 lots pinned blocked on LITHO-03. It ties EDD. Makespan is not the SMT2020 headline. | Not the public benchmark. |

## What the review asked, and what the runs showed

The six-lot `litho_down` baseline does pin a lot to a down scanner while another qualified scanner can run it. The SMT2020 lithography scenario does not. Its before-policy is EDD.

On published dues, 48 hours, five seeds, EDD is slightly ahead of ResiliMES (on-time 56.784% against 56.428%, weighted tardiness 21,525.68 minutes against 21,988.14). That is not a tie.

The X-factor book sets each due to remaining raw process time times 2.75. At a 600-minute repair, five-seed on-time is EDD 99.54% (sample std 0.563) and ResiliMES 97.47% (sample std 2.76). X-factor is about 1.70 against 1.69. Queue-time violations are 451.6 against 430. Re-cleans are 55.6 against 38. FIFO is 20.688% on time. Critical ratio is 71.722%. The same on-time numbers appear at 180, 300, and 705.59 minutes. Litho utilization is 79.294% (EDD) and 78.076% (ResiliMES) of the 102 `Litho_*` tools. The busiest expose family on the EDD seed-1 trace is `Litho_BE_110` at 85.5% (23 tools). Tools were not removed to force 90%. Seed 1 of that book: no scored non-hot lot finishes later under ResiliMES, and both policies are 100% on time. The five-seed mean is where EDD is ahead.

The book where EDD loses is still the constructed tight VIP stress. Five seeds, 24 hours: ResiliMES on-time 19.05% against EDD 12.382%, FIFO 0%, critical ratio 9.52%. Weighted tardiness 4,329.38 minutes against 7,985.74. Queue-time violations 176 against 413.8. Seed 1: `Init_Lot_2_23` is 5.43 hours late under EDD and on time under ResiliMES. The 13 normal lots in that queue give up 31.72 hours. The largest single additions are `Init_Lot_8_20` 3.61 h, `Init_Lot_8_9` 3.22 h, `Init_Lot_8_3` 3.02 h, `Init_Lot_5_5` 2.98 h, and `Init_Lot_5_14` 2.98 h. That stress uses constructed dues on a real three-tool dielectric queue, a real CQT, and the published dielectric MTTR. It is not a frozen-tool pin, and it does not add a reticle the extract does not contain.

Per-seed rows are in `data/smt2020/benchmark.json`.
