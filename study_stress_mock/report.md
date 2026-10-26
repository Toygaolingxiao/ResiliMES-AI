# 生成式压力集 A/B/C 对比报告

> **MOCK 模式**: C 臂为 MockProvider, 本报告所有数字仅验证管线, 
> 不是 live 结果, 不得与 live 数字混排。

- 运行环境 (environment): Linux-7.0.0-39-generic-x86_64-with-glibc2.39 / python 3.12.3
- 运行时间 (ran_at): 2026-10-26T00:34:11+0000
- 代码版本 (git_commit): 6f8c75a
- 模式 (mode): mock; 模型 (served): {}
- 触发率 (trigger rate): 已验证 None 个场景中触发 0 个 (rate=None); 未触发剔除 0 个: -; 待验证 0 个 (不在运行集内)

## 胜平负 (预注册词典序: 可避免 Q-time -> 热批迟到 -> 加权迟到)

| 对比 | 胜 | 平 | 负 |
|---|---|---|---|
| C_vs_A | 0 | 1 | 0 |
| C_vs_B | 0 | 1 | 0 |

## C 臂降级 / 超时

- LLM 调用: 0; 降级总计: 0 (其中超时 timeout: 0); 非 Nemotron 回复: 0
- 失败分类: {}

## 各场景指标 (A / B / C)

| 场景 | seed | 臂 | 可避免 Q-time | 热批迟到 | 加权迟到 (min) | 完成批数 | 升级 | LLM 调用 |
|---|---|---|---|---|---|---|---|---|
| gen_01_qtime_chain_down | 9 | A | 0 | 0 | 3986.6 | 7 | 0 | 0 |
| gen_01_qtime_chain_down | 9 | B | 0 | 0 | 3986.6 | 7 | 0 | 0 |
| gen_01_qtime_chain_down | 9 | C | 0 | 0 | 3986.6 | 7 | 0 | 0 |
