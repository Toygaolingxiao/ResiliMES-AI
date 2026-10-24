# Shift handover report (AI, advice only)

One 12 h shift of the 48 h run, written for the incoming shift in English, Chinese or Japanese.

## Sections
Top issues · WIP bubbles · at-risk lots · tools down with repair ETA and note · next-shift PM ·
overrides (lots passed over) and their outcome. Plus a one-line summary.

## Engine used: the Markovian engine
The shift is processed as **six 2 h chunks plus one compose step** on
`resilimes.engines.markovian.MarkovianEngine`. Each chunk sees only the compressed checkpoint of
the previous chunks (last 12 decisions, entities, last 8 open issues) and that chunk's facts, so
context stays bounded however long the shift is.

The engine only runs against a signed contract. Scout has no handover intent and we did not add
one (Scout routing is unchanged), so `handover_contract()` signs a fixed contract
(`ai.shift_handover`, capabilities `world.query` + `memory.write`, viewer scope, 30 min expiry)
with the configured Scout signing secret. If the engine refuses the contract, the same steps run in
our own loop with the same `compress()` checkpoint; the result says `engine: "own_loop"`.
In the mock eval all 12 reports ran on `markovian`.

## Facts and checks
- Chunk facts: tools down / PM in the window, WIP bubbles (waiting grew by at least
  max(5, 50 %)), overrides, lots finished.
- End facts: tools down at shift end (since, ETA, hours left), PM in the next 12 h (and, when
  there is none, the next calendar PM: the 48 h runs contain no PM window because the published
  calendars first start at 153.6 h, day 6.4), at-risk lots (due within the next shift, slack under 2 h),
  bubbles, overrides with whether the passed-over lot ended late.
- **Fact check:** every number and id in the report must appear in the facts the model was given;
  one repair round, then misses are reported, never hidden (`fact_ok: false`).
- **Must-mention recall:** tools down at end, tools with PM next shift, the 3 most at-risk lots and
  the bubble families must all be named.
- "Overrides" on main are rule-based Q-time overrides (no AI shift lead runs on main); the report
  labels them as such.

## API
- `GET /api/ai/handover/shifts` returns the four study shifts (seeds 1-2, start 12 h / 24 h).
- `POST /api/ai/handover {seed, start_h 0-36, lang en|zh|ja}` returns report, markdown, engine,
  chunks, fact check, recall and `response_models` (the model each response reported).

The UI card sits in the AI panel; it uses the current UI language.

## Eval
`python -m resilimes.insight.study handover --provider mock|nightshift` writes
`outputs/ai_eval/handover_<tag>.json` after every report (12 = 4 shifts × 3 languages).
The live run on the PC is part of `scripts\run_ai_evals.ps1`.

Mock (scripted stand-in, not a model result): 12/12 fact-check pass, must-mention recall 1.0
(min 1.0), 84/84 chunks ok, engine markovian 12/12.
