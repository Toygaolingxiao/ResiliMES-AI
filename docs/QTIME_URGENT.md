# Q-time-urgent override (branch `qtime-urgent`)

## Pre-registration

Written and committed before the rule was run on any seed.

- **Scope.** ResiliMES dispatch only. EDD, FIFO, CR and smt_rule are unchanged. Q-time exists only on the 264 of 4,013 route steps where SMT2020's CQT column is set (1-24 h). The rule never applies to any other step.
- **Open window.** A lot has an open window from the end of a CQT origin step until it starts that step's CQT target step.
- **Need.** The dataset process time (`cycle`) of the steps the lot still has to run before the target: its current step if that is not the target, plus each later step before the target that the lot-ID sampling rule measures. Setup is not counted, because the later tools are not known yet.
- **Urgent.** need <= remaining <= need + margin, where remaining = window deadline - now. Below need the window is already lost and the rule does not fire.
- **Margin.** `QTIME_URGENT_MARGIN_SEC` = 900 s (15 min). About three times the mean VIP queue wait on the published book (5.7 min), so an urgent lot gets at least one dispatch on its family, and a quarter of the shortest CQT limit (1 h). One value for every book and seed. Not tuned.
- **Order.** Band 0: VIP or hot lots that are late or Q-time-urgent. Band 1: other Q-time-urgent lots. Band 2: everything else. Inside a band, the existing tiered key (class tier, late, Q-time risk, setup, slack).
- **Batches.** The same key orders each recipe group, so an urgent lot can lead a batch. A batch under BATCHMN with an urgent member starts at once, reason `qtime_urgent`.
- **Override and KPI.** An override is a start whose leading lot is Q-time-urgent and where the key without the band would have picked a lot that is not in this start. Each one is logged with the remaining and needed seconds and the class of the displaced lot, and counted.
- **Pass criteria, stated before the run.** Keep the rule if published-book re-cleans fall and on-time and VIP/hot wait do not get materially worse (on-time within 1 lot of the tiered baseline, VIP and hot mean wait within 1 min). Otherwise report it and recommend against.

### Amendment 1: lot transport (Oct 24 2026, 14:2x UTC+9, before the full rerun)

Added at the user's request on the same branch so that one full-scale rerun covers both changes. Written before the full benchmark was rerun with transport.

- **Transport model, all policies.** When a lot finishes a step, or is sent back to re-clean, it reaches the next family's queue only after a fixed move: 1 min if both families are in the same bay, 3 min otherwise. No AMHS and no vehicle limit. Q-time windows keep running during the move, so a deadline is still the origin end plus the CQT limit.
- **Bay mapping.** SMT2020 does not name bays. Every family in `tool.txt.1l` has `STNFAMLOC` = `Fab`, and `fromto.txt` has one `Fab`-to-`Fab` row (uniform 7.5 ± 2.5 min). So the bay of a family is its `STNGRP` station group (14 groups: Def_Met, Delay, Delay_32, Dielectric, Diffusion, Dry_Etch, Implant, Litho, Litho_Met, Planar, TF, TF_Met, Wet_Etch, and so on). Same group means same bay. The 1 min and 3 min values come from the user and are not SMT2020 data. The dataset's 7.5 min `fromto` row is still not used.
- **Need, updated.** `need` now also counts the fixed transport legs between the current step, the later measured steps, and the target. The margin stays at 900 s, and the band and override definitions are unchanged.
- **Before baseline.** "Before" is still main at PR #17 (993fd9e): tiered priority, no override, no transport. So the before/after columns combine the override and transport. To separate the two effects, the benchmark also runs the published book (seeds 1–5, all five policies) with transport turned off (`steady_no_transport`).
- **Disclosure.** Before this amendment I ran two smoke checks on seed 1 of the published book only, both to confirm the code runs and that all invariants are 0. The first was the override without transport, followed by the full benchmark of that version. The second was the override with transport. Neither check changed the margin, and no value was tuned.
