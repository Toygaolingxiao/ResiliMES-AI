# explain 层剥离：现状与清单

这份文档记录 `resilimes/explain` 从仓内剥离的进度。目标不是现在拆仓，而是让将来拆仓只需要一次 `git filter-repo` 加改名。背景见 `docs/DEV_ARCHITECTURE.md`。

## 规则

- `resilimes.explain` 只依赖标准库、pydantic、`resilimes.common`、`resilimes.data` 和它自己。
- 它通过两个面使用孪生：
  - 读运行记录：`explain.record.Timeline`，接口是 `explain.interfaces.RunRecordSource`。
  - 再演服务：`explain.interfaces.ReplayService`。explain 只调用，不碰 `_Sim`。
- 孪生侧的适配器在 `resilimes/evidence/`，负责从模拟结果生成运行记录和 Evidence Schema。explain 不 import 它。
- `decide()` 和优先度不放进 explain。
- 故障注入基准的运行框架放在工房区（目前是 `insight/injector.py`、`hard_cases.py`、`study.py`），由它调用 explain。

规则由 `tests/test_explain_boundary.py` 检查，CI 里有单独一步 `Explain boundary`。检查有两种：
- 静态检查：沿 `resilimes.*` 的 import 一路追下去，间接依赖也算。
- 运行时检查：在新进程里 import 全部 explain 模块，再看 `sys.modules`。

禁止的包：`smt`、`engines`、`agents`、`kernel`、`domain`、`insight`、`evidence`、`llm`、`api`、`demo`、`txn`。

没用 import-linter：box 上的 pip 装不了新包，而 pytest 检查不需要新增依赖，效果相同。以后要换成 import-linter 也可以。

## 这次 PR 做了什么

| 内容 | 之前 | 之后 |
| --- | --- | --- |
| JSON 提取和 schema 校验 | `agents/jsonutil.py` | `common/jsonutil.py`，旧路径保留转发 |
| 文本里的 id 和数字核对 | `agents/facts.py` 里的 `narrative_mismatches`、`_numbers`、`_norm` | `common/textfacts.py`，`agents.facts` 继续导出 |
| 事实核查 | `evidence/factcheck.py`（依赖 `agents.facts`，间接依赖 `domain`） | `explain/factcheck.py`，旧路径保留转发 |
| 延误拆分 | `evidence/lateness.py` | `explain/lateness.py`，旧路径保留转发 |
| SQL 守卫 | `evidence/sqlguard.py` | `explain/sqlguard.py`，旧路径保留转发 |
| 运行记录类型 `Timeline`、`Visit`、`Gap`、`Displacement` | `evidence/timeline.py`（直接依赖 `smt.fab`、`smt.simulate`） | `explain/record.py`。`evidence/timeline.py` 只保留 `build_timeline`，作为孪生侧适配器，并转发旧名字 |
| Evidence Schema v0 | 没有 | `explain/schema.py` |
| 两个公开面 | 没有 | `explain/interfaces.py`：`RunRecordSource`、`ReplayService`、`ReplayRequest` |
| 孪生侧适配器 | 没有 | `evidence/adapters.py`：`TwinRunRecord`、`TwinReplayService`、`lot_evidence` |

`resilimes/` 里原来 import `agents.jsonutil` 和 `evidence.factcheck/lateness/sqlguard` 的地方，已经改成直接 import 新位置。测试仍走旧路径，这样转发也一直有测试覆盖。

### Evidence Schema v0

- `schema_version` 固定为 `evidence/v0`。
- `content_hash`：去掉 hash 字段后，对规范化 JSON（按 key 排序、不转义）取 SHA-256，格式是 `sha256:<hex>`。任何字段一改，hash 就变。
- 每一项都有 `tier`：
  - `recorded`（記録）：直接来自运行记录，必须有 `sources`。
  - `attributed`（観測帰因）：按固定规则从观测中拆出来，比如按机台数分摊排队时间。也必须有 `sources`。
  - `unknown`（不明）：记录里没有原因，必须写 `reason`。
- 延误各桶的分层写在 `LATENESS_TIER` 里：
  - 加工、换线、搬送、投入保留：`recorded`。
  - 停机、PM、凑批、前面的 lot、Q-time、AI 决定：`attributed`。
  - `dispatch_other`（有空闲机台但记录里没有原因）：`unknown`。
- 契约测试在 `tests/test_explain_contract.py`。它固定了字段集合、分层规则、hash 的稳定性和防篡改，还检查适配器生成的 bundle 加总后等于延误时间。这些测试只要有一条需要改，版本号就必须跟着升。

## 依赖现状（这次 PR 之后）

`explain/` 全部通过边界检查。下面是剩下的、还直接依赖孪生或工房区的文件。

| 文件 | 依赖 | 定位 |
| --- | --- | --- |
| `evidence/timeline.py` | `smt.fab`、`smt.simulate` | 孪生侧适配器，留在外面 |
| `evidence/toolkit.py` | `smt.fab`、`smt.faults`、`smt.simulate` | 混合：`record_run` 属于适配器；`Toolkit` 里的查询本应只读 `Timeline`，但 `RecordedRun` 带着 `RunResult`、`FaultPlan` |
| `evidence/fab_ops.py` | `evidence.toolkit` | 跟着 `Toolkit` 走 |
| `evidence/sqlrun.py` | `config`、`agent.tools_zetaris` | 执行 SQL，有 I/O，留在外面 |
| `evidence/adapters.py` | `smt.fab`、`evidence.toolkit` | 孪生侧适配器，留在外面 |
| `insight/explainer.py` | `evidence.toolkit`、`llm` | 解释逻辑，但调用了 `record_run` 做反事实重跑，需要改成调用 `ReplayService` |
| `insight/gaps.py` | `smt.dispatch_log` | 需要把 `DispatchRecord` 也变成运行记录的一部分 |
| `insight/context_investigation.py` | `kernel.score`、`evidence.toolkit`、`llm` | `class_tier` 要挪到 common，或者由记录带出 |
| `insight/handover.py` | `engines.contracts`、`engines.markovian` | 交接摘要，依赖引擎，暂不进 explain |
| `insight/deliberation.py`、`gap_explainer.py`、`notes.py` | `llm` | 已经不依赖 agents；LLM 调用接口要不要放进 explain，还没定 |
| `insight/investigator.py` | `evidence.toolkit`、`evidence.sqlrun`、`insight.injector`、`llm` | 和注入基准耦合 |
| `insight/injector.py`、`hard_cases.py`、`notes_cases.py`、`notes_ab_live.py`、`study.py` | `smt.*` | 故障注入基准和实验，属于工房区，留在外面 |

## 剩下的清单

1. 拆 `Toolkit`：只读 `Timeline` 的查询搬进 `explain`；`RecordedRun` 和 `record_run` 留在适配器侧。
2. `insight/explainer.py` 的反事实重跑改成调用 `ReplayService.replay`，然后把解释逻辑搬进 `explain`。
3. `smt.dispatch_log.DispatchRecord` 改成运行记录里的普通数据，之后搬 `insight/gaps.py`。
4. `kernel.score.class_tier` 挪到 `common`，或者由记录带出，之后搬 `context_investigation.py`。
5. 想清楚 LLM 调用接口（`llm.base.Completer`）怎么处理：是做成 explain 自己的一个协议，还是让 explain 完全不碰 LLM，只负责证据和核查。
6. explain 单独打包：自己的 `pyproject`（或 hatch/uv workspace 的子包）、单独的测试目录和 CI 任务，做到能单独安装、单独跑通。
7. Import 页和 Report 页直接读 Evidence Schema；Report 页显示 `content_hash`，用来复核。
8. 产品区页面和工房区页面分目录。

## 什么时候该拆仓

满足下面任一条就该拆：

- 第一个设计伙伴要在自己的环境本地部署，而他们不应该拿到孪生、engines、agents 的代码。
- 决定开源 Evidence Schema 或公开基准。
- 数据或代码有许可、保密限制，需要和产品代码隔开。SMT2020 数据集的使用条款要自己核对，还没核对。
- 两边的发布节奏开始不同。
- 品牌、商标和域名核查通过，需要独立的仓库名。

出现第二个贡献者只算弱信号：一个仓库多人开发很常见，单靠这一条不拆。
