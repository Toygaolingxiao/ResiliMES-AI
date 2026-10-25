# AI shift lead: propose → fork → simulate → select

Branch `shift-lead-sim`, stacked on `shift-lead-progress` (#28) → `ai-shift-lead` (#24).
**Off by default.** Nothing in the app, the API or `run_policy` uses it; it runs
only when a study arm or a caller builds `SimShiftLead` explicitly.

## What it does

At an *escalated* exception (see "When the shift lead is asked" below) the shift lead:

1. **Recall** (optional, H-MEM): top-5 similar past cases with their receipts
   ([H_MEM.md](H_MEM.md)).
2. **Propose**: Nemotron (lane `shift_lead_plan`) writes up to 4 typed plans
   from a closed lever set. The engine's own options are always candidates too,
   so a bad or missing model reply never leaves the lead without plans.
3. **Guardrails** (`PlanBuilder`) reject any plan that breaks a rule before it
   is simulated:
   - `keep_pin` ≤ 8 h (or until the repair at a breakdown);
   - `reroute` only at a breakdown; frozen lots (`sim.fz.free_for`) cannot be
     moved or boosted; FIX lots stay on their tool;
   - `boost` ≤ 60 min, only listed lots, at their real next step;
   - `defer_pm` — flex-PM rule: new start within ±24 h of the *planned* start,
     in the future, no overlap with the same tool's previous / next PM, and no
     two tools of the family in PM together (overlap may not grow); one PM move
     per plan;
   - `start_batch` only for a recipe with lots waiting;
   - only lots and tools in the exception's scope; ≤ 4 levers per plan.
4. **Fork** (`resilimes/smt/twin.py`): the live sim is pickled and each plan
   plus the rule default is run `fork_h` ahead (default 8 h) over `futures`
   (default 3) **resampled** futures. Repairs already under way are kept; every
   future breakdown is redrawn from the fab's MTBF/MTTR with seed
   `sha256("twin:{seed}:{t}:{k}")`. The forks never see the true future
   (`tests/test_twin.py::test_forks_do_not_see_the_true_future`). All plans
   share the same futures (common random numbers). Forks run in a `spawn`
   process pool (Windows-safe; nothing runs at import).
5. **Select**:
   - `pareto` (no model): a plan replaces the default only if it is no worse on
     Q-time violations, hot/VIP late lots and weighted tardiness and strictly
     better on one ("do no harm").
   - `llm` (lane `shift_lead_select`): the model sees the numbers table and must
     return `plan_id`, `reason` and `cited` (`"plan.metric": value`). The
     **number checker** rejects the pick if a cited value does not match the
     table, or if any number in the reason is not a table value; a pick with
     more hot/VIP late lots than the default is rejected too.
   - Any failure (timeout, provider error, bad JSON, unknown plan, number
     check, invariant) falls back to the **rule default** and is counted.
6. **Receipt**: the log entry keeps every plan, its guardrail result, the
   per-future KPIs and the chosen-vs-default deltas.

## When the shift lead is asked: rules first

**Rules first; the AI shift lead is asked only for exceptions the rule plan
can't handle.** Rule-based scheduling handles every event by itself. At each
exception (any kind) the rule default plan is what runs, and a cheap no-AI
check decides whether the shift lead is asked at all:

- **Gate** (`rule_trigger` in `resilimes/agents/sim_select.py`): the twin forks
  the **rule default alone** over the same fork horizon and futures as the
  selection (default 8 h × 3 resampled futures). No model is involved.
- **Trigger** (pre-registered, not tuned): escalate only if the rule default
  is projected, as the mean over the futures, to cause **≥ 1 avoidable Q-time
  violation** or **≥ 1 late hot/VIP lot** inside the fork horizon.
  "Avoidable" is the hard Q-time notion of PR #46
  (`hard_qtime.miss_class`, [HARD_QTIME.md](HARD_QTIME.md)): misses after a
  breakdown of the fork's sampled future, disruptions (target down / PM,
  rework, transport) and pre-gate windows are unavoidable and do not trigger.
  "Late hot lot" is the fork's `hot_late`: a hot or VIP lot due inside the
  horizon that misses its due date.
- **Otherwise** there is no escalation and no LLM call; the decision log
  records the exception with `escalated: false`,
  `escalation_reason: "rule_ok"` and the gate's projected KPIs.
- When escalated, the gate's default score is reused as the default row of
  the numbers table (same snapshot, same futures), so only the alternative
  plans are forked again. `escalation_reason` names the trigger
  (`avoidable_qtime` or `hot_late`).
- `summary()` and the study report count `exceptions`, `rule_handled`,
  `escalated`, `escalation_triggers`, `gate_checks`, `gate_forks` and
  `gate_wall_s` (wall-clock of the gate). The study prints them per run.
- **Experiment switch, off by default:** `SHIFT_LEAD_ESCALATE=always` restores
  the old kind filter (breakdown, pm_conflict, hot_insertion and
  batch_underfill always; qtime_competition only if the engine's best option
  is projected to save ≥ 2 Q-time violations), logged as
  `escalation_reason: "filter"` when not escalated.

Why: in a live run the kind filter escalated 49 exceptions in 7.6 simulated
hours, each with a Nemotron call plus twin forks, so one 24 h seed took about
5 h. A fab shift lead is asked only when there is a real problem.

### Measured: rules first vs the old filter (MOCK, no LLM)

**Mock / no-LLM measurement, not a model result.** Arm `sim_mock` (canned
replies, no Nemotron call), book `heldout_published`, seed 9, 8 h horizon,
fork 8 h × 3 futures, workers 3, llm-timeout 1200 s (the `run_live_eval.py`
config). The trigger above was fixed before this run and not tuned on it.

| | exceptions | escalated | handled by rule | LLM calls | twin forks | gate wall s (p50 / p95 per check) | run wall s |
|---|---|---|---|---|---|---|---|
| before (`main` b1799d2, kind filter) | 91 | 51 | 40 (44 %) | 102 | 612 | – | 288.6 |
| after (rules first, default) | 93 | **0** | **93 (100 %)** | **0** | 279 (gate only) | 126.7 (1.41 / 2.12 s) | 131.5 |

On this seed the twin never projected the rule default to cause an
avoidable Q-time miss or a late hot lot: the gate's mean `qavoid` was 0 in
89 checks and 0.67 in 4 (below the pre-registered ≥ 1), and `hot_late` was 0
in all 93. The run's Q-time violations (7) and waiting time (5419 vs 5421 min
before) are unchanged within noise. The exception count differs (91 vs 93)
because the old run made 5 non-default choices, which changed the trajectory.
Gate cost is about 1.4 s per exception (3 forks), with no model call. With
zero escalations a live run on this seed makes no Nemotron calls. One seed
and 8 h show the gate works and what it costs. They do not show that
avoidable misses are rare in general: HARD_QTIME.md finds about 24 avoidable
misses per 7-day run, roughly 1 per 8 h.

## Study (honest benchmark)

`python -m resilimes.smt.sim_select_study --arms ...` — same held-out seeds
(9–13, book `heldout_published`), 24 h horizon, fork 8 h × 3 futures. All
settings were fixed before the held-out runs; nothing was tuned on them.

| arm | what |
|---|---|
| `rules` | pure dispatch rules, no shift lead |
| `heuristic` | existing shift lead, deterministic stand-in (not an LLM) |
| `sim` | twin + engine plans + pareto pick (no model) |
| `sim_hmem` | `sim` + H-MEM (twin skipped on repeated "default held" cases) |
| `sim_mock` | `sim` with the offline mock in both lanes — **pipeline check, not a model** |
| `sim_llm` | Nemotron via Nightshift proposes and selects — **real, run on the PC** |
| `sim_llm_hmem` | `sim_llm` + H-MEM cases in both prompts — **real, run on the PC** |

### Results on the box (LLM-free arms; no model involved)

**Real simulation results, no LLM** (`sim` uses the deterministic rule
proposer + Pareto selector). Book `heldout_published`, 24 h horizon,
seeds 9–13, fork horizon 8 h, 3 resampled futures. Δ is paired against `rules`,
W/T/L counts seeds where the arm is better/tied/worse than `rules`.

| arm | wt min (mean) | Δwt vs rules | W/T/L (wt) | Q-time viol. | ΔQ vs rules | W/T/L (Q) | on-time % | escalations/run | wall s/run |
|---|---|---|---|---|---|---|---|---|---|
| rules | 14355.3 | 0 | – | 38.2 | 0 | – | 25.0 | – | 52 |
| heuristic (one-step lookahead, no twin) | 15082.6 | +727.3 | 0/0/5 | 42.6 | +4.4 | 1/0/4 | 25.0 | – | 77 |
| sim (twin + Pareto) | 14411.5 | **+56.2 (worse)** | 1/0/4 | 36.0 | **−2.2 (better)** | 4/1/0 | 25.0 | 143 | 1730 |
| sim_hmem (twin + Pareto + H-MEM) | 14332.9 | −22.4 (better) | 4/0/1 | 37.0 | −1.2 (better) | 3/0/2 | 25.0 | 150 (≈58 twin skips) | 718 |

Per seed (wt / Q-viol): rules 14549.5/40, 13932.4/41, 14332.8/38, 14452.9/35,
14508.9/37; sim 14680.6/36, 13976.4/40, 14301.2/37, 14520.0/35, 14579.4/32;
sim_hmem 14498.4/37, 13859.8/42, 14326.4/36, 14445.2/37, 14534.6/33.

Honest reading: the twin trades a little waiting time (+0.4 %) for fewer
Q-time violations (−5.8 %, never worse on any seed). It is not a clear win on
waiting time, and on-time % does not move in 24 h. Five seeds and one horizon
are too few for significance; nothing was tuned on these seeds. The plain
look-ahead heuristic is worse than rules on every seed, which is why the twin
(resampled futures) is the part worth keeping. With H-MEM, about 39 % of
escalations skip the twin (≥3 matching past cases where the rule default
held) and keep the rule default; that recovers the waiting-time loss
(−22 min vs rules, 4/0/1) while keeping part of the Q-time gain (−1.2 vs
rules, but +1.0 vs `sim`). Differences are within ~0.5 % and not
significant at 5 seeds. Wall-clock is not comparable across arms (box load
varied). The mock-LLM plumbing arm (`sim_mock`, canned replies, not a model result) is labelled MOCK and is a plumbing check only; see `study_sim_select/report.md`.

### Live arms (Nemotron) — run on the PC

Not run on the box (no Nightshift there). One command runs both live arms on
all five held-out seeds (plus H-MEM warm-up on dev seeds 1–3) and the LLM-free
baselines for paired deltas; it is resumable and prints progress:

```powershell
cd <repo>
git fetch origin; git checkout shift-lead-sim; git pull
python -m pip install -r requirements-dev.txt
python scripts\probe_nightshift.py            # ~5 min; writes probe_nightshift.json (no token in it)
python scripts\run_live_eval.py               # all live arms, sequential, resumable
type study_sim_select_live\report.md
```

Budgets are for runtime and safety only: no cap on escalations, 1200 s per
call, `NEMOTRON_MAX_TOKENS=16384`, `METERLESS_TIMEOUT_S=900`,
`LLM_MAX_RETRIES=5` (override via env/.env). A call that still fails falls
back to the rule default and is reported per cause.

## Files

- `resilimes/smt/simulate.py` — `make_sim`, `run_until` (chunked == whole run, tested)
- `resilimes/smt/twin.py` — snapshot, resampled futures, spawn pool
- `resilimes/agents/sim_select.py` — filter, plan DSL + guardrails, selectors, `SimShiftLead`
- `resilimes/llm/mock.py` — mock lanes `shift_lead_plan` / `shift_lead_select`
- `resilimes/smt/sim_select_study.py`, `scripts/run_live_eval.py`, `scripts/probe_nightshift.py`
- tests: `test_run_until.py`, `test_twin.py`, `test_sim_select.py`, `test_sim_select_study.py`
