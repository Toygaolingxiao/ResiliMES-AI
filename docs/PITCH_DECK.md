# Pitch deck outline

The submission deck is [deck/index.html](deck/index.html): 18 slides in one offline HTML file. Diagrams are inline SVG, with no external images (arrow keys or click). Every number on a slide names its source doc in the slide footer. Open slots are yellow `[...]` chips: `[SCREENSHOT: Gantt right-click]`, `[LIVE: notes extraction P/R]`, `[LIVE: notes A/B/C]`, `[LIVE: hard-case rerun]`, `[TBD after re-record]`. Fill a slot only with a number that has a committed source.

Positioning: the scheduler stays rule-based and auditable, like mainstream APS. AI makes its decisions understandable to the people who run the fab. The filmed and scored fab is the public industry benchmark (SMT2020), not a recording from a production fab.

| # | Slide | Content |
| --- | --- | --- |
| 1 | Title | Positioning line. Run card: 1,313 tools in 106 families, 2,156 WIP lots, 264 Q-time limits, 99.26% true Q-time compliance. Team and repo. |
| 2 | Problem | A schedule this size cannot be read on the floor, so the shift lead fills an idle gap by hand and a downstream Q-time window is missed. Filling every deliberate gap in a 48 h run adds +19 avoidable Q-time violations (23 → 42). |
| 3 | Approach | Rules decide (planning, scheduling tick, dispatch, hard Q-time gate, every deviation logged). AI explains (Gantt right-click, gap reasons and counterfactual, notes → constraints). |
| 4 | Architecture (diagram) | Decision path: SMT2020 data (Zetaris or local extract) → planning → scheduling tick → dispatch + Q-time gate → SMT2020 simulator (15 invariants, all 0) → console. The AI understanding layer sits beside it: it reads the decision record and sends advice to the console. No arrow from the AI layer into planning or dispatch. |
| 5 | Gantt right-click | Bar, gap, family window or free question. Tier (`decision_record` / `rule_emergent` / `unknown`) is set by code; a rewrite that claims intent is refused. |
| 6 | Right-click sequence (diagram) | Console → `POST /api/ai/investigate` → decision record → at most one model rewrite → code fact-check → answer with tier and evidence. Fallback branch: no model, timeout, provider error, fact-check failure, tier upgrade or bad JSON give the scripted answer, labelled `degraded` with its reason. |
| 7 | Gap reasons + counterfactual | 6,864 recorded gaps on seed 1 / 48 h; filling them adds +19 avoidable violations; 546 gaps were protective. Pure simulation, no LLM. |
| 8 | Result 1: Q-time first | Published book, seeds 1–3, 7 d: 99.26% true Q-time compliance, 71 avoidable misses. Q-time first costs about 17 completed lots and 10 on-time points per run against gating off. EDD (520.0 lots/run, 91.96% on-time) is an infeasible reference with 1,719 avoidable violations. |
| 9 | Result 2: remaining misses | Avoidable misses 334 → 111 → 71; 105 unavoidable, by cause. Lots that miss are expedited, never excluded. The 71 are the open item. |
| 10 | Notes → constraints (diagram) | Note → extractor → `validate_events` (code) → typed event candidate → a person reviews; rejected events are shown with their reason; A/B/C runs on a mock ledger and nothing is auto-applied. 46 notes, 48 gold events. Regex baseline P 0.973 / R 0.750 / hard recall 0.000. Live Nemotron slots stay open. |
| 11 | Design evidence | Shipped exception-only trigger: 0 AI calls (58 exceptions, 0 escalated; 0/16 stress books; study fork 1 h × 2 futures, shipped 8 h × 3). Same-budget K-curve flat for K = 1–15; limitation: the lever set may be too weak or the search too blind. B/C ordering comparisons are exploratory (study mode). |
| 12 | Exception-only escalation (diagram) | Exception (5 kinds) → rule default → no-AI twin preview (8 h × 3 futures) → mean avoidable Q-time ≥ 1.0 or hot/VIP late ≥ 1.0? No: keep the rule plan, no LLM call. Yes: AI shift lead proposes ≤ 4 plans → fork sim on the same futures → pareto select. Thresholds pre-registered, not retuned. |
| 13 | AI results | Investigator 20/24 top-1, equal to the rule baseline, fact-check 24/24. Handover 12/12. Late-lot explainer cause 11/12, but only 1/12 of its levers held up in the simulator, so every lever is re-simulated. |
| 14 | Without Nemotron (diagram) | Slide 4's architecture with the removed boxes greyed out. Stays: every scheduling KPI (0 AI calls by default), gap reasons and the +19 counterfactual, scripted answers with the same tier, rule baselines. Goes: model rewrites, handover narrative, prose causes, LLM note extraction (regex hard-note recall 0.000). |
| 15 | Design principles + safety (diagram) | ① Q-time first ② AI advises, never decides ③ every answer fact-checked ④ fallback labelled. 90 s per call, 180 s per task; SQL guard; tier set by code. |
| 16 | Sponsor tech | Nightshift + Nemotron as the only model provider, Zetaris master data (11 tables, 6,935 rows, PARITY OK), Scout Intent, Markovian, World Model, Cursor. |
| 17 | Demo video | Fab state → rule schedule → right-click "why?" → Q-time first → one live Nemotron answer. Timings `[TBD after re-record]`. |
| 18 | Team + next | Close the 71 avoidable misses at chained furnace windows; live notes A/B/C and hard cases on Nemotron; field test of override rates with shift leads. |

What the deck does not claim: that an LLM schedules better than rules, or that ResiliMES is better or worse than EDD. EDD appears only as an infeasible reference.

Export: open the HTML in a browser at 1280×720 and print or screenshot each slide. Do not paste tokens.
