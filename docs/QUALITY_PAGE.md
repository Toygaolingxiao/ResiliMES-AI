# Quality 页改造 v0（信任度量视图）

实现：`resilimes/demo/static/product/quality/quality-report.js`（新）、
`resilimes/demo/static/product/quality/quality.js`（`paintAnalyze` 加视图切换）；
契约测试：`tests/test_quality_page.py` + `tests/fixtures/quality-report-sample.json`；
接线测试：`tests/test_frontend_dirs.py::test_quality_report_page_wiring`。
口径：`docs/QUALITY_METRICS.md`（quality/v0，PR #88 未合并，本文引用时标注状态）；
设计基线：`docs/DESIGN_SYSTEM.md`（PR #91 未合并，§7 的 Quality 改造方向）。

## 构成（标准第四节：新构成的理由、与现状的差异及取舍）

现状：控制台 Metrics（analyze）面板是旧排程 KPI 面板（`paintAnalyze`），
百分比裸显、无分母（基线 §5 缺口①）。本次不新增 tab、不新增路由，
在 Metrics 面板内加并行视图切换：

- **KPI 视图**（默认）：既有排程 KPI 卡片，原样保留，可达、不删除。
- **信任视图**（Trust metrics）：quality/v0 的三项度量 + 校准 + 样本计数，
  数据来自用户加载的 QualityReport JSON 文件（内存-only）。

默认视图的抉择（基线 §7 列为第 4 项增量的必答项）：**默认 KPI**。
理由：① 目前不存在任何实测 QualityReport（故障注入基准适配是开发队列
第 1 项的剩余增量，待 PR #88 合并后进行），默认信任视图会让所有既有
用户先看到一个空状态；② KPI 面板是工程师每日复盘的工作面，改默认是
破坏性变更。实测报告落地后，由后续增量重议默认视图；切换状态只存在
`state.qualityView`（内存），不持久化（后续增量可记 `localStorage`，
与 `resilimes.lang` 同机制）。

三类人分别的使用场景（标准第三节第一问）：

- **fab 工业工程师查某 lot 为何晚**：本页**不回答**单 lot 原因——信任
  视图只有聚合度量，无从度量钻取到 lot、样本或案件，无指向
  Explanation/Report/Cases 的链接。工程师仍走既有路径（右键 Gantt
  问 why、Explanation/Report）；钻取（drill-down）记为后续增量。
- **生产管理复盘**：本页服务的是复盘时刻的聚合判断——三项比率各带
  分母、校准分箱与样本计数，可与“上次基准的同一张表”对照；但本页
  不给通过/不通过阈值，也不存历史报告，对照须人工拿两份文件比。
- **质保/客户审核举证**：本页**暂不能支撑对外举证**——报告无 run
  id、时间戳、基准配置字段（见 v0 局限），且文件未经验证（每张内容
  卡均标「未验证文件」）；质保现阶段只能用本页做内部筛查，正式举证
  仍走 Report 页。

与 Cases 页（PR #92）的取舍差异：Cases 页是新 tab（新分区），Quality
页是同一面板内的视图切换——因为 Quality 的旧内容仍有人看、须并行，
而 Cases 是新增内容、没有旧内容要保留。两者文件加载模式一致（文件读
取、校验、正規化、只读、内存-only、5 MB 上限、世代 guard），以便用户
学一次、用两次。

## 数据契约

输入：`QualityReport` JSON（quality/v0，`resilimes/explain/quality.py`
的 `evaluate()` 导出）。页面只消费 JSON，不 import `quality.py`，
故 quality.py 仍在未合并 PR #88 时本增量也可开工；合并顺序要求见下。

校验（`validateQualityReport`）以 pydantic 模型
（`QualityReport` / `Rate` / `CalibrationBin`）为基准，分两类：

**与模型一致的部分**：顶层键白名单；`metrics_version` 若缺失视为
`quality/v0`，若存在须等于 `quality/v0`；`calibration_bins` /
`expected_calibration_error` 若缺失补既定值（`[]` / `null`）；
`Rate.value` 在分母为 0 且缺失时视为 `null`；6 个计数字段须为 ≥ 0
整数，接受数字字符串（`"12"`、`"12.0"`、`"+12"` 接受，指数写法
`"1e3"` 拒绝——已用 pydantic 实测核对）；三项比率须为
`{numerator, denominator, value}`：分子 ≤ 分母；分母 0 时 value 须
为 null；分母 > 0 时 value 须等于分子/分母（误差 ≤ 1e-9，与
`quality.py` 的 `Rate` 校验一致）；校准分箱每项须为 `{lower,
upper, count, mean_confidence, accuracy}`，count ≥ 0 整数，
mean/accuracy 为有限数或 null。

**比模型严格的部分（有意偏离，JS 拒绝、Python 接受）**：

1. **空箱的 mean/accuracy**：count 0 的箱须带 null，否则拒绝。
   真实 `evaluate()` 导出恒为 null；fixture 的
   `bin_accuracy_without_count` / `bin_mean_without_count` 覆盖此偏离。
2. **范围**：`expected_calibration_error` 与各箱 mean/accuracy 须
   在 [0, 1] 内。模型本身无范围约束，链上无他处检查，故本页检查；
   fixture 的 `ece_out_of_range` / `bin_mean_out_of_range` 覆盖此偏离。
3. **跨字段一致性**：`answered + unknown_answers ==
   total_samples`；`over_unknown` 分母须等于 `truth_known`；
   `misattribution` 分母不得超过 `truth_known`；`unknown_share`
   分母须等于 `total_samples`；各箱 count 之和须等于
   `calibration_samples`。`evaluate()` 的输出恒满足这些；fixture
   的 `inconsistent_counts` / `inconsistent_bins` /
   `inconsistent_denominators` 覆盖此偏离。`calibration_bins`
   缺失时按 `[]` 计，故 `calibration_samples > 0` 且无分箱的报告
   同样被拒（fixture 的 `missing_bins`）。
4. **分箱几何**：每箱须 `lower < upper`，且 lower 单调不减；fixture
   的 `bin_geometry` 覆盖此偏离。

校验错误详情是英语字段路径（与 Cases 页相同；完全三语化是后续
增量）。错误超过 50 条时截断并明示（5 MB 恶意文件不致攒出数万条
错误；显示时仍只列前 20 条并计数余数）。

正規化（`normalizeQualityReport`）：补 `metrics_version` /
`calibration_bins` / `expected_calibration_error` /
分母 0 缺失 `Rate.value` 的既定值，数字字符串转数字；不重算任何比率。

## 显示规则（基线 §4/§5）

- 比率卡（复用既有 `.cards` / `.card`）：大数字（`--text-kpi`、字重
  300）是百分比，下一行是分子/分母的文字（如 `2/7 judged answers`）；
  分母为 0 时不显示 0%，显示「无样本」——0.0 是测量结论，None 是还没测。
- 三张卡的含义（口径见 `QUALITY_METRICS.md`）：误归因率（开口归因且
  真值已知中说错的比例）、过度不明率（真值已知中仍答不知道的比例）、
  不明占比（全部样本中答不知道的占比——描述统计，不是质量结论）。
- 校准卡：ECE 大数字（3 位小数）上方无标签是不行的——数字下标
  `ece`（期望校准误差）与定义行 `eceDef`（各箱 |准确率−平均置信|
  的样本加权平均，越小越名副其实；暂无通过/不通过阈值）；校准样本
  数 + 无置信排除数在 `calibrationNote` 句中；分箱表 10 行（或报告
  所给的全部行），每行给区间、件数、平均置信、准确率；空箱的平均
  置信与准确率显示「—」；区间按原值打印（最多 3 位小数去尾零，不
  四舍五入到 0.1 网格），末位 `[0.9, 1]` 双闭，其余左闭右开。
- 样本计数卡：样本总数 / 已回答 / 不明回答 / 真值已知（四行两列表）。
- 来源说明：**每张内容卡底部均标「未验证文件」短句**（三张比率卡、
  校准卡、样本计数卡各一）；load 卡另有完整说明（数字按文件所报原
  样展示，本页不重算；手写文件与真实导出无法区分）。单张卡的截图
  也带警示。
- 空状态：未加载报告时写清为什么空（尚无服务端数据）与补法
  （`evaluate()` 导出后加载，quality/v0 实现随 PR #88 合入，口径见
  `QUALITY_METRICS.md`）；目前尚无实测报告的原因写明（故障注入
  基准适配是后续增量）。
- 错误状态：无效文件列出全部校验理由（最多 20 条，余数计数），不加载
  任何内容；文件 > 5 MB 拒绝；非 JSON 说明解析失败原因；错误卡底部
  有三语下一步指引（重新导出、确认 `metrics_version` 为 quality/v0；
  字段路径详情仍为英语）。
- 滚动与焦点：信任视图重绘时保留面板滚动位置；文件选择框获得焦点时
  重绘后恢复焦点（与 Cases 页同款处理）。
- 响应式：沿用既有断点，不另发明；`.cards` 三列在窄屏下的行为与既有
  KPI 卡一致，不另行规定列数。

## 意図的な乖離（与 `quality.py` 的差异，均有意）

校验比 pydantic 模型严格的四项（见「数据契约」节）：（1）空箱的
mean/accuracy；（2）ECE 与 mean/accuracy 的 [0, 1] 范围；（3）跨字段
一致性；（4）分箱几何。另有两项与模型无关的页面决定：校验错误详情
是英语字段路径（与 Cases 页相同；完全三语化是后续增量），以及分箱
行数——模型接受任意长度的 `calibration_bins`（缺省为空元组），本页
接受任意行数并按原样渲染，缺省时显示「无校准分箱」；`evaluate()`
恒出 10 行。

其余有意保留的“不做”：

- **ECE 与 mean/accuracy 的范围检查不在 `quality.py`**：模型无范围
  约束，本页补了校验；若 `quality.py` 后续版本加范围约束，本页
  校验与之重合，无冲突。
- **信任视图的名称**：`信任度量 / Trust metrics` 沿用基线 §7 的叫法；
  页面本身不验证任何东西，诚实性由每张卡的「未验证文件」短句与
  load 卡的完整说明承担，不由名字承担。
- **`trustTitle` 的 `(quality/v0)`**：写的是本页实现的契约版本，不
  是所加载文件的版本（校验已拒绝其他版本）；契约升级时随代码改。

## v0 局限（未实现、未核实）

- 无服务端数据：`quality.py` 在未合并 PR #88，故障注入基准适配未做；
  目前没有任何实测 QualityReport 可加载，信任视图现阶段只能加载
  人工构造或测试导出的报告。
- 无 `/api/quality` 端点；无持久化；无状态迁移（只读）；视图选择不
  持久化（每次访问默认 KPI）。
- **无解读锚点**：本页不给任何通过/不通过阈值；小样本下比率与 ECE
  都不稳定，阅读时以分母与校准样本数为准（ECE 定义行已写明暂无阈值）。
- **无 provenance**：`QualityReport` 无 run id、时间戳、基准配置字段，
  页面也无处展示这些；即使文件是真实导出，也无法确认它对应哪次基准
  运行、哪个版本——**暂不能支撑对外举证**。后续增量在 quality/v0.x
  或 v1 中给报告加 run id / 时间戳 / 基准配置字段。
- 浏览器实机渲染（tab 切换、文件读取、视图切换、滚动/焦点保持）
  未核实：本次只有代码审查 + TestClient 配信确认 + node parity（含
  quality-report.js 缺失时的回退驱动）+ 视图切换焦点恢复的代码审查。
  AC1/AC2 的渲染部分（切换按钮按下态、卡片实际外观）目前是人工核对，
  无 DOM 渲染自动化测试。
- 校验错误详情英语-only（见上）；错误卡的下一步指引已三语化。
- 三位审核员的修订版未再送审；修订内容为审核意见的直接落实，无新主张。
- `QUALITY_METRICS.md` 与 `DESIGN_SYSTEM.md` 均在未合并 PR 中；若
  合并时改动口径、字段名或基线，本增量须跟随更新。
- parity 测试在 quality.py 未合入前是 fixture-based：edge 的 `valid`
  标志是生成 fixture 时 `model_validate` 的返回（生成脚本实测），
  但测试本身在 #88 合并前不执行模型；`test_quality_fixture_matches_model`
  在 #88 合并后自动接通双向断言。

## 验收标准（given/when/then）

1. 默认打开 Metrics 面板时看到既有 KPI 卡片，顶部有两枚视图切换按钮，
   KPI 为按下态；切换到信任视图后看到空状态（未加载报告 + 原因与补法）。
2. 加载 fixture 的真实 `evaluate()` 导出后，三张比率卡显示
   `28.6%`（2/7）、`30.0%`（3/10）、`33.3%`（4/12），ECE 显示
   `0.333`，分箱表 10 行且空箱显示「—」，样本计数 12/8/4/10。
3. 加载分母为 0 的空报告后，比率卡显示「无样本」而不显示 0%。
4. 加载 30 类 edge 报告后，校验结果与 Python 判定一致（除 9 项已声明
   的偏离：空箱 mean/accuracy、ECE/mean 超范围、跨字段不一致、分箱
   几何缺失、缺失分箱且校准样本 > 0——JS 更严、拒绝加载）；缺失 ECE
   与分母 0 缺失 value 的报告两边都接受。
5. 三语切换后 `quality.*` 41 键齐备，无缺键回退到英语原文键名；
   `docs/i18n_review.md` 已再生成。
6. `tests/test_quality_page.py`（node parity，含 quality-report.js
   缺失时的回退驱动）与
   `tests/test_frontend_dirs.py::test_quality_report_page_wiring` 通过；
   explain 回归测试全过；`node --check` 通过。

测试逐条对应：AC1 由接线测试 + 人工核对（渲染部分无 DOM 自动化
测试，见 v0 局限）；AC2/3/4 由 `tests/test_quality_page.py` 的 parity
corpus 覆盖（node 驱动；ECE 与分箱 6–9 的 mean/accuracy 已断言）；
`test_quality_fixture_matches_model` 在 PR #88 合并后自动接通与模型的
双向断言，在此之前跳过；AC5 由 `tests/test_i18n.py`（键集合一致）+
再生成；AC6 由 pytest 通过本身。

## 依赖与合并順序

- **本 PR 是 PR #88（quality.py / QUALITY_METRICS.md）的后合并**。
  先合并会使 main 只有页面而无契约实现与口径文档。PR 正文に明記。
- **合并前复核清单**（#88 合并时逐项打勾，语义漂移时页面会静默显示
  旧口径数字）：① 字段名（`QualityReport` / `Rate` /
  `CalibrationBin` 的全部字段与本页校验器一致）；② 三项比率的
  分母定义与分箱边界（0.1 等宽、末箱双闭）未变；③ 版本仍为
  `quality/v0`（口径变则版本须升）；④ `test_quality_fixture_matches_model`
  在合并后的树上通过（它在 #88 合并前跳过，合并后自动接通）。
- 与 PR #90 / #91 / #92 无文件重叠（#92 改 `index.html` 的 cases
  script 行与 `styles.css` 末尾、`.cases` 规则、`i18n.json` 的
  `cases` 节；本增量改 `index.html` 的 quality-report script 行
  （在 quality.js 之前）、`styles.css` 的 `.analyze` 区块内规则、
  `i18n.json` 的 `quality` 节（在 report 之后、import 之前），
  锚点均不相同；`tests/test_frontend_dirs.py` 本增量只在文件末尾追加
  新测试函数，不改 #92 改过的既有测试）。合并时若仍冲突，按
  #88 → #90 → #91 → #92 → 本 PR 的顺序解决；`docs/i18n_review.md`
  是生成文件，冲突时以合并后的 `i18n.json` 为准重新生成，不得整文件
  取一边。
- 回滚：revert 本 PR 的单一提交（分支 `Muse/resilitrace-20261115-pm`），
  Metrics 面板恢复为只有 KPI 视图；既有 tab/页面不受影响。
- 回退安全：`quality-report.js` 加载失败（404）时 `paintAnalyze`
  回退到 KPI 视图，不拖垮控制台绘制；`tests/test_quality_page.py`
  有对应的 node 回退驱动。

## 非目标

- 不做故障注入基准适配（第 1 项剩余增量，待 #88 合并后）。
- 不接 `/api/quality`（无端点）；不做持久化；不做报告对比（多报告并排）。
- 不改 report/import 页的裸百分比（基线 §5 缺口②，归属后续增量）。
- 不改 KPI 视图的任何数字与口径（旧百分比无分母的问题，信任视图不
  覆盖 KPI 视图；KPI 视图的分母化是后续增量）。
- 不改 `QUALITY_METRICS.md`（#88 未合并，冲突回避）；不碰排程核心。
