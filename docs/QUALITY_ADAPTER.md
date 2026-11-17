# 故障注入基准适配（adapter/v0）

实现：`resilimes/insight/quality_adapter.py`；契约测试：`tests/test_explain_quality_adapter.py`（41 件，40 通过、1 件は #88 未合并のため skip——下记「再现性」参照）。
口径：`docs/QUALITY_METRICS.md`（quality/v0；该文件属 PR #88，本 PR には含まれない）。
本文只定适配规则与首次实测。适配规则变更 = 版本变更，不许静默改映射。

## 这是什么

quality/v0（PR #88）能算三项度量，但它不读文件、不跑仿真——样本从哪来由
调用方负责。本适配器是第一个调用方：把已保存的故障注入基准运行
（`insight.study.run_investigator` 的输出 JSON）转成 quality/v0 的
`AttributionSample` JSON 形态。适配器自身不算率；率是 `quality.evaluate`
的职责。适配器不 import `quality`——#88 未合并，本 PR 只消费 quality/v0
的 JSON 契约（字段名与 tier/预测一致性规则，见模块内 `_validate_sample`；
`#88` 合并后跑起来的交叉校验测试 `test_adapter_validation_matches_quality_when_available`
会把手工复刻的校验与真实 `AttributionSample` 逐项对上，防止契约漂移）。
合并顺序：**#88 → 本 PR**。本 PR 的三个文件与 #88 的三文件
（`quality.py`、`test_explain_quality.py`、`QUALITY_METRICS.md`）零重叠
（已核实）；与 #89–#93 亦无重叠（据 dev-queue.md / checkpoint.md 记录的
各 PR 文件清单：claims、cases、DESIGN_SYSTEM、Cases 页、Quality 页——均不
触及 `resilimes/insight/quality_adapter.py` 与本 PR 的测试/文档名）。

## 映射规则（adapter/v0）

- **真值**：行内 `truth`（注入原因）。无可用真值的行不能评分，跳过并计入
  `skipped.missing_truth`；不把它写成 `true_cause=None` 的样本。
- **预测**：取运用者看到的回答，以 `ai.system.source`（`explain.investigator._system_answer`
  写入的字段）为准：
  - `"ai"`——AI 自身的回答（此时 `system.primary_cause` 即 `ai.primary_cause`）。
  - `"rule"`——degraded 时的规则基线回答（`baseline_rank` top1）。AI 回答已判定不可用时，
    运用者看到的是这条规则回答。
  - `"none"`——系统拒绝服务（基线排序本身抛错，`stop_reason` 同时变为 `"error"`）。
    此时预测为 None，**不**把 AI 回答捡回来。
  - `system` 无 `source` 键时容忍旧形态：有可用的 primary 即采用；无则回落到 AI 回答。
  - `system` 不是 dict、或 `source` 为 `"ai"`/`"rule"` 时 primary 不可用
    （非字符串、空字符串；`"rule"` 时 None 亦然），计入 `malformed_predicted` 跳过——
    绝不静默改用另一方的回答。
  - 注意：仓内对此存在分歧。`study.system_score`、`api/insight.py`、`explain/context_investigation.py`
    都读 system 回答；而证据页（`evidence.js`）的标题仍显示 AI 自身的 `primary_cause`，
    规则回答只出现在一行警告里。适配器采 system-score 一方的读法；这是一个有争议的选择，
    不是不证自明的事实。
- **超时/错误**：行 `timeout`、`ai.timed_out`、`ai.timeout` 任一为真，或行 `error` / `ai.error`
  任一非 None（空字符串亦算错误信号），或行/`ai` 的 `stop_reason == "error"` 时，预测为 None——
  即使半成品 `primary_cause` 存在（超时就是 miss，与 `study.ai_score` 同规则）。
- **档位**：命名了原因 → `"attributed"`；没命名 → `"unknown"`。但此处的 `"attributed"`
  只表示「系统给出了命名」，**不**携带 Evidence Schema 的保证：schema 的 attributed 是
  「按固定规则从观测中拆出来」（可复现）且非 unknown 项必须有 `sources`，而 investigator 的
  `primary_cause` 是 LLM 自由推理（temperature 0.2，非固定规则），且适配器丢弃了行内的
  `citations` 与 `causal_chain`，样本里没有任何来源字段。degraded 时的规则回答与 AI 自由推理
  共用同一档位——认识论上两者不同，样本 dict 本身无法区分（quality/v0 契约恰为 5 字段）；
  区分信息在 `AdaptedSet.system_answer_sample_ids` 与 CLI summary 中。`"recorded"` 永不使用
  （investigator 的回答是推论，不是记录事实）。
- **置信**：恒为 None。investigator 的回答没有置信度，事后补造等于伪造
  校准。直接后果：本基准上的校准恒为空（`calibration_samples=0`、
  ECE None；24 件样本全部因无置信被排除），直至 investigator 本身输出置信度。
- **sample_id**：`"<source>:<case_id>"`（`adapt_investigator_file` 既定为文件 stem）。
  调用方必须指明 source（无默认值），以免两个文件静默撞 id。
  重复 `case_id` 是输入文件已坏，整个运行以 `ValueError` 失败，不默默去重。
  id 只在行真正成样后才登记——被跳过的行不占用 id，不会拖垮后出现的同 id 有效行。
- **词表外预测**：保留不丢弃（quality/v0 也不校验词表成员），件数记入
  `out_of_taxonomy_predicted`。词表外真值只对成样的行计数（`out_of_taxonomy_truth`）。
- **跳过**：结构原因无法成样的行按理由计数（`missing_case_id` /
  `missing_truth` / `malformed_row` / `malformed_ai` /
  `malformed_predicted`），计数随结果一起走，不静默。
- **行形态**：已保存文件早于 `system` / `stop_reason` / `degraded` 字段
  （形态 `"legacy"`），现行 `run_investigator` 输出带这些字段（形态
  `"current"`）。两种都接受。形态只是文件级的信息标签，不改变任何映射规则；
  混合文件只要任一行带新键即标为 `"current"`。

## 用法

仓库根目录、项目 venv 中执行：

```sh
python -m resilimes.insight.quality_adapter results_pc/investigator_nightshift_v2.json --out samples.json
```

stdout 打印 summary JSON（`adapter_version` / `source` / `shape` / `samples` /
`skipped` / `system_answers_used` / `system_answer_sample_ids` /
`out_of_taxonomy_*`），外加 `report` 键：三项度量的分子/分母/值与校准样本
数（见下「接线」）。`--out` 指定时写出自描述对象
`{"samples": [...], "summary": {...}}`（样本列 + 全部元数据，只拿该文件
的下游也能复原跳过与来源信息）。写出失败时 exit 2（不抛 traceback）。

## 接线：适配 → 评估 → 报告（evaluate wiring）

`evaluate_adapted(adapted)` 把适配得到的样本列喂给 `quality.evaluate()`：
每条样本 dict 先过真实 `AttributionSample` 校验，再算 quality/v0 报告。
`evaluate_file(path)` 一步完成适配与评估；CLI 加 `--report report.json`
写出自描述对象 `{"report": <QualityReport 全量 JSON>, "summary": {...},
"adapter_version", "metrics_version"}`，只拿该文件也能复原测了什么、
跳过了什么。

```sh
python -m resilimes.insight.quality_adapter results_pc/investigator_nightshift_v2.json --report report.json
```

接线不改变任何映射规则：它只把适配器已产出的样本列交给已有的
`evaluate()`。样本列本身仍由 adapter/v0 的规则决定；率的口径仍由
quality/v0 决定。空样本列评估出的报告三项率均为 `None`（分母 0：数据
不足，不是 0.0）。

## 首次实测（2026-11-16，本地运行）

方法：适配器（本 PR 内容）+ `quality.py`（本地副本，经核验与 PR #88
提交 `claude/resilitrace-20261113-dev1` 先端 `4c0410f` 上的文件逐字节一致，
blob `c464455f…`）。每条样本都通过了 `AttributionSample` 的 pydantic
校验（48 条全过；三位独立审核员另行复算一致）。输入文件取自 main `86fdf157`：

| 文件 | blob | 标签 |
| --- | --- | --- |
| `results_pc/investigator_nightshift_v2.json` | `db8dd589…` | real:nvidia/nemotron-3.5-lightning-30b-a3b |
| `results_pc/investigator_nightshift_v1.json` | `869bf2f8…` | real:nvidia/nemotron-3.5-lightning-30b-a3b |

两文件覆盖同一组 24 个 case（6 种注入原因 × seed 1–4，case_id 集合一致，
逐 case 的 question、family、t1/t2、truth、baseline 在两文件间完全相同），
summary 的 `errors` 字段均为 0（行级 error 键的计数；另见下：v1 有 2 行
`no_answer`，不在 `errors` 里）。适配结果：两文件各 24 样本，skipped 0，
system 回答 0 件（旧形态无 system 字段），词表外 0 件。

**运行溯源的缺失**：两文件除 summary 外无任何元数据——无时间戳、无 investigator
代码版本、无 temperature/prompt 版本等运行参数。所以连「v1 与 v2 之间改了什么」
都无从得知；下文的「对照」仅描述数字差异，不指向任何一次变更。

### 命名准确率（quality/v0 报告）

本增量测的是**命名准确率**（predicted 的名字与注入真值是否一致），不是
「归因可信」的全部：名字对错与证据支撑是两个维度——两文件的误归因行
**全部 `fact_ok=True`**（事实核查通过了错误的答案），本率不衡量证据支撑。

| 度量 | v2 | v1 | 规则基线（两文件相同） |
| --- | --- | --- | --- |
| 误归因率 misattribution | **4/24 = 16.7%** | **11/22 = 50.0%** | 4/24 = 16.7% |
| 过度不明率 over-unknown | 0/24 = 0.0% | 2/24 = 8.3%（2 件均为 turn-limit 超时，非主动弃权） | — |
| 答错 + 无回答（合计失败率） | 4/24 = 16.7% | 13/24 = 54.2% | 4/24 = 16.7% |
| unknown 占比（描述统计） | 0/24 | 2/24 | — |
| 校准样本 / ECE | 0 / None（24 件因无置信被排除） | 0 / None（22 件因无置信被排除） | — |

分母说明：v1 的误归因分母是 22 不是 24——2 行无回答（unknown），按口径
不在误归因分母里，而在过度不明分母里。这正是 quality/v0 要求分母常显
的原因；只报「50%」而不报分母会重蹈 1/12 的覆辙。另注意激励含义：
在难题上超时/崩溃比答错更划算——答错推高误归因率，不回答只推高过度不明率；
合计失败率（v1 13/24、v2 4/24）是更诚实的对照。

**基线对照**：v2 的 AI（20/24）只追平确定性规则基线（`baseline_top1` 20/24），
v1 的 AI（11/24）远低于同一基线。在这组 case 上 LLM 相对规则没有增量价值——
16.7% 不是「AI 变好了」的证据。

**不确定性**：Wilson 95% 区间——v2 4/24 为 6.7%–35.9%，v1 11/22 为 30.7%–69.3%，
两区间重叠，33 个百分点的表观差距在 95% 水平下不显著。配对检验（McNemar）
算得 p≈0.022，但该检验假定两次运行除版本外可比，而文件不记录运行条件，
故不作为结论引用。n=24，每格 n=4：分格数字只作描述，不作原因归因。

与文件自带 summary 的一致性检查（不是独立验证——两边读的是同一文件的
同一字段，一致只能证明适配器没读错字段，不能证明文件数据本身正确）：
v2 `ai_top1 20/24` → 答对 20、答错 4，与误归因 4/24 一致；v1 `ai_top1 11/24`、
`no_answer 2` → 答 22、错 11，与误归因 11/22、过度不明 2/24 一致。
注意：新形态文件一旦出现 degraded 行，适配器的 predicted（system 答案）与
文件自带 `ai_top1`（AI 答案）按设计就该不一致，届时「不一致」不是适配器有错。

### 按注入原因（v2 / v1 / 基线，各 n=4）

下表是两文件自带 summary 的 `by_fault.ai_top1` / `base_top1` 的转述；
本增量首次的只是 quality/v0 口径的率（分母处理），不是分格数字本身。

| 原因 | v2 答对 | v1 答对 | 基线答对 |
| --- | --- | --- | --- |
| tool_down | 4 | 2（另 2 行无回答） | 4 |
| pm_in_peak | 3 | 3 | 3 |
| release_burst | 4 | 4 | 4 |
| setup_thrash | 3 | 2 | 3 |
| batch_cap | 2 | 0 | 2 |
| upstream_starvation | 4 | 0 | 4 |

每格 n=4（2/4 的 Wilson 95% 区间是 15%–85%），分格数字只作描述。
一个比总率更有用的模式：失败不是随机的——v2 的 4 个误归因**全部**预测为
`release_burst`，v1 的 11 个误归因中有 9 个预测为 `release_burst`
（另 2 个预测为 `tool_down`）。`release_burst` 是系统性吸引子。
另：top-2 信号（`ai_top2` v2 21/24、v1 12/24）不在本度量内——quality/v0
只定义 top-1，适配器忽略 `secondary_cause` 是口径内的选择。

**再现性**：上表数字由三位独立审核员用真实 `quality.py` 另行复算一致。
#88 合并后，接线已落地，复现是测试与 CLI 的一部分，不再需要手工拼
样本列：`tests/test_explain_quality_adapter.py` 的
`test_evaluate_file_reproduces_first_measurement` 用真实
`evaluate()` 对两文件重算并断言上表 headline（v2 误归因 4/24、v1
11/22）；命令行复现：`python -m resilimes.insight.quality_adapter
results_pc/investigator_nightshift_v2.json --report report.json` 取
`report.misattribution` / `report.over_unknown`；输入文件以 blob（上表）
核对。

## 局限与非目标

- 校准恒为空：investigator 不输出置信度。想测校准，先改 investigator
  输出置信（本体变更，见提案），不是适配器能补的。
- 旧形态文件无法区分「AI 自身回答」与「运用者看到的回答」（无 system
  字段）：v1/v2 的 24+24 样本全按 AI 回答计；新形态运行才有 degraded
  分支的区分（且届时基线对照与 `ai_top1` 一致性检查的含义都会变，见上）。
- 样本量小（n=24）：率的波动大，上述数字是首次测量，不是基线定论。
- explainer 流（`run_explainer` 的 dominant 成分）不在本增量：它的
  「原因」词表（processing / lots_ahead 等）与注入原因词表不同，混进
  同一样本列会把两个问题算成一个率；另行增量处理。
- 本增量不重跑基准（LLM 呼び出しを伴う），只读已保存输出。
- 独立包 `packages/resilimes-explain` 不受影响：适配器是基准侧工具，
  不进独立包。

## 提案（不直接实现）

- investigator 在 `Investigation` 上输出置信度（或至少每轮的
  self-rated confidence），校准才有可测之物；输出档位（tier）同理，
  届时适配器的 tier 指派规则可退役。样本带 `citations`（来源引用）
  亦然——届时 `"attributed"` 才能配得上 schema 的来源保证。
- 新形态的 `run_investigator` 输出（带 system/degraded/timeout）跑
  一轮后，用本适配器复测，对比 legacy 形态下 system 回答的占比。
- `evaluate()` 接线（#88 合并后）：已落地（本增量）。CLI 或 study 侧加 `--quality-report`
  选项，适配 → 评估 → 报告一次完成；`evaluate_adapted` / `evaluate_file` /
  CLI `--report` 即此接线，首次实测已由测试固定在 CI 内。
- 证据页 degraded 标题的歧义（标题显示 AI 答案、警告行显示规则答案）
  与 system-score 读法不一致，应由上游定夺哪一方是「运用者看到的回答」；
  在此之前适配器按 system-score 读法，并在本文中明示分歧。
