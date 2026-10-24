# AI shift lead: propose → fork → simulate → select

Branch `shift-lead-sim`, stacked on `shift-lead-progress` (#28) → `ai-shift-lead` (#24).
**Off by default.** Nothing in the app, the API or `run_policy` uses it; it runs
only when a study arm or a caller builds `SimShiftLead` explicitly.

## What it does

At an *escalated* exception the shift lead:

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

Escalation filter (pre-registered, not tuned): breakdown, pm_conflict,
hot_insertion and batch_underfill always; qtime_competition only if the
engine's best option is projected to save ≥ 2 Q-time violations over the
default. Everything else is handled by the plain rule default.

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
