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
- **SQL.** The `sql` tool goes through the PR #30 guard: SELECT only, allowlisted tables, and an
  enforced LIMIT.
- **Schema.** The final answer must be JSON with a cause from the taxonomy and citations that point
  to real calls. Up to 2 schema repairs are allowed.
- **Fact check.** Every number and id in the answer must appear in a tool result or in the
  question. A failing answer gets one rewrite. Anything still unknown is returned in
  `fact_misses`, and the UI flags it.
- **Secrets.** Errors are redacted before they are printed or saved.

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

`python -m resilimes.insight.study investigator --provider mock` (24 cases, 65 s):

| Arm | top-1 | top-2 | fact check passed | tool calls |
| --- | --- | --- | --- | --- |
| Biggest-anomaly baseline | 21/24 | 22/24 | n/a | n/a |
| Mock stand-in | 21/24 | 22/24 | 24/24 (0 repairs) | 6.0 |

By fault (top-1): tool down 4/4, PM in peak 4/4, release burst 4/4, setup thrash 3/4, batch cap
2/4, upstream starvation 4/4.

The baseline misses `setup_thrash-s2`, `batch_cap-s2` and `batch_cap-s3`. In all three, arrivals
rose more, relative to the 4 h before, than the faulted metric did, so "release burst" scored
highest. These are the cases where
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
- **Mock stand-in.** It now calls `compare_windows` first. Its answers still equal the baseline's.

Cases, seeds, weights and scoring are unchanged. The re-run result will be added here.

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
