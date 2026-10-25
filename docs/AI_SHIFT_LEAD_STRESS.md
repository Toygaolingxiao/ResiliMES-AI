# AI shift lead: pre-registered stress book

Status: **pre-registration**. This file was committed before any stress
scenario was simulated. Its commit hash is the proof. Results go in a
separate section added afterwards; nothing above "Results" changes after the
first run.

## Why

PR #47 made the AI shift lead exception-only: the rule default runs, a no-AI
twin preview scores the rule plan (8 h x 3 futures), and the shift lead (and
so Nemotron) is asked only if the preview projects at least 1 avoidable
Q-time violation (`hard_qtime.miss_class`, docs/HARD_QTIME.md) or at least 1
late hot/VIP lot. On `heldout_published`, seeds 9-13, 8 h: 93-100 exceptions
per seed and **0 escalations**. In normal production the AI never acts.

The question here is whether there are realistic incidents in which the rule
default is plausibly inadequate, how often the AI is then called, and
whether it helps. The escalation threshold (`GATE_QAVOID_MIN = 1`,
`GATE_HOT_LATE_MIN = 1`), dispatch weights, the published due dates and the
seeds are **not** changed for this study.

## Book `stress`

Five scenarios on the full SMT2020 fab (published routes, process times,
setups, CQT limits, dues; sampled breakdowns of the seed as in
`heldout_published`; published PM calendar). Each adds one incident that
starts at the snapshot (t = 0 is the start of the shift in which the incident
happens) or inside the shift. Horizon 8 h, fork 8 h, 3 futures, as in the
live evaluation. Policy `resilimes` (planning + hard Q-time default), same as
every study arm.

Target families come from the hard-Q-time study: the remaining avoidable
misses sit at the batch diffusion furnaces `Diffusion_BE_123` (9 tools,
target of the chained segment `DE_BE_69 -> WE_BE_17` (300 min) `->
Diffusion_BE_123` (600 min), and of `Dielectric_BE_28 -> Diffusion_BE_123`
(240 min)) and `Diffusion_FE_94` (13 tools, target of `WE_FE_108` (480 min)).
"Half the tools" means the first `ceil(n/2)` tools of the family in tool
order, as in the investigator's fault injector (`resilimes.insight.injector`).

| # | id (book) | realistic incident | exact injection |
|---|---|---|---|
| S1 | `stress_furnace_down` | diffusion furnace tubes fail while the chained CQT segment into them is full (46 lots queued at t = 0, 35 one step away) | `Diffusion_BE_123-1` .. `-5` (5 of 9) down from 0 h to 4 h (added to the sampled downs) |
| S2 | `stress_hot_cqt` | a customer expedite: a lot about to enter the chained CQT segment is made hot with an in-shift due | lot `Init_Lot_2_1` (rule below) promoted to hot/VIP (`promote_hot`, value 3), due = 2.0 x its remaining raw process time at t = 0 = 6.757 h |
| S3 | `stress_release_burst` | a held batch of WIP (e.g. an engineering hold lifted) arrives at once at the CQT origins feeding the furnace | every WIP lot whose current or next step is at `DE_BE_69`, `WE_BE_17` or `Dielectric_BE_28` (80 lots) is held at t = 0 and arrives at 1 h (`FaultPlan.hold_until`) |
| S4 | `stress_pm_peak` | PM placed in the arrival peak of a CQT-target furnace | `Diffusion_FE_94-1` .. `-7` (7 of 13) in PM from 1 h to 5 h (added to the published PM windows) |
| S5 | `stress_batch_cap` | furnace load limited to one lot (quartzware / boat shortage), so batches starve | `Diffusion_BE_123` batch cap (BATCHMX) lowered to 25 wafers (1 lot) from 0 h to 6 h (`FaultPlan.batch_cap_wafers`) |

S2 lot rule (fixed before running, from static data only): the
normal-class WIP lot with 2 h <= remaining raw process time <= 4 h at t = 0
whose remaining route contains a CQT origin. Exactly one lot qualifies:
`Init_Lot_2_1` (part_2, 3.379 h remaining, at `DE_BE_69`, a CQT origin into
`WE_BE_17`, itself the origin of the 600-min window into `Diffusion_BE_123`).
The hot due uses X-factor 2.0 (a hot lot), not the book's 2.75 for normal lots,
so that it falls inside the shift.

Twin note: forks resample only breakdowns that start after the fork moment.
The incidents above start at t = 0 (downs) or are part of the simulator state
(PM windows, holds, batch cap), so the twin preview knows the incident, as a
real shift lead would. It does not know future random breakdowns.

Seeds: **9, 10, 11** (the first three held-out seeds). Fixed.

Order (fixed, used for any subset): seed-major, scenario order S1..S5:
(S1,9) (S2,9) (S3,9) (S4,9) (S5,9) (S1,10) ... (S5,11).

## Arms

* `rules`: rules only, no shift lead.
* `sim`: exception-only gate, then the twin selects among the engine plans
  (do-no-harm Pareto), no LLM. This is the bar the LLM must beat.
* `sim_llm`, `sim_llm_hmem` (live, on the PC, Nemotron via Nightshift).
  For the stress book H-MEM has **no warm-up**: each run starts with empty
  memory and accumulates cases within the run (saves the warm-up's LLM
  calls; the stress book has no dev seeds).
* `sim_hmem` (LLM-free, memory without warm-up) may be run as a baseline.

## Metric (Q-time first)

Per run, lexicographic, lower is better:

1. **avoidable Q-time violations** in the run (`RunResult.qtime_miss_class
   ["avoidable"]`). Any plan with more avoidable violations is worse,
   whatever its tardiness.
2. **hot/VIP lots late**: lots of tier VIP/hot (SMT2020 PRIOR, plus the S2
   promoted lot) due inside the horizon that did not finish by their due.
3. **weighted tardiness** (value x minutes, open lots censored at the
   horizon); a difference within 0.5 min is a tie.

Also reported, not used for the decision: total Q-time violations, on-time %,
completed routes, escalations, fallbacks, LLM calls.

## Decision rule

Per (scenario, seed) pair, an arm wins/ties/loses against `rules` by the
lexicographic metric above.

* **AI called**: a scenario "needs the AI" if the `sim` arm escalates at
  least once in at least one of its seeds. 0 escalations is reported as such;
  the scenario is not changed afterwards. New scenarios, if any, go into a
  second, separately committed pre-registration and the first set stays in
  the results.
* **Bar**: the `sim` arm's (twin-only) result per pair is the bar.
* **LLM helps** (live): `sim_llm` (and separately `sim_llm_hmem`) helps if,
  over the pairs run, its total avoidable violations are lower than `rules`'
  (or equal with fewer hot late, or equal on both with lower total weighted
  tardiness), and it has more lexicographic wins than losses vs `rules`.
* **LLM adds over the twin**: the same test against `sim` instead of `rules`.
* **Harm**: more losses than wins vs `rules`, or any pair with more
  avoidable violations than `rules`, is reported as harm.

With at most 15 pairs nothing here is a significance test; sign counts and
totals are reported as they are.

## Live runtime and subset rule

Estimate per escalation: 2 Nemotron calls x 60 s + 15 s twin = 135 s, plus
each run's no-LLM wall (gate and simulation, measured on the box in the
`sim` arm). Escalation counts are taken from the mock `sim` arm (the live
arms diverge after their first non-default choice, so this is an estimate).
Both live arms count (`sim_llm` + `sim_llm_hmem`). If the total exceeds 2 h,
the live run uses the longest prefix of the fixed order above whose
cumulative estimate for both arms is at most 2 h (`--first N`), and the
report says so.

## Second pre-registration (P2, book `stress2`)

**Clearly labelled post-hoc set.** Written after seeing the first set's
seed-9 results (rules and `sim` arms: 0 avoidable Q-time violations, 0 late
hot lots, **0 escalations** in all five scenarios; seeds 10-11 were still
running). The first set stays in the results unchanged. P2 is committed
before any P2 run; same seeds (9, 10, 11), horizon, fork, futures, arms,
metric, decision rule and runtime rule as above, and the threshold, weights,
published dues and seeds are still untouched. P2 is harsher on purpose: it
asks whether *any* realistic, if severe, incident makes the rule default
project an avoidable miss or a late hot lot.

| # | id (book) | incident | exact injection |
|---|---|---|---|
| P2-1 | `stress2_furnace_crisis` | furnace-bay crisis: tube failures, load limit and a lifted hold at the same time | S1 + S3 + S5 together (`Diffusion_BE_123-1..5` down 0-4 h; the 80 S3 lots held until 1 h; `Diffusion_BE_123` batch cap 25 wafers 0-6 h) |
| P2-2 | `stress2_rush_hot` | rush expedite with minimal slack | S2 lot `Init_Lot_2_1` promoted hot, due = 1.25 x remaining raw process time = 4.223 h |
| P2-3 | `stress2_fe_furnace_crisis` | front-end furnace crisis | `Diffusion_FE_94-1..7` (7 of 13) down 0-4 h and `Diffusion_FE_94` batch cap 25 wafers 0-6 h |

Order for any subset: seed-major, then P2-1..P2-3, after the first set
(`--book stress2` runs P2 only).

## Results

Added after all runs finished (box, mock/no-LLM arms only: `rules` and
`sim`). Nothing above this section was changed. Raw per-run JSON:
`stress_out/{rules,sim}/<scenario>_s<seed>.json` (not committed); produced by
`python -m eval.sim_select_study --book stress` and `--book stress2`.

All 8 scenarios (P1: 5, P2: 3) x seeds 9, 10, 11 = 24 pairs, 8 h horizon,
fork 8 h, 3 futures. Sums over the three seeds, `rules / sim`:

| scenario | avoidable Q-time | all Q-time viol. | hot late | weighted tardiness (min) | exceptions (sim) | escalated (sim) | sim vs rules W-T-L |
|---|---|---|---|---|---|---|---|
| `stress_furnace_down` | 0 / 0 | 0 / 0 | 0 / 0 (of 0 due) | 16254.4 / 16254.4 | 267 | 0 | 0-3-0 |
| `stress_hot_cqt` | 0 / 0 | 31 / 31 | 0 / 0 (of 3 due) | 15628.3 / 15628.3 | 286 | 0 | 0-3-0 |
| `stress_release_burst` | 0 / 0 | 10 / 10 | 0 / 0 (of 0 due) | 16195.8 / 16195.8 | 268 | 0 | 0-3-0 |
| `stress_pm_peak` | 0 / 0 | 31 / 31 | 0 / 0 (of 0 due) | 16254.4 / 16254.4 | 286 | 0 | 0-3-0 |
| `stress_batch_cap` | 0 / 0 | 35 / 35 | 0 / 0 (of 0 due) | 16254.4 / 16254.4 | 294 | 0 | 0-3-0 |
| `stress2_furnace_crisis` | 0 / 0 | 14 / 14 | 0 / 0 (of 0 due) | 16195.8 / 16195.8 | 286 | 0 | 0-3-0 |
| `stress2_rush_hot` | 0 / 0 | 31 / 31 | 0 / 0 (of 3 due) | 15628.3 / 15628.3 | 286 | 0 | 0-3-0 |
| `stress2_fe_furnace_crisis` | 0 / 0 | 31 / 31 | 0 / 0 (of 0 due) | 16254.4 / 16254.4 | 298 | 0 | 0-3-0 |
| **total (24 pairs)** | **0 / 0** | 183 / 183 | **0 / 0** (of 6 due) | 128665.8 / 128665.8 | 2271 | **0** | 0-24-0 |

* **AI called: no.** In none of the 8 scenarios and none of the 3 seeds did
  the no-AI twin preview of the rule default project an avoidable Q-time
  violation or a late hot lot, so the `sim` arm escalated **0 times out of
  2271 exceptions**. By the decision rule above, no scenario "needs the AI".
* **Bar**: identical to `rules` in every pair (0 avoidable, 0 hot late, same
  weighted tardiness): the twin found no reason to deviate from the rule plan.
* All 183 Q-time violations in these runs are classified unavoidable by
  `hard_qtime.miss_class` (169 `unavoidable_pre_gate`: the lot had already
  entered the window before the snapshot / gate; 14
  `unavoidable_disruption`). None is avoidable.
* The live arms (`sim_llm`, `sim_llm_hmem`) were **not run** for this book:
  with 0 escalations in the mock `sim` arm they would call Nemotron 0 times
  and reproduce the `sim` result; the runtime rule makes this a 0-LLM run.
* Several scenarios give identical weighted tardiness (e.g. `stress_hot_cqt`
  and `stress2_rush_hot`; `stress_furnace_down`, `stress_pm_peak`,
  `stress_batch_cap`, `stress2_fe_furnace_crisis`): within an 8 h horizon the
  furnace incidents delay lots that are not due inside the horizon, so the
  censored tardiness of due lots does not move. The Q-time columns do move.

**Conclusion (honest).** With hard Q-time gating (docs/HARD_QTIME.md) the
rule plan already holds Q-time in all pre-registered incidents at the 8 h
scale: the gate does not release a lot into a window it cannot close, so
the incidents turn into queueing upstream of the CQT origin (tardiness), not
into avoidable Q-time misses. The AI shift lead is a **safety net** that
these incidents never trip. This is a negative result for "the AI is
needed" and a positive result for the rules-first design. Demo cases where
the AI is genuinely called are built separately, from moments where the
rule failed in long runs, and are **not** part of this pre-registered
evaluation (docs/AI_SHIFT_LEAD_DEMO.md).
