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
