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

## 第一步（PR #79）做了什么

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

## 第二步做了什么

| 内容 | 之前 | 之后 | 原因 |
| --- | --- | --- | --- |
| LLM 协议 `Completer`、`LlmResult` | `llm/base.py` | `common/llm.py` | 只是协议和结果类型，没有 I/O。Nightshift 和 mock 这些实现留在 `llm/` |
| 时间预算 `deadline` | `llm/deadline.py` | `common/deadline.py` | 纯标准库。旧路径和新路径是同一个模块对象，测试里替换 `clock` 照样有效 |
| 进度行和 `redact` | `insight/progress.py` | `common/progress.py` | 通用小工具，explain 和工房区都在用 |
| `RunRecord` | 没有（`RecordedRun` 带着 `RunResult`、`FaultPlan`） | `explain/record.py` | explain 只读记录，不该碰模拟器对象。`RecordedRun` 改成它的子类，多出 `result` 和 `faults`，只在孪生侧用 |
| `Toolkit` | `evidence/toolkit.py` | `explain/toolkit.py` | 它的查询本来就只读 `fab`、`downs`、`pm` 和 `timeline`。`record_run` 留在 `evidence/toolkit.py`，作为孪生侧适配器 |
| `DispatchRecord` 和派工原因常量 | `smt/dispatch_log.py` | `explain/record.py` | 它是运行记录的一部分。模拟器按这个格式写记录，所以 `smt` 依赖 explain 的记录类型，方向是对的。`GapRecorder` 留在 `smt` |
| 空闲区间分类 `gaps` | `insight/gaps.py` | `explain/gaps.py` | 原来只因为 `DispatchRecord` 才依赖 `smt` |
| 空闲解释 `gap_explainer` | `insight/gap_explainer.py` | `explain/gap_explainer.py` | 只依赖 `gaps`、`factcheck` 和 LLM 协议 |
| Gantt 上下文问答 | `insight/context_investigation.py` | `explain/context_investigation.py`（`answer_context`） | `class_tier` 改成从记录读：`RunRecord.class_tiers` 由孪生侧按 `kernel.score.CLASS_TIER` 填，explain 不碰优先度规则。窗口查询要用的 `investigate` 改成注入（`WindowInvestigator` 协议）。旧入口 `insight.context_investigation.investigate_context` 会自动注入工房区的 investigator |
| 延误解释 `explainer` | `insight/explainer.py`（自己调用 `record_run` 重跑） | `explain/explainer.py` | 反事实重跑改成调用 `ReplayService.replay`（`verify_counterfactual`）。旧入口 `insight.explainer.verify` 默认传入 `TwinReplayService`；`base_run` 留在工房区 |

旧路径都还能用：
- `insight/gaps.py`、`gap_explainer.py`、`progress.py`、`llm/base.py`、`llm/deadline.py` 直接指向新模块，是同一个模块对象。
- `insight/explainer.py` 和 `context_investigation.py` 是薄入口，负责注入孪生侧或工房区的实现。私有名字会转给新模块，所以 `from ... import _x` 也还能用。

有一处测试改了：`test_gap_classification_keeps_dict_evidence` 原来替换的是 `sys.modules["resilimes.insight.gaps"]`，现在 `gaps` 在 explain 里，所以改成替换 `resilimes.explain.gaps`。断言没有动。

## 第三步做了什么

| 内容 | 之前 | 之后 | 原因 |
| --- | --- | --- | --- |
| 原因分类 `TAXONOMY`、`CAUSE_TEXT`、`main_upstream` | `insight/injector.py` | `explain/causes.py`，`injector` 转发 | investigator 和注入基准都要用。放在基准里，explain 就得依赖基准 |
| 窗口调查 `investigator` | `insight/investigator.py` | `explain/investigator.py`（`investigate_window`、`run_call`） | 分析逻辑只读 `Toolkit`。SQL 改成注入：`SqlRunner` 协议，不传 runner 时，`sql` 调用会像其他失败的调用一样返回 error。`settings` 只用来读时间预算，不再 import `config` |
| 旧入口 | — | `insight/investigator.py` 的 `investigate`、`execute` | 自动传入 `evidence.sqlrun.run_guarded`，行为和原来一样 |
| `context_investigation` 对 gaps 的动态 import | `import_module` 加 `except ImportError` | 直接 `from resilimes.explain import gaps` | gaps 已经在同一个包里了 |
| explain 单独打包 | 没有 | `packages/resilimes-explain/pyproject.toml` | 用 hatchling 打包，只带 `explain`、`common` 和 `data/zetaris_layout.py` |

关于 gaps 的改动：原来的“镜像分类”分支不只在 import 失败时走。当时间段里没有 gap 记录重叠时，它也会走。这条路径保留了，只把标签从“module not in this tree”改成“no gap record overlaps it”，因为原来的说法已经不对了。`test_gap_classification_keeps_dict_evidence` 原来替换 `sys.modules`，现在改成用 monkeypatch 替换 `gaps.gaps_from_run`，断言没动。

### 单独打包

- 安装和测试（在一个干净的环境里）：
  ```
  python -m pip install ./packages/resilimes-explain pytest
  cd packages/resilimes-explain && python -m pytest
  ```
- `packages/resilimes-explain/tests/` 是 explain 自己的测试。用的都是手工搭的小记录，不依赖孪生。
- CI 里新加了一个 job：`explain-alone`。它只安装这个包，先确认 import 到的是 site-packages 里的那份，再跑测试。
- 主仓的边界测试多了一条：explain 能 import 到的模块，必须都在这个包的 `force-include` 列表里。
- 不要和主包装在同一个环境里，因为两边都带 `resilimes/__init__.py`。
- 目前只做了 wheel。sdist 不行，因为 `force-include` 引用的是包目录外面的文件。真要拆仓时，把这些目录搬进包目录就行。

## 模块归属

**explain（产品侧）**：`record`、`schema`、`interfaces`、`toolkit`、`lateness`、`factcheck`、`sqlguard`、`gaps`、`gap_explainer`、`context_investigation`、`explainer`，第三步加上 `causes`、`investigator`。它们只读记录，再演只能通过 `ReplayService`。

**孪生侧适配器（`evidence/`）**：`timeline.build_timeline`、`toolkit.record_run` 和 `RecordedRun`、`adapters`。`fab_ops` 是把一次运行导出成 SQL 表，也留在这里。`sqlrun` 真正去执行 SQL，有 I/O 和配置，同样留在这里。

**工房区（`insight/`）**：
- `investigator`：第三步之后只剩薄入口，负责注入 `run_guarded`。
- `injector`、`hard_cases`、`notes_cases`、`notes_ab`、`notes_ab_live`、`study`：故障注入基准和实验，需要孪生给出真值，由它们去调用 explain。
- `handover`：交接摘要，依赖 `engines.markovian` 压缩和 `engines.contracts` 签名，属于引擎和交接流程。
- `deliberation`：三角色讨论，最后由 kernel 定，属于决策支持，不是解释。
- `notes`：把现场笔记转成排程事件，属于输入侧（以后的 Import 页），不是解释。

## 依赖现状（第三步之后）

`explain/` 全部通过边界检查。依赖只有标准库、pydantic、`common`、`data.zetaris_layout` 和 explain 自己。下面是还依赖孪生或引擎的文件：

| 文件 | 依赖 | 定位 |
| --- | --- | --- |
| `evidence/timeline.py`、`toolkit.py`、`adapters.py` | `smt.*`，`toolkit` 还依赖 `kernel.score` | 孪生侧适配器 |
| `evidence/sqlrun.py` | `config`、`agent.tools_zetaris` | SQL 执行，有 I/O |
| `insight/investigator.py` | `evidence.sqlrun` | 薄入口，注入 SQL |
| `insight/handover.py` | `engines.contracts`、`engines.markovian` | 工房区 |
| `insight/injector.py`、`hard_cases.py`、`notes_ab_live.py`、`study.py`、`notes_cases.py` | `smt.*` | 基准和实验 |
| `smt/dispatch_log.py` | `explain.record` | 模拟器按 explain 的记录格式写数据，方向是对的 |

## 剩下的清单

1. Import 页和 Report 页直接读 Evidence Schema；Report 页显示 `content_hash`。
2. 产品区页面和工房区页面分目录。
3. 旧路径的转发模块：等外部引用都改完以后再删。现在测试还在用旧路径，所以先留着。
4. 现在 explain 的版本号（`0.1.0`）和 Evidence Schema 的版本号是分开的，要定一下怎么对应。
5. 拆仓时，把 `explain`、`common` 和 `data/zetaris_layout.py` 搬进包目录，去掉 `force-include` 里的 `../../`，sdist 就能用了。
6. `smoke_test.py` 和根目录的 `pyproject.toml` 还是整包安装，主包里也还带着 explain。要不要让主包依赖 `resilimes-explain`，等拆仓时再定。

## 什么时候该拆仓

满足下面任一条就该拆：

- 第一个设计伙伴要在自己的环境本地部署，而他们不应该拿到孪生、engines、agents 的代码。
- 决定开源 Evidence Schema 或公开基准。
- 数据或代码有许可、保密限制，需要和产品代码隔开。SMT2020 数据集的使用条款要自己核对，还没核对。
- 两边的发布节奏开始不同。
- 品牌、商标和域名核查通过，需要独立的仓库名。

出现第二个贡献者只算弱信号：一个仓库多人开发很常见，单靠这一条不拆。
