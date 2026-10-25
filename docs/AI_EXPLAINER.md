# AI late-lot explainer

Advice only. The explainer never changes dispatch, KPIs or the default demo; it lives behind
`/api/ai/explain*` and the **AI evidence** tab.

## What it does

For one late lot of a 48 h run (seeds 1 and 2):

1. **Exact split (deterministic).** `Toolkit.lot_lateness` splits the lateness into buckets
   (processing, setup, transport, tool down, PM, batch wait, lots ahead, Q-time, AI decision,
   other dispatch, release hold, already late at the start). The raw split is exact to float
   precision (`decompose`), and the shown minutes are rounded with largest-remainder so they
   **add up exactly** to the shown lateness. `exact_split` checks both; tests check every late
   lot of a 24 h run.
2. **Evidence.** `lot_lateness` + `lot_waits` (the longest waits: step, family, window, bucket
   minutes, and `no_wait_late_min` = how late the lot would be with zero waiting; positive means
   the due date was infeasible even with no queues).
3. **Explanation + one counterfactual.** The model (Nemotron live, scripted stand-in in mock)
   returns JSON `{explanation, dominant, counterfactual: {lever, family, expected_saving_min,
   claim}}`. Levers: `prioritise` (make it the hot lot), `clear_down` (no tool down at that
   family while the lot waited), `skip_pm` (defer PM at that family while it waited). Up to 2
   schema repairs; every number in the text is fact-checked against the evidence (1 repair, then
   flagged).
4. **Verification by one re-run.** `verify` re-runs the same seed with the lever applied
   (`record_run(hot_lot=…)` or `drop_downs` / `drop_pm` over the lot's wait windows) and
   measures the real saving. **Hit** = saving > 0 and saving >= 50% of the expected saving.

## Metrics

| metric | meaning |
| --- | --- |
| exact_sum / shown_sum_ok | raw and shown splits add up to the lateness (target: all lots) |
| fact_ok | explanation + claim pass the fact check |
| dominant_match | model's dominant bucket = largest while-late bucket |
| cf_hit | counterfactual confirmed by the re-run (main AI metric) |
| cf_helped | re-run saving > 0 at all |
| mean_saving_min | mean re-run saving |

## Time budgets

Line-side use: never block the operator. Each lot gets `AI_TASK_DEADLINE_S` (default 180 s;
`explain(..., deadline_s=)`), and each model call `AI_CALL_DEADLINE_S` (90 s) with the
`meterless-ttfb-ms` header, as in [AI_INVESTIGATOR.md](AI_INVESTIGATOR.md#time-budgets). The
deadline is checked before every model call; on timeout the answer has `timeout: true`,
`error: "timeout: ..."` and no lever, while the exact lateness split and evidence
(deterministic) stay. `elapsed_s` is recorded per lot; the study summary adds
`elapsed_s_p50`, `elapsed_s_p95` and `timeouts`.

## Results

**MOCK (scripted stand-in, not a model), seeds 1+2, 48 late lots, 6 min 40 s on the box:**
exact 48/48, shown sums 48/48 (max residual 9e-11 s), fact_ok 48/48, 0 repairs,
CF hit **8/48**, saving > 0 on 25/48, mean saving 32.3 min. The stand-in always picks
`prioritise` and its dominant bucket matches by construction, so it is a floor, not a result.
Note: priority can also make a lot *later* in the re-run (knock-on batching/setup effects); the
re-run is exactly what catches such advice.

**REAL (Nemotron via Nightshift):** pending the PC run below.

## Running it

Box / CI (mock):

    RESILIMES_MODE=mock python -m resilimes.insight.study explainer --provider mock

User PC, everything live in one go (investigator 24 cases, explainer 48 lots, handover when
merged), with a progress line per arm and partial results after every item:

    cd C:\code\ResiliMES-AI
    powershell -ExecutionPolicy Bypass -File scripts\run_ai_evals.ps1

**Model check:** every row records `response_models`, the model each response reported (`provider_model` from the API response; `unreported:<requested>` if the response named none). Each arm summary has `model_audit`, `summary_nightshift.json` has `model_check`, the progress line shows a `non-nemotron` count, and the script ends with `MODEL CHECK OK` or `MODEL CHECK FLAG`.

Explainer only: `-Arms explainer`. Output: `outputs\ai_eval\explainer_nightshift.json` and
`summary_nightshift.json`. Expect roughly 15–25 min for the explainer arm (one LLM call or a few
per lot plus a ~10 s re-run).

## API

- `GET /api/ai/explainer/lots?seed=1` – late lots of the 48 h run (base run cached per seed).
- `POST /api/ai/explain {"lot_id": "...", "seed": 1, "lang": "en|zh|ja"}` – split, lateness,
  explanation, verified counterfactual, `advice_only: true`.
