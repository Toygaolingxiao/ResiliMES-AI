# Pitch deck outline

Build this in Google Slides or PowerPoint. Twelve slides, plus one labeled backup. The demo video carries the product; the deck carries the judging rubric. Use console screenshots from `make demo` (KPI row, both Gantts, trace). Do not paste tokens.

Suggested file name: `ResiliMES-Track03.pdf`.

The filmed console is the public industry benchmark (SMT2020). Say that name. It is the published dataset, not a recording from a production fab.

## 1. Title

ResiliMES. Autonomous rescheduling and fault recovery for smart manufacturing.

Track 03 — Reasoning Architecture. Open Agent Hackathon 2026.

Team names. One line: "On the public SMT2020 benchmark, the supervisor gets a schedule they can commit, with the due-date delta and the reason each move was allowed."

## 2. Published dues (Impact — 30)

Lead with this slide. Horizon 48 hours from the 2018-01-01 snapshot. 56 lots are due inside the horizon. 10 of those lots are already late at the snapshot, so the maximum on-time count is 46/56.

Five seeds, ResiliMES: 32, 32, 32, 32, 31 of 56 (159/280, mean 56.78%).

Five seeds, earliest-due: 33, 33, 32, 33, 32 of 56 (163/280, mean 58.21%).

Earliest-due is ahead by 4 pooled lots on on-time delivery, and slightly ahead on weighted tardiness (19,033 minutes against 19,095). ResiliMES has fewer Q-time violations (388.8 against 432.6) and re-cleans (47.0 against 57.2).

These are the published routes and the published dues. Nothing on this slide was retuned to manufacture a win.

## 3. Where ResiliMES wins and where it loses

Same fab. Three books. Read them in this order.

- Published dues, above. Earliest-due wins on on-time (163 against 159 of 280). ResiliMES does not win this book.
- X-factor dues (remaining process time times 2.75, 87 lots, 48 hours). Five-seed mean: ResiliMES and earliest-due both 99.54% on time (433/435 pooled), weighted tardiness 0.76 minutes each. Both beat FIFO (47.1%) and critical ratio (76.6%). Five-seed means for the side metrics: Q-time violations 436.8 vs 479.0 (ResiliMES fewer), re-cleans 53.4 vs 48.8 (ResiliMES more). The console click is seed 1, and the cards on that click are earliest-due 87/87 against ResiliMES 87/87, re-cleans 44 to 57, Q-time 494 to 448. Speak the cards. The five-seed mean is the line under the cards.
- Tight VIP dues. This book rewrites the dues. It is a stress test, not the published order book. 21 lots, 24 hours. ResiliMES is 5/21, 6/21, 6/21, 6/21, 5/21 (28/105). Earliest-due is 4/21, 4/21, 3/21, 4/21, 4/21 (19/105). Seed 1 weighted tardiness is 6,842.1 under earliest-due and 3,616.9 under ResiliMES. `Init_Lot_2_13` is the save on this book (5.03 h late under earliest-due, on time under ResiliMES).
- Every number on these slides is after the simulator stale-queue fix and the fab-logic-r1 operation logic ([FAB_LOGIC_R1.md](FAB_LOGIC_R1.md)), and passes the trace invariant checker with 0 violations ([invariants.md](invariants.md)).

Screenshot: the X-factor cards from seed 1, then the tight VIP cards. The study line under the X-factor cards has to be visible so a judge can see which number is the click and which number is the five-seed mean.

## 4. Why Track 03

The challenge asks for data, knowledge, memory, and reasoning turned into a reliable decision and action.

- Data: the SMT2020 extract in process. Live mode also reads the setup matrix from Zetaris. Mock mode labels the local extract and does not call Zetaris.
- Knowledge: routes, station-family qualification, setup seconds, published CQT limits, PM windows.
- Memory: World Model event log and the Markovian checkpoint.
- Reasoning: Scout contract, then the event-driven dispatcher, then a critic that speaks only when the trace contains the start it rejects.
- Decision: the recovered schedule.
- Action: assignment events the world model can replay.

Track 02's "explain why" is the narrative. It supports the decision. It is a second sentence, not a second entry.

## 5. The loop (Technical — 20)

One diagram. Use the mermaid figure in `docs/ARCHITECTURE.md` or a simplified version:

Disruption → Scout contract → specialist → dispatcher → critic → world model, with Nightshift/Nemotron on the explainer lane only.

Say this sentence: "The model does not author the schedule. It writes one sentence after a schedule that is already fixed."

## 6. Reliability (Technical, Innovation — 15)

The critic on the SMT console leaves `refusal` empty when the event trace has no start on the down tool. A reject sentence appears only when that trace contains one. The verdict on a clean run is accept, and it is not paired with a reject sentence.

Four checks that do fire, each with a test name in the speaker notes, live on the six-lot bay and on Scout:

- Start LOT-1001 on a down tool. Critic: `equipment_status`.
- Preempt a running lot to flatter a rush promise. Critic: `preemption`.
- Dispatch lithography with zero resist. Critic: `material`.
- Viewer role, or "ignore previous instructions". Scout: no contract, no commit.

Innovation is the split between a deterministic commit path and a language lane, gated by a signed contract.

## 7. Sponsor stack (Sponsor tech — 10)

| Layer | What we use | What is unique |
| --- | --- | --- |
| Zetaris | In live mode, five `COUNT(*)` queries plus `resilimes.setup_matrix`. Matching setup seconds replace the local matrix for that run. Routes, WIP, and dues stay on the local extract. | Mock mode does not call Zetaris. `zetaris.called` is false, and the query line says so. |
| Scout Intent | The required Meterless engine | Live mode uses the Nightshift profile. Mock mode stays on the mock profile. Nothing reschedules without a fresh HMAC contract. |
| World Model | Assignment log | Replay is the commit. |
| Markovian | The five-step loop | Checkpoint size stays flat. About 500 vs about 1600 on the litho run. Not a model token count. |
| Nightshift + Nemotron | One sentence after the schedule is fixed | The model does not place lots. Without a token the step is the mock narrative and there is no request id. |
| Cursor | How the team built it | Agent-assisted implementation, tests, and this deck's source docs. |

Speaker note: `pytest tests/test_scout_engine.py` is the test the submission form should name.

## 8. One live request (Sponsor tech, Demo — 15)

Screenshot or a 10-second still from the optional live clip.

Show `provider_call.provider = nightshift` and the Nemotron model id. Call out that the token is not on the slide. If you have not run live yet, this slide is a diagram of the same call path plus the sentence "mock mode is what you saw; live mode is this configuration" and a pointer to `.env.example`. Do not fake a live transcript, a Zetaris row count, or a Nightshift request id.

## 9. Product (Product & UX — 10)

What the supervisor does: pick the disruption, read the cards with their denominator, read the study line under the cards, compare the Gantts, and check that a refusal is present only when the trace contains the start.

What we deliberately left out: a general chat box as the product, a schedule the model can silently overwrite, a mock mode that hides itself, and a button whose sentence describes a gate the code no longer runs.

## 10. Engineering (Technical)

Python 3.11+, typed package, ruff, mypy, pytest, GitHub Actions on 3.11 and 3.12, Dockerfile, `make demo` with no credentials. Structured logs redact secrets. Zetaris schema names are validated. SQL on the read path is `SELECT` only. `smt_rule` is the dataset dispatch cascade from `tool.txt.1l` (`rule_HotLotFIRST` with `rank_HP;rank_RSETUP;rank_CR`, and `rule_LSSU` on Implant_128, Implant_132, and Implant_91). Seeds 1-5, scored once: ResiliMES beats it on on-time, 56.428% against 28.214% on published dues and 97.47% against 70.116% on the X-factor book. Those rows were not tuned after the run. On the shifted PM calendar, with the same PM refusal on every policy, EDD is 55.716% on time and ResiliMES is 55.0%.

## 11. What we would do next

- Point the live Zetaris read at the rest of the dispatcher inputs (routes and WIP), once those tables are loaded beside the setup matrix.
- Add a human approval click for `plant.emergency_stop`, which the contract already requires.
- Feed the world-model log back as the next shift's prior, so a second disruption replans with `parentId`.

Keep this slide short. Do not promise a second product.

## 12. Ask

We are submitting to Track 03. The supervisor's decision is the schedule on the public SMT2020 benchmark. Scout, Zetaris, Nightshift/Nemotron, and the critic are how that decision stays inspectable.

Team names, repo URL, video link, and the sponsor paragraph from `docs/SPONSOR_TECH.md`.

## Backup (not the filmed demo): six-lot bay

`make demo-bay` only. Unit-test fab FAB-A, scenario clock 22 Oct 2026 06:30 UTC. This slide is not the film and it is not the SMT2020 score.

- Machine breakdown: on-time delivery 83.3% to 100%, weighted tardiness 784 minutes (13 hours 4 minutes) to 0.
- Rush order: the hot lot is 36 min late. The running lot is not preempted.
- Material shortage: lots that need photoresist are held, with the stock row as evidence.

The SMT2020 lithography and X-factor baselines are earliest-due on the full fab. This bay compares a frozen assignment, and it charges a scanner-family setup and a 5-minute reticle mount the SMT2020 extract does not contain.
