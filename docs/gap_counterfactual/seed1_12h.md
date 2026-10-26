# Gap counterfactual: fill the deliberate gaps

Scenario: policy `resilimes`, seed 1, horizon 12.0 h, fab = SMT2020 extract (simulated, not a real fab). Pure simulation, no LLM.

- Deliberate gaps recorded at dispatch time: **3155** ({'qtime_gate': 3155})
- Gaps filled in the twin run: **3155**
- New avoidable Q-time violations after filling: **3** (baseline 0 -> filled 3)
- Protective gaps (filling them hurt): **21** = share **0.0067** of filled, **0.0141** of judgeable gaps

| reason | gaps | protective | not protective | inconclusive |
|---|---|---|---|---|
| qtime_gate | 3155 | 21 | 1466 | 1668 |

## Limits

- All gaps filled in one twin run: per-gap attribution is indicative, fills interact.
- PM-avoidance gaps are recorded but never filled (different intervention).
- Simulator results on the SMT2020 extract; no LLM involved.
- Per-gap attribution comes from one twin run with all gaps filled at once; fills interact, so treat the share as an estimate and the violation delta as the hard number.
