# Schedule_Viewer reuse map

Schedule_Viewer (SV, `github.com/Toygaolingxiao/Schedule_Viewer`, read at `8eab999`
"release:v7.19.1-constraint-fixes") is the owner's own schedule checker. This note lists
every SV constraint check and KPI module, says what ResiliMES-AI already does for each, and
recommends what to port into the SMT2020 simulator next.

Rules for this branch (`ui-r1`):

- No SV data file is used. All numbers come from the SMT2020 run (public industry benchmark).
- SV KPI logic is ported (plain Python, no pandas) into `resilimes/smt/kpi.py`, tested in
  `tests/test_sv_kpi.py`, and shown on the Overview and Daily KPIs screens.
- SV constraint logic is **not** wired into `resilimes/smt/simulate.py` here: that file is
  being changed on branch `qtime-urgent`. This doc is the plan only.

Legend for "ResiliMES": **sim** = enforced while dispatching (`simulate.py`, `fab.py`);
**check** = verified after the run (`resilimes/smt/invariants.py`, `check_trace`);
**n/a** = SMT2020 has no data for it; **missing** = could apply, not modelled.

## 1. KPI modules (`apps/kpi/kpi_engine/src/kpi_modules/`)

All take SV's `schedule_df` (one row per lot-step: lot, equipment, start, end, setup,
recipe, due date, priority) plus `analysis_start_time/end_time`.

| SV module | What it computes | ResiliMES-AI |
| --- | --- | --- |
| `due_date_adherence.py` | On-time count/rate of finished lots, mean delay of late lots | Ported: `kpi.due_date_adherence` (finish vs due per lot, per day / 48 h) |
| `qtime_achievement_rate.py` | Share of Q-time windows met | Ported: `kpi.qtime_achievement` on the replay's indexed windows. Semantics differ: SV counts start→end of the zone; SMT2020 counts the dataset's step-to-step window (see "decisions") |
| `queue_time_stats.py` | Wait between steps and its ratio to lead time, by priority | Ported into `kpi.lot_step_stats` (queue mean per class VIP/hot/normal) |
| `xfactor_stats.py` | X-factor mean/variance (lead time ÷ raw process time) | Ported into `kpi.lot_step_stats` (`xfactor_mean`) |
| `lead_time_stats.py` | Lead time mean/variance per lot | Partly: per-step lead time inside `lot_step_stats`; per-lot cycle-time variance is **missing** (needs whole-route lots; 48 h is short) |
| `setup_time.py` | Setup time and share of tool time | Ported: `kpi.setup_time` |
| `equipment_stats.py` | Tool idle time and wait (idle) rate | Ported: `kpi.equipment_stats` |
| `equipment_activity_analysis.py` | Production / setup / down / PM / idle split | Ported: `kpi.activity` (the "Where tool time went" bars) |
| `equipment_load_summary.py` | Load rate per tool and tool group | Ported: `kpi.load_by_group` (per process area) |
| `throughput.py` | Lots and wafers moved per day | Ported: `kpi.throughput` (counts lot-step moves, as SV does) |
| `batch_formation_rate.py` | Batches formed and fill rate vs capacity | Ported: `kpi.batch_formation` |
| `same_recipe_consecutive_runs.py` | Share of consecutive runs on a tool with the same recipe | Ported: `kpi.same_recipe_runs` |
| `transfer_counts.py` | Inter-fab / inter-building transfers per day | n/a: SMT2020 has one site and no transport model |

## 2. Constraint checks (`libs/constraints/check_*.py`)

Each is `check_x(input, output) -> bool` where `input` is SV's master tables (CSV/Parquet
from the MES) and `output` the schedule result. Grouped by how much they matter for SMT2020.

### 2a. Already covered

| SV check | What it verifies (inputs) | ResiliMES-AI |
| --- | --- | --- |
| `check_equipment_capability` | Tool is in the capable list for the logical recipe (`RTS_Eqp_Arrange_Info`) | sim + check `family` (tool belongs to the step's family) |
| `check_process_order` | Steps run in route order, next starts after previous ends; skip only where allowed (`Operation_Info`, `OPE_JUMP`) | sim + check `route_order`, `sampling` (lot-ID sampling skips) |
| `check_parallel_processing` | Concurrent batches per tool ≤ max (`Eqp_Info.EqpMaxProcessingCnt`) | sim + check `tool_overlap` (one piece per tool) |
| `check_batch_size` | Lots/wafers per batch ≤ max (`Eqp_Info.MaxBatchSize_*`) | sim + check `batch`, `batch_min` (BATCHMN floor with logged reason) |
| `check_maintenance` | No start inside a PM window (`RTS_A3_STOP_EQP_P3`) | sim + check `pm_overlap`, `down_start` |
| `check_interval_setup` | Setup (and interval) time between runs matches the setup matrix (`SETUP`, `INTERVAL`) | sim: sequence-dependent setup from `setup.txt`; interval/dummy part n/a. No after-the-fact check (**missing check**) |
| `check_tact` | Process time matches the master (`MT_TABLE_MATRIX`, `Operation_Info`) | sim uses dataset times; no after-the-fact check (**missing check**) |
| `check_qtime_zone` | Zone start→end within limit (`QTIME_ZONE`) | sim counts violations; check `qtime_recount`. Being reworked on `qtime-urgent` |
| `check_lot_release_time` | No start before release (`USER_INPUT_SCHEDULE.RELEASE_DATE`) | sim: lots start from the dataset's WIP/releases only |
| `check_rework_return` | Return step after rework is the defined one (`Rework_Return_Ope`) | sim + check `rework_redo` (breakdown rework redoes the same step) |
| `check_cf_machine_memory` / "号機覚え" part of `check_flow_fab_restriction` | Same lot uses the same tool across linked steps | sim + check `dedication` (litho layer pinned to first-layer scanner, re-pinned if down) |

### 2b. Missing, and would change dispatch if ported

| SV check | What it verifies (inputs) | ResiliMES-AI |
| --- | --- | --- |
| `check_hold_and_release` | ONHOLD lots start only after release time (`Lot_Info.HOLD_*`) | missing (only rework holds) |
| `check_inhibit` | Tool×recipe/product inhibits, with lot exceptions (`Inhibit*`, `Operation_Info`) | missing |
| `check_online_alarm` | No start for alarmed tool/lot/recipe after alarm time (`EqpAlarmNGListsForRTS`) | missing |
| `check_cumulative_maintenance` | Film-thickness / dummy-wafer counters force PM before alarm (`ADDITION_*`, `DIFF_FILM`) | missing (SMT2020 has calendar PM only) |
| `check_reticle_constraint` | Active reticle present on scanner, reticle capacity (`RTS_ReticleInfo`) | missing (SMT2020 has no reticles) |
| `check_conditioning_dummy` | Dummy lot inserted after long idle (`RTS_DummyDeviceGmst`) | missing |
| `check_pilot_segment_block` | Followers wait until pilot lot leaves the segment | missing |
| `check_non_working_day` | No processing on non-working days (`RTS_WARKING_PLAN`) | n/a (fab runs 24/7 in SMT2020) |
| `check_excluded_eqps` | No start on tools with excluded port status (`SCHEDULE_PARAMETER`) | missing (closest: down calendar) |
| `check_excluded_lots` | Finished/shipped lots never scheduled (`Lot_Info`) | covered implicitly (done lots leave the sim) |

### 2c. Site- or MES-specific (keep out of the SMT2020 sim)

`check_flow_fab_restriction` (remeasure tool, MES designate, pilot return, dispatch
reservation, in-transit lot, flow/lot fab restriction), `check_pathfinder_compliance`,
`check_neo_compliance`, `check_siview_eqp`, `check_lot_eqp_restriction`,
`check_css_recipe`, `check_css_special_instruction`, `check_impla_gas_type`,
`check_bonding_constraint`, `check_branch_return`, `check_prohibited_transfer`,
`check_transfer_capacity`. These read customer MES tables (SiView, NEO, Pathfinder, CSS,
transport base) that SMT2020 does not have. They stay valuable for the "real fab adapter"
story but have nothing to bind to in the benchmark.

Framework files: `validator.py` (`ScheduleConstraintValidator`, runs all checks,
`ALL_CONSTRAINTS`), `task_manager.py` (async runs + progress),
`specs/constraint_metadata.py` (per-check name/description/related columns). ResiliMES's
counterpart is `check_trace` + `CHECKS` in `invariants.py` and the "Checks" tab.

## 3. Recommendation: what to port next

Order is by demo value per hour of risk. None should land until `qtime-urgent` merges.

1. **Setup and tact re-check (post-run, check only).** Port the comparison half of
   `check_interval_setup` and `check_tact` into `invariants.py` as `setup_matrix` and
   `process_time` counters. *Effect:* two more green rows on Checks; proves the trace
   matches `setup.txt` and route times. *Risk:* very low, no dispatch change, no benchmark
   numbers move.
2. **Hold and release (`check_hold_and_release`).** Add an optional hold list (lot, until)
   honoured by the dispatcher and a `hold_release` check. *Effect:* enables an "engineering
   hold" what-if next to tool-down and VIP promotion; operators ask for it first. *Risk:*
   low–medium; base book unchanged when the list is empty, but it touches dispatch, so after
   `qtime-urgent`.
3. **Inhibit (`check_inhibit`, simplified tool×recipe).** Optional inhibit table used when
   picking a tool, plus a check. *Effect:* "inhibit this chamber for recipe X" scenario,
   shifts load inside a family, makes the Tools screen's bottlenecks move. *Risk:* medium;
   needs care so a family never ends with zero capable tools (would strand lots).
4. **Cumulative maintenance (`check_cumulative_maintenance`, counter-based PM).** Wafer-count
   triggered PM on furnaces/CVD. *Effect:* realistic PM in 48 h (published calendar has 0 PM
   in the window), feeds the PM state on the Tools screen. *Risk:* medium–high: changes
   tool availability, so every benchmark number moves; label as a separate book, not base.
5. Leave reticle, dummy, pilot and 2c items as "real-fab adapter" next steps.

Expected effect on numbers: items 1 none; 2 and 3 none for the base book (empty tables),
only in their own what-if books; 4 changes the base unless kept as an optional book.
