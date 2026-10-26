# K curve — lever search (sim_search arm, non-LLM, seeded)

- 运行环境 (environment): Linux-7.0.0-39-generic-x86_64-with-glibc2.39 / python 3.12.3
- 运行时间 (ran_at): 2026-10-26T03:43:30+0000
- 代码版本 (git_commit): 9d7fc23
- 注记 (note): 
- book heldout_published, book seeds [9], search seeds [101, 202, 303], horizon 5.0 h, fork 1.0 h, futures 2, escalation always (always = legacy kind filter, experiment only; the shipped gate is exception)
- runs in: 15/9 (means over search seeds x book seeds; min-max in brackets)

| K | runs | avoidable Q-time (mean) | hot late (mean) | completed (mean) | wt min (mean) | sim calls (mean) | propose calls (mean) | escalated (mean) |
|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 0.0 [0.0-0.0] | 0.0 [0.0-0.0] | 5.0 [5.0-5.0] | 3323.7 [3323.7-3323.7] | 222.667 [218.0-228.0] | 38.0 [38.0-38.0] | 38.0 [38.0-38.0] |
| 3 | 3 | 0.0 [0.0-0.0] | 0.0 [0.0-0.0] | 5.0 [5.0-5.0] | 3323.7 [3323.7-3323.7] | 352.0 [342.0-366.0] | 38.0 [38.0-38.0] | 38.0 [38.0-38.0] |
| 5 | 3 | 0.0 [0.0-0.0] | 0.0 [0.0-0.0] | 5.0 [5.0-5.0] | 3323.7 [3323.7-3323.7] | 483.333 [478.0-494.0] | 38.0 [38.0-38.0] | 38.0 [38.0-38.0] |
| 10 | 3 | 0.0 [0.0-0.0] | 0.0 [0.0-0.0] | 5.0 [5.0-5.0] | 3323.7 [3323.7-3323.7] | 795.333 [786.0-812.0] | 38.0 [38.0-38.0] | 38.0 [38.0-38.0] |
| 15 | 3 | 0.0 [0.0-0.0] | 0.0 [0.0-0.0] | 5.0 [5.0-5.0] | 3323.7 [3323.7-3323.7] | 1106.0 [1090.0-1134.0] | 38.0 [38.0-38.0] | 38.0 [38.0-38.0] |

sim calls = gate forks + twin forks (the twin's fork counter). propose calls = escalations that asked the sampler for plans. Pure simulation: no LLM is involved in any run of this curve.

D arm: rows marked (D) are the same lever-space search at a much larger candidate budget (the extrapolation point). To answer 'does the AI reach the same effect with fewer simulations?', compare the sim calls of the row whose avoidable / hot-late matches the C arm's (see the stress live report, same lexicographic metrics) against the C arm's own fork counts.
