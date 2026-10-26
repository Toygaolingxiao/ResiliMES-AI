# AI investigator

Ask "why did the WIP of family F double between t1 and t2?" The investigator reads simulator
evidence through the typed toolkit (`resilimes/evidence`), using at most **6 tool calls**. It then
names one primary cause from a fixed taxonomy, writes a short causal chain, and suggests one lever.
The lever is **advice only**: nothing is applied to the plan, and no existing KPI or endpoint changes.

## Pieces

| Piece | File |
| --- | --- |
| Fault injector, 6 faults × 4 seeds with ground truth | `resilimes/insight/injector.py` |
| Bounded tool loop, fact check, biggest-anomaly baseline | `resilimes/insight/investigator.py` |
| Study CLI with a progress line | `resilimes/insight/study.py`, `resilimes/insight/progress.py` |
| The 24 committed cases | `eval/investigator_cases.json` |
| API | `GET /api/ai/investigator/cases`, `POST /api/ai/investigate {"case_id"}` |
| UI | **AI evidence** tab, Investigator panel (`resilimes/demo/static/ai.js`) |

### Taxonomy

`tool_down`, `pm_in_peak`, `release_burst`, `setup_thrash`, `batch_cap`, `upstream_starvation`.

### How the 24 cases are made

The injector uses a 16 h SMT2020 run, with the fault window from 6 h to 12 h. For each seed and
fault, it picks a family and applies one fault:

| Fault | What it does to the simulation |
| --- | --- |
| tool down | Half of the family's tools are unscheduled down for the whole window. |
| PM in peak | Half of the tools are in PM for 4 h at the family's arrival peak. |
| release burst | Lots heading for the family are held, then released together at 6 h. |
| setup thrash | Every changeover gets an extra 45 min of setup. |
| batch cap | A batch family is capped to 25 wafers per start. |
| upstream starvation | Every tool of the main feeding family is down, so the family drains. |

A case is kept only when the symptom is real. For a rise, WIP must go up by at least 1.5× (and by
6 lots or more) against the same family's unfaulted run. For starvation, the family must fall to
half or less. The question says "double" only when WIP at least doubled; otherwise it says "rise"
or "fall". Cases are deterministic. `python -m resilimes.insight.study cases` rebuilds the JSON
in about 4 minutes.

### Guard rails

- **Tool budget.** The loop stops at 6 tool calls (10 turns in total) and then asks for the final
  answer.
- **Repeat stop.** A tool call with the same tool and the same normalized args as an earlier
  call is not run; see [Loop controls](#loop-controls).
- **SQL.** The `sql` tool goes through the PR #30 guard: SELECT only, allowlisted tables, and an
  enforced LIMIT.
- **Schema.** The final answer must be JSON with a cause from the taxonomy and citations that point
  to real calls. Up to 2 schema repairs are allowed.
- **Fact check.** Every number and id in the answer must appear in a tool result or in the
  question. A failing answer gets one rewrite. Anything still unknown is returned in
  `fact_misses`, and the UI flags it.
- **Secrets.** Errors are redacted before they are printed or saved.

### Loop controls

Program-side controls, on top of the tool budget and the fact check. Prompts are unchanged.

- **Repeat stop.** Args are normalized (key order, `6` / `6.0` / `"6"`, whitespace) and compared
  with every earlier call in the case. A repeat is not executed: the model is told it already has
  that evidence in `RESULT n` and must give the final answer now, and the tool phase ends. If it
  asks for another tool instead of answering, the loop stops with no answer (degraded route).
- **Per-round trace.** `Investigation.trace` has one entry per round (LLM turn): `round`,
  `action` (tool name or `answer`), `args`, `status` (`executed`, `repeat`, `over_budget`,
  `tool_phase_closed`, `accepted`, `schema_repair`, `fact_check_repair`, `invalid`,
  `format_retry`, `error`), and for executed calls a short `evidence` summary (result size in
  chars, top-level keys, list sizes, and for `compare_windows` each cause's relative change), never
  the payload. `stop_reason` is one of `answered`, `budget_exhausted` (a call was refused over
  budget, then answered), `repeat_call`, `fact_check_repaired` (the one rewrite passed the fact
  check), `degraded_to_rule` (below) or `error` (the rule answer itself could not be computed).
  Provider errors keep their redacted message in `error`, not just the exception type. The trace
  and `stop_reason` are in the study rows (`stop_reasons` counts in the summary), in
  `POST /api/ai/investigate` under `answer`, and in the console as a collapsed "Loop steps" list
  under the Investigator card.
- **Degraded route (縮退).** When the AI answer still fails the fact check after the one rewrite
  (`fact_check_failed`), there is no valid answer (`no_answer`: turn limit, invalid final, or a
  tool call after the repeat stop), the provider fails (`provider_error`), or the time budget runs out (`timeout`, see Time
  budgets), the system output
  becomes the rule baseline's answer: `degraded: true`, `degrade_reason`, and
  `system = {"source": "rule", "primary_cause", "secondary_cause", ...}`. Otherwise
  `system.source` is `ai`. The AI's own answer (`primary_cause`, `causal_chain`, ...) and its
  `fact_misses` stay in the record; nothing is hidden. The console shows a "Degraded: rule answer
  (reason)" line above the AI answer.
- **Scoring stays separate.** The study summary reports `ai_top1` / `ai_top2` (the AI's own
  answer, scored exactly as before: a no-answer or provider error is an AI miss, and a
  `fact_check_failed` answer is still scored by its own flagged cause, as it was before) and
  `system_top1` / `system_top2` (what the operator sees, after the degraded route), plus
  `degraded_count` and `degraded_by_reason`. They are never merged into one number.
- **Explainer and handover** are unchanged here. They keep their existing behaviour: a failing
  answer is flagged (`fact_ok: false`, `fact_misses`, `error`), not replaced.

### Time budgets

Line-side use: the AI is advice next to a running line, so it must never block the operator.
Two wall-clock budgets bound every answer (`resilimes/llm/deadline.py`, monotonic clock):

- **Per model call: `AI_CALL_DEADLINE_S` (default 90 s).** Each Nightshift request gets
  `timeout = min(call time left, task time left)` (never above `METERLESS_TIMEOUT_S`, 180 s) and
  the header `meterless-ttfb-ms` = min(timeout, `AI_TTFB_S` = 60 s) in ms, at most 300000, so
  Nightshift stops a lane that has not produced a first token. The empty-reply ladder
  (4k → 8k → 16k tokens) does not start another rung with less than 30 s left in the call or the
  task; retries do not sleep past the deadline. A client timeout raises `DeadlineExceeded`.
  These limits apply only to calls made inside an AI task deadline (investigator, explainer,
  handover); the sim-select / shift-lead studies keep their own long `METERLESS_TIMEOUT_S`.
- **Per task: `AI_TASK_DEADLINE_S` (default 180 s)** per investigator case (`investigate(...,
  deadline_s=)`). The deadline is checked before every model call and every tool round; when it
  is gone the loop stops, the round's trace status is `timeout`, and the case takes the degraded
  route: `degrade_reason: "timeout"`, `stop_reason: "degraded_to_rule"`, system answer = rule
  answer. A provider `DeadlineExceeded` is the same timeout.
- **Recorded.** Every trace round has `elapsed_s`; each case has `elapsed_s` and `timed_out`. The
  study rows carry `elapsed_s` / `timeout`; the summary adds `elapsed_s_p50`, `elapsed_s_p95` and
  `timeouts`. A timeout is an AI miss in `ai_top1` (even if a half-finished answer named the
  right cause) and counts as degraded in `system_top1` and `degraded_by_reason`.
- The mock stand-in finishes in well under a second, so mock/CI numbers are unchanged. Note that
  real 16k-token answers have taken 34–63 s; a 60 s first-token limit can cut the slowest ones.

### Baseline

The biggest-anomaly baseline scores each cause by the relative change of its metric. It compares the
window [t1, t2) with the 4 h before t1. The metrics are down hours, PM hours, arrivals, setup
minutes per start, lots per batch start, and down hours at the main upstream family. The baseline
ranks the causes by that change. The investigator is scored top-1 and top-2 against the injected
fault, side by side with the baseline.

## Results

### Mock (offline stand-in, CI) — not a model result

Without Nightshift, the "model" is a scripted stand-in. It runs the same loop, budget and fact check.
It makes six fixed calls, then answers with the baseline's top two causes. Its accuracy therefore
**equals the baseline by construction**. These numbers check the plumbing; they are not a measure of
the model.

`python -m resilimes.insight.study investigator --provider mock` (24 cases, about 100 s):

| Arm | top-1 | top-2 | fact check passed | tool calls |
| --- | --- | --- | --- | --- |
| Biggest-anomaly baseline | 20/24 | 21/24 | n/a | n/a |
| Mock stand-in | 20/24 | 21/24 | 24/24 (0 repairs) | 6.0 |

By fault (top-1): tool down 4/4, PM in peak 3/4, release burst 4/4, setup thrash 3/4, batch cap
2/4, upstream starvation 4/4. All 24 mock cases stop with `answered`, none is degraded, so the
system score equals the AI score (20/24 top-1, 21/24 top-2).

The baseline misses `pm_in_peak-s1`, `setup_thrash-s2`, `batch_cap-s2` and `batch_cap-s3`. In all
four, arrivals rose more, relative to the 4 h before, than the faulted metric did, so "release
burst" scored highest. These are the cases where
reading the evidence (setup minutes per start, lots per batch start) has to beat a single metric.

### Real (Nemotron via Nightshift)

Run on the PC (below); the build box has no Nightshift. It writes
`outputs/ai_eval/investigator_nightshift.json` with the same summary fields, labelled
`real:<model id>`.

**First live run (before the protocol):** AI top-1 **11/24** against the rule baseline's **20/24**.
The fact check passed 22/24; the other 2 gave no answer because they hit the 10-turn limit. The
model made 2.9 tool calls on average.

Why it lost: the system prompt listed the tools and the answer format, but never said *how to
decide*. The baseline compares the window with the 4 h before t1 and picks the cause whose metric
changed most. The model read only absolute numbers in the window and followed the most visible
signal. It answered `release_burst` whenever it saw many arrivals, including batch-cap and
upstream-starvation cases where WIP fell. In one case it ranked a clear setup thrash (36.6 setup
minutes per start, 130 changeovers) as secondary because one tool was down.

**What changed (a prompt and tool fix, not tuning).**

- **Protocol in the system prompt.** Always compare the window with the 4 h before t1. Check every
  cause's indicator: down tool-hours, PM tool-hours, arrivals per hour, setup minutes per start,
  lots per batch start, and the main upstream family's down time and feed. Pick the cause whose
  indicator changed most relative to before, in the direction that points to it. If WIP falls,
  consider upstream starvation first. Answer by about turn 6.
- **New tool `compare_windows {family, start_h, end_h}`.** It returns, for each of the six causes,
  the indicator before, in the window, and its relative change. It also gives waiting lots at the
  window's start and end, and the main upstream family's down+PM tool-hours and feed into this
  family. It uses the same metrics as the baseline (`cause_indicators`), and its numbers go into
  the fact registry like every other tool. It gives **no ranking and no winner**, so the model
  still has to reason.
- **Mock stand-in.** It calls `compare_windows` first. Its answers still equal the baseline's.

Cases, seeds, weights and scoring are unchanged.

**Second live run (v2, with the protocol and `compare_windows`):** AI top-1 **20/24** against the
rule baseline's **20/24**; top-2 **21 vs 21**. The fact check passed **24/24** (4 answers needed the
one rewrite), **0** no-answers, and the model made **1.54** tool calls on average.

| Fault (top-1, of 4) | v1 | v2 | rule |
| --- | --- | --- | --- |
| tool down | 2 | 4 | 4 |
| PM in peak | 3 | 3 | 3 |
| release burst | 4 | 4 | 4 |
| setup thrash | 2 | 3 | 3 |
| batch cap | 0 | 2 | 2 |
| upstream starvation | 0 | 4 | 4 |

The v2 run predates the loop controls and the degraded route, so it has no `system_top1`. Because
v2 had 0 no-answers and all 24 answers passed the fact check, no case would have been degraded,
and the system top-1 would also be 20/24. That is an inference, not a measured value.

## PC commands

From `C:\code\ResiliMES-AI` in PowerShell, with `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN` and
`NEMOTRON_MODEL` set (or in `.env`):

```powershell
git fetch origin; git switch ai-investigator; git pull
powershell -ExecutionPolicy Bypass -File scripts\run_ai_evals.ps1
```

This runs every AI arm sequentially on Nemotron, with one progress line per arm. On this branch the
only arm is the investigator; the explainer and handover branches add theirs. Each case is saved as
soon as it finishes, so a stopped run keeps its rows. To run only the investigator:

```powershell
python -m resilimes.insight.study investigator --provider nightshift
```

The token is read from the environment and never printed. Error text is redacted before it is
saved.
