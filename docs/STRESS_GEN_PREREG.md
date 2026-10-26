# 生成式压力场景集 — 预注册（STRESS_GEN_PREREG）

> 本文件与场景定义文件在任何验证/实跑结果产生**之前**提交。规则先写死，
> 结果出来后不许改场景、不许挑场景。

## 场景定义（数据，不是代码挑选）

- 定义文件：`resilimes/smt/stress_gen_scenarios.json`（16 个场景）。
- 生成器：`resilimes/smt/stress_gen.py`，`GEN_SEED = 20261026`，
  `python -m resilimes.smt.stress_gen` 必须能逐字节复现该文件（有测试钉住）。
- 采样方式：从 SMT2020 故障分布的**尾部**采样——
  - 停机时长取对应机台组指数 MTTR 分布的 0.85–0.99 分位（downcal），
    上限 6 h（与验证 horizon 对齐；更长的停机在窗口内看不到恢复）；
  - 停机对象取 q90 修复时长最长的一批 family（≥2 台机）；
  - Q-time 链场景取全路线中 CQT 受限相邻步使用次数最多的 origin→target 对，
    停其下游 family 一半机台；
  - 热批场景的 due 取剩余加工时间的 1.1–1.5 倍（紧端），并把一批朝同一
    family 去的 lot 暂扣后同时释放（扎堆）。
- 四类原型各 4 个：`combo_down`（双 family 组合停机）、
  `qtime_chain_down`（Q-time 链下游停机）、`hot_cluster`（热批扎堆）、
  `down_pm_batch`（停机 + PM 撞窗 + 炉管批上限）。

## 纳入规则（验证后按规则剔除，不许人工挑选）

- 验证：每个场景用**真实 gate 的无 AI 预演**跑一遍
  （`resilimes/smt/stress_gen_validate.py`：`SimShiftLead` 无 completer、
  出货默认 `exception` 门、孪生 fork 1 h、futures 2、horizon 6 h、seed 9）。
- `rule_trigger` 触发的定义：该场景验证跑中至少 1 个异常通过
  `exceptions.triggered()` 使 gate 升级（`escalations >= 1`）。
- 未触发的场景**剔除**，并在验证报告与最终 A/B/C 报告中如实计数、列名。
- 验证通过的场景全集即 A/B/C 三臂的运行集，顺序按场景 id 固定。

## A/B/C 三臂（见 scripts/run_stress_live.py）

- A = 无 AI 孪生基线（引擎方案 + pareto，无 proposer）；
- B = 非 AI 杠杆搜索（SearchCompleter，K=3，pareto）；
- C = Nemotron（现有 sim_llm 路径，K=3，propose + 选择，含降级计数）。
- 比较胜负沿用 `sim_select_study.lexi_cmp` 的预注册词典序：
  可避免 Q-time 违规 → 热批迟到 → 加权迟到 → 完成批数（多胜）。
- mock 模式结果必须在报告中明确标注 MOCK，不得与 live 数字混排。

## 环境注记欄位（每次实跑必填）

运行环境（OS/Python）、运行时间（ran_at, UTC）、代码版本（git_commit）、
模型（C 臂 served model）、场景集版本（本文件所在提交）。
