# Pitch deck outline

The submission deck is [deck/index.html](deck/index.html): 15 slides in one offline HTML file (arrow keys or click). Every number on a slide names its source doc in the slide footer. Open slots are yellow `[...]` chips: `[SCREENSHOT: Gantt right-click]`, `[LIVE: notes extraction P/R]`, `[LIVE: notes A/B/C]`, `[LIVE: hard-case rerun]`, `[TBD after re-record]`. Fill a slot only with a number that has a committed source.

Positioning: the scheduler stays rule-based and auditable, like mainstream APS. AI makes its decisions understandable to the people who run the fab. The filmed and scored fab is the public industry benchmark (SMT2020), not a recording from a production fab.

| # | Slide | Content |
| --- | --- | --- |
| 1 | Title | Positioning line. Run card: 1,313 tools in 106 families, 2,156 WIP lots, 264 Q-time limits, 99.26% true Q-time compliance. Team and repo. |
| 2 | Problem | A schedule this size cannot be read on the floor, so the shift lead fills an idle gap by hand and a downstream Q-time window is missed. Filling every deliberate gap in a 48 h run adds +19 avoidable Q-time violations (23 → 42). |
| 3 | Approach | Rules decide (planning, scheduling tick, dispatch, hard Q-time gate, every deviation logged). AI explains (Gantt right-click, gap reasons and counterfactual, notes → constraints). |
| 4 | Architecture | Zetaris → rule kernel + hard gate → SMT2020 simulator (15 invariants, all 0) → console. The AI understanding layer reads the record and is advice only. |
| 5 | Gantt right-click | Bar, gap, family window or free question. Tier (`decision_record` / `rule_emergent` / `unknown`) is set by code; a rewrite that claims intent is refused. |
| 6 | Gap reasons + counterfactual | 6,864 recorded gaps on seed 1 / 48 h; filling them adds +19 avoidable violations; 546 gaps were protective. |
| 7 | Result 1: Q-time first | Published book, seeds 1–3, 7 d: 99.26% true Q-time compliance, 71 avoidable misses. Q-time first costs about 17 completed lots and 10 on-time points per run against gating off. EDD is an infeasible reference (1,719 avoidable). |
| 8 | Result 2: remaining misses | Avoidable misses 334 → 111 → 71; 105 unavoidable, by cause. Lots that miss are expedited, never excluded. |
| 9 | Notes → constraints | 46 notes, 48 gold events. Regex baseline P 0.973 / R 0.750 / hard recall 0.000. Live Nemotron slots stay open. |
| 10 | Design evidence | Shipped exception-only trigger: 0 AI calls (58 exceptions, 0 escalated; 0/16 stress books). Same-budget K-curve flat for K = 1–15. B/C ordering comparisons are exploratory (study mode). |
| 11 | AI results | Investigator 20/24 top-1, equal to the rule baseline, fact-check 24/24. Handover 12/12. Late-lot explainer cause 11/12, but only 1/12 of its levers held up in the simulator, so every lever is re-simulated. |
| 12 | Safety | Advice only. Every number and id is fact-checked. 90 s per call, 180 s per task; a timeout or failure falls back to the rule result, labelled with its reason. |
| 13 | Sponsor tech | Nightshift + Nemotron as the only model provider, Zetaris master data (11 tables, 6,935 rows, PARITY OK), Scout Intent, Markovian, World Model, Cursor. |
| 14 | Demo video | Fab state → rule schedule → right-click "why?" → Q-time first → one live Nemotron answer. Timings `[TBD after re-record]`. |
| 15 | Team + next | Close the 71 avoidable misses at chained furnace windows; live notes A/B/C and hard cases on Nemotron; field test of override rates with shift leads. |

What the deck does not claim: that an LLM schedules better than rules, or that ResiliMES beats EDD. EDD appears only as an infeasible reference.

Export: open the HTML in a browser at 1280×720 and print or screenshot each slide. Do not paste tokens.
