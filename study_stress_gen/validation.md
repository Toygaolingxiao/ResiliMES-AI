# 生成式压力场景 - gate 验证 (预注册规则)

- 运行环境 (environment): Linux-7.0.0-39-generic-x86_64-with-glibc2.39 / python 3.12.3
- 运行时间 (ran_at): 2026-10-26T02:04:34+0000
- 代码版本 (git_commit): 9d7fc23
- 规则 (rule): triggered := escalations >= 1 in the no-AI gate run (exception mode, fork 1 h, futures 2, horizon 6 h, seed 9)

生成 16 个, 已验证 16 个, 触发 0 个, 未触发剔除 16 个, 待验证 0 个。

| 场景 | 原型 | 异常 | gate 检查 | 升级 (rule_trigger) | 触发 |
|---|---|---|---|---|---|
| gen_01_qtime_chain_down | qtime_chain_down | 60 | 60 | 0 | 否 (剔除) |
| gen_02_qtime_chain_down | qtime_chain_down | 70 | 70 | 0 | 否 (剔除) |
| gen_03_hot_cluster | hot_cluster | 66 | 66 | 0 | 否 (剔除) |
| gen_04_down_pm_batch | down_pm_batch | 70 | 70 | 0 | 否 (剔除) |
| gen_05_combo_down | combo_down | 68 | 68 | 0 | 否 (剔除) |
| gen_06_qtime_chain_down | qtime_chain_down | 70 | 70 | 0 | 否 (剔除) |
| gen_07_combo_down | combo_down | 71 | 71 | 0 | 否 (剔除) |
| gen_08_qtime_chain_down | qtime_chain_down | 74 | 74 | 0 | 否 (剔除) |
| gen_09_combo_down | combo_down | 69 | 69 | 0 | 否 (剔除) |
| gen_10_hot_cluster | hot_cluster | 69 | 69 | 0 | 否 (剔除) |
| gen_11_down_pm_batch | down_pm_batch | 69 | 69 | 0 | 否 (剔除) |
| gen_12_hot_cluster | hot_cluster | 65 | 65 | 0 | 否 (剔除) |
| gen_13_hot_cluster | hot_cluster | 70 | 70 | 0 | 否 (剔除) |
| gen_14_down_pm_batch | down_pm_batch | 79 | 79 | 0 | 否 (剔除) |
| gen_15_combo_down | combo_down | 84 | 84 | 0 | 否 (剔除) |
| gen_16_down_pm_batch | down_pm_batch | 70 | 70 | 0 | 否 (剔除) |
