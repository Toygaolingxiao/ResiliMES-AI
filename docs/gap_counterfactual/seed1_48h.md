# Gap counterfactual: fill the deliberate gaps

Scenario: policy `resilimes`, seed 1, horizon 48.0 h, fab = SMT2020 extract (simulated, not a real fab). Pure simulation, no LLM.

- Deliberate gaps recorded at dispatch time: **6864** ({'qtime_gate': 6822, 'batch_wait': 42})
- Gaps filled in the twin run: **6864**
- New avoidable Q-time violations after filling: **19** (baseline 23 -> filled 42)
- Protective gaps (filling them hurt): **546** = share **0.0795** of filled, **0.0897** of judgeable gaps

| reason | gaps | protective | not protective | inconclusive |
|---|---|---|---|---|
| batch_wait | 42 | 17 | 25 | 0 |
| qtime_gate | 6822 | 529 | 5519 | 774 |

## Limits

- All gaps filled in one twin run: per-gap attribution is indicative, fills interact.
- PM-avoidance gaps are recorded but never filled (different intervention).
- Simulator results on the SMT2020 extract; no LLM involved.
- Per-gap attribution comes from one twin run with all gaps filled at once; fills interact, so treat the share as an estimate and the violation delta as the hard number.
