# Context investigation contract — Gantt right-click "查排程" (v2)

One endpoint answers "what is the basis for this part of the schedule?"
for a right-click on the Gantt: a lot-step **bar**, an idle **gap** on one
tool, a time **window** on one family, or a **free** question that chains
several evidence sources.

- Endpoint: `POST /api/ai/investigate` on the demo API (this is the same
  endpoint as the case library; a request with `type` is a context query,
  a request with `case_id` is the original case re-run — unchanged).
- Service: `resilimes.insight.context_investigation.investigate_context`.
- The context run is the explainer's cached 48 h base run (`seed`, default
  1), the same run the lot explainer answers from.
- Advice only (`advice_only: true`). Nothing here changes a plan.

## Three-tier honesty (decided by code, never by the model)

Every context answer carries a `tier`, assigned by the service from the
kind of evidence behind it:

| tier | meaning | wording rule |
| --- | --- | --- |
| `decision_record` | A recorded dispatch/gate decision explains it: a recorded start reason, a displacement or AI decision event, a dispatch-log gap record. | The basis may be stated directly. |
| `rule_emergent` | Only the rule and the state at the time are on record (the dispatch ranking leaves no per-decision record). | The answer must frame it as "the result of rule X under the state at the time". Model rewrites that use decision language ("decided to", "chose to", "intentionally", "in order to", …) are refused like a fact-check failure (`degrade_reason: "tier_upgrade_refused"`). |
| `unknown` | The recorded evidence does not say. | The scripted unknown text is final; the model is never asked to rewrite an unknown answer. |

For `free` answers the overall tier is the weakest tier among the parts
that make a causal claim; unknown parts are abstentions and do not drag
it down unless every part abstains. Per-part tiers are in `part_tiers`.

## Request

| field | type | notes |
| --- | --- | --- |
| `type` | `"bar" \| "gap" \| "window" \| "free"` | selects context mode and the route |
| `tool` | string | tool name as shown on the Gantt (e.g. `DE_BE_11-1`) |
| `family` | string | family name (e.g. `Litho_FE`) |
| `lot` | string | lot id (e.g. `Init_Lot_1_54`) |
| `step` | int | route step of the clicked bar |
| `t1_min` / `t2_min` | number | window bounds in **minutes** from run start — the front end's native unit; wins over hours when both are sent |
| `t1_h` / `t2_h` | number | window bounds in hours (service-native; still accepted) |
| `scenario_id` | string | echoed in the response; `"seed-<n>"` (n = 1..4) also selects the run seed |
| `lang` | `"en" \| "zh" \| "ja"` | accepted and echoed in the query; v1 answers are English (alignment point, below) |
| `question_preset` | string | per type, see below; validated |
| `question` | string | free text; the anchor question for `free`, the investigator's question for `window` |
| `seed` | int 1..4 | which base run (default 1) |

Presets: bar — `why_here`, `why_this_tool`, `why_this_time`; gap —
`why_idle`; window — `what_happened`, `why_wip_changed`; free — none
(free text only).

Required per type: bar — `lot` (plus `step` or `t1_min` to disambiguate);
gap — `tool`, `t1_min` (`t2_min` defaults to +60 min); window — `family`,
`t1_min`, `t2_min`; free — at least one anchor among `lot`, `tool`+window,
`family`+window, else the answer is `unknown` by construction.

## Response

```json
{ "context": { ...ContextAnswer }, "scenario_id": "...", "advice_only": true }
```

| field | notes |
| --- | --- |
| `query` | the query as understood (hours normalised) |
| `type` | echoed route |
| `tier` | `decision_record` \| `rule_emergent` \| `unknown` — code-decided |
| `status` | `answered` \| `unknown` |
| `answer` | the text the UI shows |
| `basis` | evidence entries `{n, kind, source, facts}`; `n` is the citation number |
| `citations` | citation numbers the answer rests on |
| `part_tiers` | free only: tier per chained source |
| `primary_cause` / `secondary_cause` | window (and free with a window part) |
| `fact_ok` / `fact_misses` | result of `evidence.factcheck.check` over the answer's own basis |
| `source` | `scripted` (deterministic) \| `llm` (model rewrite that passed the checks) |
| `degraded` / `degrade_reason` | model path fell back: `fact_check_failed`, `tier_upgrade_refused`, `bad_json`, `provider_error` (investigator reasons pass through for window) |
| `mocked` / `provider` / `model` / `error` | provenance, same convention as the other AI endpoints |

`basis[].source` distinguishes the evidence chains:
`run_record` (visit / tool / queue records), `decision_log` (recorded
displacements and AI decisions), `rule` (the ranking itself),
`gap_classifier` (gap classification), `investigator` (the window tool
loop), `fab_notes` (operator notes — context claims, not run records).

## What each type answers from

- **bar** — the visit record (ready/start/leave, the simulator-recorded
  `start_reason`, batch size, setup), the exact wait split
  (`evidence.lateness.visit_waits`: batch/pm/qtime/down/lots_ahead/…),
  queue and tool state at the start, displacements and AI decisions
  touching the lot, and the dispatch ranking (`kernel.score.tiered_key`)
  labelled as what it is: a rule recomputed at every wake. Tier:
  `decision_record` when a start reason or displacement is recorded,
  else `rule_emergent`. The ranking's per-decision winner is *not*
  recorded, and the answer says so instead of inventing an intent.
- **gap** — the tool's state split over the window, the lots waiting at
  the family with their window-clipped wait buckets, batch-step and
  Q-time-hold counts, and a gap classification (below). No waiting lot
  and no bucketed wait → `status: "unknown"`, `tier: "unknown"`, however
  suggestive the window looks. A classification on its own (e.g. a PM
  starting inside the span) is reported in `basis` but does not upgrade
  an otherwise evidence-free gap.
- **window** — routed to `insight.investigator.investigate` (the bounded
  evidence-tool loop); its answer, causes, fact-check and degradation
  pass through in the same shape. Tier `rule_emergent` when a primary
  cause is returned.
- **free** — chains, in order, whichever sources the query anchors:
  the bar record for `lot`; the gap evidence + classification for
  `tool`+window; the investigator for `family`+window; and fab notes
  whose text or extracted events mention the queried tool/family/lot.
  Each part is labelled in the text (`[Run record]`, `[Gap evidence]`,
  `[Investigation]`, `[Notes]`) and in `basis[].source`. Notes are
  labelled as people's claims, never as run records. When the
  `fab_notes` dataset is not in the build, the notes entry is a
  placeholder with `available: false` and contributes no evidence.

Gap classification: the service prefers `resilimes.insight.gaps`
(Plan-4 module) when it is in the tree — its `GapRecord` tiers map
`decision_record → decision_record`, `inferred_evidence →
rule_emergent`, `unknown → unknown`. Until the merge, an adapter mirrors
the same taxonomy, priority and evidence rules (batch / PM / CQT only —
the same v1 limit `gaps.py` itself states) and says so in the basis
facts (`classifier: "mirrored insight.gaps taxonomy …"`).

## Model use

Offline (no provider, or a mocked one) the deterministic scripted
answers are the product — CI never needs Nightshift. With a live
provider, bar/gap/free scripted answers may be rewritten once for
readability; the rewrite must pass `factcheck.check` against the
answer's own basis and stay inside the code-assigned tier (see above),
else the scripted answer is returned with `degraded: true`. Window
answers go through the investigator's own loop and checks.

## Examples (abridged; numbers schematic)

Bar, decision-record tier:

```json
POST /api/ai/investigate
{"type": "bar", "lot": "Init_Lot_1_54", "step": 399, "scenario_id": "gantt-demo"}
→ { "context": {
    "type": "bar", "tier": "decision_record", "status": "answered",
    "answer": "Init_Lot_1_54 step 399 started on Diffusion_BE_123-3 at … h; it was ready at … h and waited 465 min. The simulator recorded the start reason as 'min_met'. Its wait was split as …",
    "basis": [{"n": 1, "kind": "visit", "source": "run_record", "facts": {"lot": "Init_Lot_1_54", "start_reason": "min_met", "…": "…"}}, "…"],
    "fact_ok": true, "source": "scripted", "degraded": false, "mocked": true },
  "scenario_id": "gantt-demo", "advice_only": true }
```

Gap with no evidence — the honest answer:

```json
{"type": "gap", "tool": "DE_BE_69-3", "t1_min": 0, "t2_min": 60, "question_preset": "why_idle"}
→ "context": { "tier": "unknown", "status": "unknown",
    "answer": "DE_BE_69-3 was idle 1 h in this window, but no lot was waiting at DE_BE_69 and no recorded hold overlaps it. The recorded evidence does not say why (unknown)." }
```

Free, chained:

```json
{"type": "free", "tool": "DE_BE_11-1", "t1_min": 120, "t2_min": 180,
 "question": "Why is this tool idle in this window?"}
→ "context": { "tier": "rule_emergent", "part_tiers": {"gap_classifier": "rule_emergent"},
    "answer": "[Gap evidence] DE_BE_11-1 was idle 0.42 h between 2 h and 3 h while 2 lots were waiting at DE_BE_11. …",
    "basis": […, {"kind": "gap_classification", "source": "gap_classifier", …},
              {"kind": "fab_notes", "source": "fab_notes", "facts": {"available": false, …}}] }
```

Errors: an invalid preset, an unknown lot, or a missing required field
returns `400` with the reason; the case mode is unaffected (unknown
`case_id` still returns `404`).

## Evaluation

Free questioning is the headline feature, so it has its own small eval
(`scripts/run_context_eval.py`, fixture `eval/context_questions.json`):
10 fixed questions across bar/gap/window/free with pre-registered
expected tiers and evidence points, run in two arms — template
(scripted, no model) vs full (chaining + model rewrite; a deterministic
EvalPolisher mock in CI). Metrics: fact-check pass rate, evidence-point
coverage, tier distribution. The script writes
`outputs/context_eval/report.{json,md}`; the report has a blank live
table for the owner's Nightshift run — CI numbers are mock numbers and
are labelled as such.

## Open alignment points

- Front end (`resilimes/demo/static/app.js`, `investigateContext` /
  `renderCtxAnswer`): sends type/tool/family/lot/step/t1_min/t2_min/
  scenario_id/lang/question with absent values as `null` and numbers as
  numbers (the API also treats `""` as absent). It reads the answer at
  `context.answer`, evidence at `context.basis`, and shows `context.tier`,
  the Mock/Live source and degraded/timeout labels. A family row has no
  single tool, so a gap right-click there is sent as a `window` query on
  the family. Covered by `test_api_accepts_every_payload_the_gantt_sends`.
  Not yet surfaced: `part_tiers`, grouping by `basis[].source`. `lang` is
  accepted but answers are English in v1 — localisation is a follow-up.
- Which run answered: the response carries `run` = `{id, seed, horizon_h,
  reference, requested_scenario}`. Only `scenario_id="seed-<n>"` selects an
  explainer run; any other scenario is answered from the 48 h reference run
  `seed-1` (`reference: true`), and the panel says so.
- `scenario_id` semantics beyond `seed-<n>` (e.g. naming an SMT book or
  a study case) need the front end's scenario list to pin down.
- `insight.gaps` merge: the adapter prefers the real module when
  present; once merged, the mirrored path should be deleted.
- `data/notes/fab_notes.json` (Plan-2 line) merge: notes chaining turns
  on automatically when the dataset lands (or via
  `RESILIMES_NOTES_PATH`); Zetaris-backed notes would slot into the same
  `fab_notes` basis source.
- Dispatch-time decision logging (per-wake ranking winner, idle-reason
  records) would move more answers from `rule_emergent` to
  `decision_record`; that is a simulator change, out of scope here.
