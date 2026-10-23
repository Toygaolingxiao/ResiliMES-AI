# Pitch deck outline

Build this in Google Slides or PowerPoint. Twelve slides. The demo video carries the product; the deck carries the judging rubric. Use console screenshots from `make demo` (KPI row, both Gantts, trace). Do not paste tokens.

Suggested file name: `ResiliMES-Track03.pdf`.

## 1. Title

ResiliMES. Autonomous rescheduling and fault recovery for smart manufacturing.

Track 03 — Reasoning Architecture. Open Agent Hackathon 2026.

Team names. One line: "When a scanner faults, the supervisor gets a schedule they can commit, with the due-date delta and the move that was refused."

## 2. The user and the cost (Impact — 30)

User: production supervisor on a wafer fab shift.

The problem is not a missing chatbot. A priority lot blocked on a down tool misses a due time while the planner is still copying the queue into a spreadsheet. Missed on-time delivery is the customer's scorecard. The sample morning is concrete: LOT-1001, priority 1, due 18:00 UTC, scanner down for 10 hours.

## 3. What we show them (Impact, Product)

Three disruptions, one console.

- Machine breakdown: on-time delivery 83.3% → 100%, weighted tardiness 840 → 0 minutes.
- Rush order: the hot lot is 1 h 10 min late because a running lot is not preempted and the reticle stays on that scanner.
- Material shortage: lots that need photoresist are held, with the stock row as evidence.

Screenshot: KPI cards plus the two Gantts.

## 4. Why Track 03

The challenge asks for data, knowledge, memory, and reasoning turned into a reliable decision and action.

- Data: Zetaris tables, or the same SQL against the sample twin.
- Knowledge: routes, capability, setup family, max WIP, operator pool.
- Memory: World Model event log and the Markovian checkpoint.
- Reasoning: Scout contract, then a solver, then a critic.
- Decision: the recovered schedule.
- Action: assignment events the world model can replay.

Track 02's "explain why" is the narrative and the rejected alternative. It supports the decision. It is not a second entry.

## 5. The loop (Technical — 20)

One diagram. Use the mermaid figure in `docs/ARCHITECTURE.md` or a simplified version:

Disruption → Scout contract → specialist → solver → critic → world model, with Nightshift/Nemotron on the explainer lane only.

Say this sentence: "The model does not author the schedule. It explains a schedule that already passed the critic."

## 6. Reliability (Technical, Innovation — 15)

Four refusals, each with a test name in the speaker notes:

- Start LOT-1001 on a down tool. Critic: `equipment_status`.
- Preempt a running lot to flatter a rush promise. Critic: `preemption`.
- Dispatch lithography with zero resist. Critic: `material`.
- Viewer role, or "ignore previous instructions". Scout: no contract, no commit.

Innovation is the split between a deterministic commit path and a language lane, gated by a signed contract, not a larger prompt.

## 7. Sponsor stack (Sponsor tech — 10)

| Layer | What we use | What is unique |
| --- | --- | --- |
| Zetaris | SQL over equipment, WIP, routes, stock, maintenance | Same queries in live and mock. Mock is labeled. |
| Scout Intent | The required Meterless engine | Nothing reschedules without a fresh HMAC contract. |
| World Model | Assignment log | Replay is the commit. |
| Markovian | The five-step loop | Checkpoint tokens stay flat. About 500 vs about 1600 on the litho run. |
| Nightshift + Nemotron | Explainer lane | Right model in the language lane. Solver stays in the decision lane. |
| Cursor | How the team built it | Agent-assisted implementation, tests, and this deck's source docs. |

Speaker note: `pytest tests/test_scout_engine.py` is the test the submission form should name.

## 8. One live request (Sponsor tech, Demo — 15)

Screenshot or a 10-second still from the optional live clip.

Show `provider_call.provider = nightshift` and the Nemotron model id. Call out that the token is not on the slide. If you have not run live yet, this slide is a diagram of the same call path plus the sentence "mock mode is what you saw; live mode is this configuration" and a pointer to `.env.example`. Do not fake a live transcript.

## 9. Product (Product & UX — 10)

What the supervisor does: pick the disruption or type a sentence, read the narrative, compare the Gantts, check the refused alternative.

What we deliberately left out: a general chat box as the product, a schedule the model can silently overwrite, a mock mode that hides itself.

## 10. Engineering (Technical)

Python 3.11+, typed package, ruff, mypy, pytest, GitHub Actions on 3.11 and 3.12, Dockerfile, `make demo` with no credentials. Structured logs redact secrets. Zetaris schema names are validated. SQL on the read path is `SELECT` only.

## 11. What we would do next

- Point `ZETARIS_SCHEMA` at the plant's real Lightning database and drop the sample overlay.
- Add a human approval click for `plant.emergency_stop`, which the contract already requires.
- Feed the world-model log back as the next shift's prior, so a second disruption replans with `parentId`.
- Calibrate setup families from the last completed lot instead of treating the horizon family as unknown.

Keep this slide short. Do not promise a second product.

## 12. Ask

We are submitting to Track 03. The supervisor's decision is the schedule. Scout, Zetaris, Nightshift/Nemotron, and the critic are how that decision stays inspectable.

Team names, repo URL, video link, and the sponsor paragraph from `docs/SPONSOR_TECH.md`.

## Speaker notes for the judges' weights

If a judge only remembers three numbers, they should be 83.3 to 100, 840 to 0, and "the rush lot is 1 h 10 min late because we would not preempt, and the reticle stays with the running lot." Those three cover impact, the decision, and the refusal.
