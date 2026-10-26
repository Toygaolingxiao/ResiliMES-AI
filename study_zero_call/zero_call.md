# 常态账本零调用表 (zero-call table)

- 运行环境 (environment): Linux-7.0.0-39-generic-x86_64-with-glibc2.39 / python 3.12.3
- 运行时间 (ran_at): 2026-10-26T00:14:20+0000
- 代码版本 (git_commit): d1f15ab
- 注记 (note): sim_llm wiring run dry with MockProvider; no live model is called.
- book heldout_published, seed 9, horizon 5.0 h, fork 1.0 h, futures 2

异常 58 个, 升级 0 次, AI 调用 0 次。

| 指标 | 纯规则 (rules) | sim_llm 接线 (mock 干跑) | 一致 |
|---|---|---|---|
| weighted_tardiness_min | 3323.7 | 3323.7 | 是 |
| on_time_pct | 7.14 | 7.14 | 是 |
| qtime_violations | 3 | 3 | 是 |
| qtime_avoidable | 0 | 0 | 是 |
| hot_late | 0 | 0 | 是 |
| hot_due | 0 | 0 | 是 |
| completed_routes | 5 | 5 | 是 |

结论: 常态账本上 gate 不升级, AI 零调用, 两臂逐项一致。
