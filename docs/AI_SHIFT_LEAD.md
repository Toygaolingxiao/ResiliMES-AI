# AI shift lead (AI班长)

The dispatcher stays 100% rule-based. The AI shift lead steps in only at the
**exception points** where a human shift lead would step in, never on every
dispatch. At each one, the scheduling engine builds 2–4 *legal* options and
projects their impact. A decider (an LLM, or a deterministic stand-in) picks
one option. The answer is validated, and anything wrong falls back to the
rule default. Every decision is logged and replayable.

With the twin (`SimShiftLead`, [AI_SIM_SELECT.md](AI_SIM_SELECT.md)) the
rule is stricter: rules first, and the AI shift lead is asked only when a
no-AI twin check projects the rule default to cause an avoidable Q-time
violation or a late hot/VIP lot. Every other exception is handled by the
rule default and counted as `rule_ok`.

| Piece | File |
|---|---|
| Exception detection, options, impact projection | `resilimes/smt/exceptions.py` |
| Deciders, prompt, guardrails, levers, decision log | `resilimes/agents/shift_lead.py` |
| Engine hook (off by default) | `resilimes/smt/simulate.py` (`shift_lead=` kwarg) |
| Offline mock answer (lane `shift_lead`) | `resilimes/llm/mock.py` |
| Study CLI | `resilimes/smt/shift_lead_study.py`, `python -m resilimes.smt.qtime_study shift_lead` |
| Tests | `tests/test_shift_lead.py` |

## Design

### Hook into the simulator

`run_policy(..., shift_lead=ShiftLead(decider))` works only with
`policy="resilimes"`; any other policy raises `ValueError`. The default is
`None`, and with `None` every hook is skipped or adds `0.0`, so the event
trace is **bit-identical** to a run without the feature. A `RuleDefault` lead
is also bit-identical, because the rule default is always a no-op lever. Both
cases are tested and checked by event-trace hash. The hook touches four
places:

1. `tick()`: after `plan_holds`, it calls `lead.on_tick(sim, t)`. That call
   expires old levers, detects exceptions, and handles at most
   `max_per_tick` (8) of them.
2. Urgency (`cheap`, `rank`, `build_schedule`): it adds `lead.bias(lot, step)`
   inside the lot's urgency band. The bias is `0.1 × prio` with
   `|bias| < 0.5`. It can reorder lots *within* a band, but it never moves a
   hot lot below a normal one.
3. `eligible()`: a pinned lot whose scanner is down may be kept on its pin
   (no reroute) if the lead chose to wait for the repair.
4. `batch_rule()`: after the minimum fill is met, the lead may start an
   under-filled batch now instead of waiting up to the rule cap. The start
   reason is `shift_lead`, which is listed in `invariants.UNDER_MIN_REASONS`.

PM deferral changes the tool's PM window in `sim.pm` directly. Each PM window
can be deferred only once, by at most 120 min, and only into free time.

### Exception types

| Type | Trigger | Options (A = rule default) |
|---|---|---|
| `breakdown` | A litho scanner goes down while lots are pinned to it (layer dedication) | A re-route every pinned lot to a sibling now · C re-route only Q-time/hot lots, the rest wait · B wait for the repair |
| `qtime_competition` | Q-time lots compete for one family, and the rule order projects ≥1 Q-time miss in the next 2 h | A keep rule order · B Q-time lots first (tightest latest start) · C triage: boost only windows that can still be met · D Q-time first, but due-critical lots keep their place |
| `hot_insertion` | Same as above, but hot/VIP lots sit ahead of the Q-time lots because of their class | Same options. A keeps hot/VIP first. The guardrail rejects any option that makes a hot lot late |
| `pm_conflict` | A PM starts within 2 h on a tool whose family has Q-time lots projected to miss | A keep the PM · B/C/D defer by 30/60/120 min (only if `pm_shift_ok`) |
| `batch_underfill` | A furnace family has idle tools, and a recipe batch meets the minimum but not the target fill, so the rule waits | A wait for more lots (until the rule cap) · B start now with what is there |

**Impact projection** (`project()`) is a short, family-local list-scheduling
model. It covers the next 2 h for one family: queued plus inbound lots (≤60),
tool availability, PM windows, and the lever under test. It returns
`qtime_violations`, `hot_late`, `late_lots`, `idle_min` and `queue_growth`.
Lower is better. A lot's lateness uses a flow-aware base:
`due − remaining_process − flow_wait × max(0, remaining − cycle)`.

### Deciders

* `LlmDecider(completer)` uses the existing `resilimes.llm` factory, on lane
  `shift_lead` at temperature 0. It works with Nightshift live, or with
  `MockProvider` offline, which is deterministic in CI.
* `HeuristicStandIn` is **not an LLM**. It picks the option with the lowest
  projected impact in lexicographic order: Q-time violations, then hot late,
  then late lots, then idle minutes. A tie keeps the default. This is the
  study arm.
* `RuleDefault` always picks the rule default. It is identical to running
  with no lead.

`build_decider("heuristic"|"rules"|"mock"|"nightshift")`. Choosing
`nightshift` raises an error unless the settings select Nightshift
(`RESILIMES_MODE=live` plus the Nightshift settings).

## Guardrails

Every answer passes through `check_option()`. Any failure falls back to the
**rule default**, which is a no-op, and the cause is written to
`fallback_cause`:

| Cause | When |
|---|---|
| `timeout` | No reply within `timeout_s` (default 30 s, daemon thread) |
| `provider_error` | The completer raised an error |
| `bad_json` | No JSON object, or `option_id` missing |
| `unknown_option` | The id is not one of the offered options |
| `invariant: makes a hot/VIP lot late` | Projected `hot_late` is above the default's |
| `invariant: PM deferral out of bounds` | More than 120 min, already started, overlaps another PM, or already deferred |
| `invariant: boost/pin outside the exception's lots` | The lever touches lots that were not in the exception |
| `invariant: batch outside the exception's family` | The lever starts a batch in a different family |
| `budget` | The optional per-run LLM call budget (`--budget N`) is used up |
| `error: <Type>` | Any other exception while deciding or applying |

The LLM never writes a schedule. It only picks from options that the engine
has already built as legal. Each lever expires: priorities after 1 h, a kept
pin at the repair ETA, and a batch start at the rule cap time.

## Prompt format

There are two messages. The system message sets the role and the reply
contract:

> You are the shift lead of a 300 mm wafer fab. The dispatcher runs on rules;
> you are asked only at exceptions. … Choose exactly one offered option. Reply
> with one JSON object only: `{"option_id": "<id>", "reason": "<one short sentence>"}`.

The user message is one compact JSON object:

```json
{"time_h":5.25,"exception":"breakdown",
 "situation":"Litho_FE_92-9 is down until 32.2 h; 1 lots pinned to it (litho layer dedication), 0 of them Q-time or hot/VIP",
 "facts":{"...":"..."},
 "options":[{"id":"A","action":"re-route every pinned lot to a sibling scanner now","rule_default":true,
             "impact":{"qtime_violations":0,"late_lots":0,"hot_late":0,"idle_min":577.5,"queue_growth":-1}},
            {"id":"B","action":"wait for the repair (ETA 32.2 h) for every pinned lot","rule_default":false,
             "impact":{"qtime_violations":0,"late_lots":0,"hot_late":0,"idle_min":652.5,"queue_growth":0}}],
 "goal":"Optimise the whole fab, not one product: keep the load level across tool families ... Protect Q-time windows first. Respect hot and VIP lots: never pick an option that makes one late. ...",
 "answer":{"option_id":["A","B"],"reason":"one sentence in Simplified Chinese, at most 40 words","lang":"zh"}}
```

The reason language is `zh`, `ja` or `en` (`--lang`). A typical prompt is
about 1–2 KB.

## Decision log schema

`ShiftLead.log` is a list of dicts. On a recorded run, each entry is also
appended to the run's events as `("ai_decision", t, entry)`.
`decision_rows(events)` turns those into `(t, "ai_decision", body)` rows
labelled **AI判断** for the replay and event-log API.

| Field | Meaning |
|---|---|
| `id` | `X00042` (sequence per run) |
| `t`, `t_h` | Sim time in seconds / hours |
| `type` | One of the five exception types |
| `family`, `tool` | Where it happened |
| `lots` | Lot ids involved (≤12) |
| `situation` | One-line description |
| `options` | `[{id, action, rule_default, impact{...}}]` |
| `default`, `chosen`, `action` | Rule default id, applied id, applied action |
| `differs` | `chosen != default` |
| `reason` | The decider's reason (zh/ja/en) |
| `provider`, `model`, `latency_ms` | Who decided and how fast. A mock answer reads `mock (mock)` |
| `fallback`, `fallback_cause` | Whether the rule default was forced, and why |

Sample (mock provider, published book, seed 1):

```json
{"id":"X00042","t":18900.0,"t_h":5.25,"type":"breakdown","family":"Litho_FE_92",
 "tool":"Litho_FE_92-9","lots":["Init_Lot_4_120"],
 "situation":"Litho_FE_92-9 is down until 32.2 h; 1 lots pinned to it (litho layer dedication), 0 of them Q-time or hot/VIP",
 "options":[{"id":"A","action":"re-route every pinned lot to a sibling scanner now","rule_default":true,"impact":{"qtime_violations":0,"late_lots":0,"hot_late":0,"idle_min":577.5,"queue_growth":-1}},
            {"id":"B","action":"wait for the repair (ETA 32.2 h) for every pinned lot","rule_default":false,"impact":{"qtime_violations":0,"late_lots":0,"hot_late":0,"idle_min":652.5,"queue_growth":0}}],
 "default":"A","chosen":"A","action":"re-route every pinned lot to a sibling scanner now","differs":false,
 "reason":"模拟（非模型）：选择预测影响最低的选项。","provider":"mock (mock)","model":"resilimes-mock",
 "latency_ms":0.1,"fallback":false,"fallback_cause":null}
```

`ShiftLead.summary()` reports these counts: exceptions by type, how often the
choice differs from the default (overall and by type), fallbacks by cause,
and latency p50/p95.

## Study: rules-only vs heuristic stand-in

```
python -m resilimes.smt.qtime_study shift_lead --provider heuristic --workers 2 \
    --out /path/study_heuristic.json
```

The setup has 4 books (published, litho, hot, pm_enforced), seeds 1–3, a
48 h horizon, the `resilimes` policy and 2 worker processes. The run takes
about 2.5 min. `pm_enforced` was added because it is the only book whose PM
windows fall inside 2 days. In the other books the first PM starts after 48 h,
so `pm_conflict` cannot fire there. The arm is the **heuristic stand-in, not
an LLM**.

**Exceptions over all 12 runs** (about 330–480 per 2-day run):

| Type | Detected | Differs from default |
|---|---:|---:|
| breakdown | 93 | 3 |
| qtime_competition | 4422 | 3026 |
| hot_insertion | 253 | 140 |
| pm_conflict | 13 | 6 |
| batch_underfill | 28 | 7 |

There were 0 fallbacks: the stand-in only picks offered, guarded options.

**KPIs, rules → stand-in:**

| book | seed | on-time % | Q-time violations | weighted tardiness (min) |
|---|---|---|---|---|
| published | 1 | 57.14 → 57.14 | 86 → 64 (−22) | +868 (+4.5%) |
| published | 2 | 57.14 → 55.36 | 59 → 71 (+12) | +801 (+4.0%) |
| published | 3 | 55.36 → 57.14 | 87 → 89 (+2) | +2467 (+12.6%) |
| litho | 1 | 57.14 → 57.14 | 102 → 79 (−23) | +1077 (+5.6%) |
| litho | 2 | 57.14 → 55.36 | 54 → 66 (+12) | +896 (+4.5%) |
| litho | 3 | 55.36 → 57.14 | 89 → 90 (+1) | +2566 (+13.2%) |
| hot | 1 | 56.14 → 56.14 | 80 → 63 (−17) | +1228 (+5.0%) |
| hot | 2 | 56.14 → 54.39 | 56 → 64 (+8) | +695 (+2.8%) |
| hot | 3 | 54.39 → 56.14 | 83 → 86 (+3) | +2729 (+11.0%) |
| pm_enforced | 1 | 57.14 → 57.14 | 125 → 116 (−9) | +534 (+2.6%) |
| pm_enforced | 2 | 57.14 → 55.36 | 81 → 89 (+8) | +1045 (+5.0%) |
| pm_enforced | 3 | 55.36 → 53.57 | 108 → 117 (+9) | +2283 (+11.1%) |

Mean deltas: Q-time violations −1.3, on-time −0.17 lots (−0.3 pp), weighted
tardiness +1432 min, recleans −2.2, batch starts +1.9.

**Reading.** The result is mixed and not a win.

* Seed 1 improves Q-time strongly in every book (−9 to −23 violations).
* Seeds 2 and 3 get slightly worse (+1 to +12).
* Weighted tardiness is worse in all 12 pairs (+3% to +13%), because pulling
  Q-time lots forward delays other lots.
* On-time completions move by at most ±1 lot.

The stand-in is myopic. It uses a 2 h, one-family projection and a strict
"Q-time first" order. It cannot see that a boost here starves a downstream
family, or that a lot pulled forward joins a later queue anyway. That is
exactly the trade-off the fab goal asks an LLM to weigh: whole fab, level
load, then Q-time. A live LLM run is needed to know if it does better. We
make no claim that it does.

## Caveats

* The projection is a simplified 2 h, family-local model. It is not the full
  simulator, and its numbers are estimates.
* Breakdown options use the scheduled repair ETA, which the shift lead would
  know from the maintenance ticket. Future breakdowns are never looked at,
  so this is not an oracle.
* **Volume.** About 330–480 exceptions per 2-day run, mostly
  `qtime_competition`. That is about 7–10 calls per sim-hour. For a live LLM,
  use `--budget N` (calls beyond N fall back with cause `budget`), one worker
  (forced for `nightshift`), and a single book/seed.
* PM deferral edits the static PM table of the run (`sim.pm`). The planned
  PM module (`pm_plan.py`, PR #23) is not integrated yet.
* The event-log/replay API lives on the UI branch, which is not merged into
  this base. `decision_rows()` is the adapter it should call.
* The study runs without the planning layer's plan (default kwargs), so it
  measures the lead's effect over the rule dispatcher alone.
* The mock provider's answer is a deterministic lowest-impact pick, labelled
  "模拟（非模型）". It tests the plumbing, not judgment.

## Running live with Nemotron (Nightshift)

Run this on a machine that has the Nightshift settings in `.env`, with
`RESILIMES_MODE=live`:

```
python -m resilimes.smt.qtime_study shift_lead --provider nightshift \
    --books published --seeds 1 --budget 200 --lang zh --timeout 30 \
    --out shift_lead_nightshift.json
```

Compare the result with the heuristic and rules arms (same book and seed).
Then check `fallback_causes` and latency p50/p95 in the summary.

### Watching a long run

A live run makes one slow model call per exception, so the study shows
its progress. On stderr it prints a start line, then one progress line,
redrawn in place on a terminal and printed every 10 s
(`--progress-every`) when stderr goes to a log file:

```
shift_lead 2/2 published s1 nightshift | sim 14.4/48h  30% [######--------------] | exc 30 | AI 31/200 ok 24 fb 6 (timeout 3, invalid 3) | LLM avg 12.5s last 12.5s wait 8s | 0:11:23 ETA 0:14:54
```

- `sim`: simulated time against the horizon of the current run.
- `exc`: exceptions so far. `AI`: model calls against the budget.
- `ok`: decisions accepted. `fb`: rule fallbacks, by reason: timeout,
  invalid (bad JSON or unknown option), guardrail, budget, or error.
- `LLM`: average and last call latency. `wait`: a call is in flight.
- Elapsed time and ETA. `ETA >…` is a lower bound, used while no run of a
  later arm has finished yet.

The line is plain ASCII, so it works in a cp932 Windows console. The same
numbers go to `<out>.progress.json` every 2 s through an atomic replace, with
`status` running, done or failed. Change the path with `--progress-file`
(`''` writes no file), or turn both off with `--no-progress`. The other
qtime_study arms print a line per finished run and write the same file;
`RESILIMES_STUDY_PROGRESS=0` turns that off.

`GET /api/shift-lead/status` returns the newest progress file, with `age_s`
and `stale` (running, no update for 60 s). The file comes from
`RESILIMES_PROGRESS_FILE`, or else the newest in `RESILIMES_PROGRESS_DIR`
(default: the server's working directory). The console shows it as a card
with a bar under the rail. Results are the same with progress on or off.
