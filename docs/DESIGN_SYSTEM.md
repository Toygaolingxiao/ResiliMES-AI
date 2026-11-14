# ResiliTrace 设计系统基线（design-system/v0）

这是 ResiliTrace 产品页面的第一份设计系统基线。按执行标准第四节：
第一次动页面之前，先定一套自洽的基线；后续页面增量在这套基线内保持
一致，确需改基线先更新本文档。

本文档由两部分组成，逐节标注：**[既成]** 是已上线代码里的事实
（逐字核对过源码）；**[新定]** 是本次为后续页面增量新立的定义与
规则，尚未在任何页面落地。**单独合入本文档不约束任何页面**——
基线只在页面增量按它实现时才生效；在那之前，它是一份待执行的
定义，不是一份已生效的标准。

本基线不改任何现有 CSS/JS，不落地任何页面。Cases 页与 quality 页
改造是后续增量，按本基线实现。

来源（全部可核查，不引无法兑现的值）：

- `resilimes/demo/static/styles.css`（`:root` 浅色 token 与
  `html[data-theme="dark"]` 深色覆盖；首行注释称 IBM Carbon，
  见仓根 `DESIGN.md`——该文件是营销画布分析文档，不是控制台
  设计文档，此处只引注释本身）
- `resilimes/demo/static/product/report/report.css`（档位徽标色）
- `resilimes/demo/static/i18n.json`（档位三语标签）
- `resilimes/explain/schema.py`（`TIER_LABEL_JA`）与
  `resilimes/explain/cases.py`（`SEVERITIES`、`SUGGEST_*` 阈值、
  状态机；PR #90 未合并，引用时标注状态）
- 对比度为本次计算（WCAG 相对亮度公式，见 §6；浅色 10 组对应
  已上线渲染，深色 8 组对应拟议值，未经渲染实测）

## 1. 原则 [新定]

1. **证据高于装饰**：界面上的每个数字必须带分母或来源；追溯不到
   就删或标未知。百分比永远不单独出现（见 §5）。
2. **复用，不另起**：新页面先用本基线的 token；不得引入第二套
   颜色、字阶或间距。同一时期内只存在一套视觉语言。
3. **档位与严重度是两套语义**：三档（記録 / 観測帰因 / 不明）说
   证据可信度；四档严重度（critical / major / minor / info）说
   跟进优先级。两者颜色可以复用同一色板，但徽标上必须带文字
   标签，绝不能只靠颜色区分（见 §2.4 的非颜色区分维度）。
4. **不明是一等公民**：空状态要写清为什么空、补什么数据会不空；
   错误状态要给出下一步动作；推断在视觉上与事实区分开。
5. **密度优先**：面向工程师的高信息密度布局优先于营销式大留白；
   表格可扫读，数字右对齐。

## 2. 色板（token）

规范源：**`styles.css` 的 `:root` 为主**。`report.css` 自有
`:root`（`--ink/--muted/--line/--ground/--paper` 及档位色），与
`styles.css` 同值不同源——这是既成双源状态，本基线不定合流时间，
只规定：新页面引用 token 时以 `styles.css` 的值为准；`report.css`
的档位对逐步合流，合流由页面增量在 PR 中声明。

### 2.1 表面与文字 [既成]（`styles.css :root`，浅色 / 深色）

| token | 浅色 | 深色 | 用途 |
| --- | --- | --- | --- |
| `--ground` | `#f4f4f4` | `#161616` | 页面底 |
| `--card` | `#ffffff` | `#1e1e1e` | 卡片面 |
| `--sheet` | `#f4f4f4` | `#262626` | 表单面 |
| `--ink` | `#161616` | `#f4f4f4` | 正文 |
| `--muted` | `#525252` | `#c6c6c6` | 次要文字 |
| `--subtle` | `#6f6f6f` | `#a8a8a8` | 辅助文字（**死 token**：已定义，全仓无 `var(--subtle)` 引用；新页面不得用它作正文色，见 §6） |
| `--line` | `#e0e0e0` | `#393939` | 分隔线 |
| `--line-strong` | `#c6c6c6` | `#525252` | 强分隔线 |
| `--field-line` | `#8d8d8d` | `#6f6f6f` | 输入框边线 |
| `--layer-hover` | `#e8e8e8` | `#333333` | 悬停面 |
| `--track` | `#e8e8e8` | `#333333` | 进度轨 |

### 2.2 状态色 [既成]（`styles.css`，浅色 / 深色）

| token | 浅色 | 深色 | 用途 |
| --- | --- | --- | --- |
| `--alarm` / `--alarm-ink` / `--alarm-wash` | `#da1e28` / `#a2191f` / `#fff1f1` | `#fa4d56` / `#ff8389` / `#3a1517` | 停机、违规、失败 |
| `--amber` / `--amber-fill` / `--amber-mark` / `--amber-wash` | `#8e6a00` / `#f1c21b` / `#b28600` / `#fcf4d6` | `#f1c21b` / — / `#f1c21b` / `#302400` | Q-time 风险、警告（深色无 `--amber-fill`；注意浅色 `--amber-fill #f1c21b` 与深色 `--amber #f1c21b` 同值不同角色） |
| `--good` / `--good-wash` | `#198038` / `#defbe6` | `#42be65` / `#071908` | 准时、通过 |
| `--accent` / `--accent-hover` / `--accent-active` / `--accent-ink` / `--accent-wash` | `#0f62fe` / `#0050e6` / `#002d9c` / `#ffffff` / `#edf5ff` | `#78a9ff` / `#a6c8ff` / `#d0e2ff` / `#161616` / `#001d6c` | **主要的**交互蓝（不是唯一：`--cyan` 用于 setup 灯/色块，`--violet` 用于 `.links`，`report.css` 还硬编码 `#0f62fe`） |
| `--hot` / `--hot-fill` / `--hot-wash` | `#9f1853` / `#d02670` / `#fff0f7` | `#ff7eb6` / — / `#3a0a22` | hot lot |
| `--violet` / `--cyan` | `#8a3ffc` / `#0072c3` | `#be95ff` / `#33b1ff` | 辅助区分 |
| `--pm` | `#6f6f6f` | `#a8a8a8` | 计划停机 |
| `--rework-ink` | `rgba(22, 22, 22, 0.5)` | `rgba(255, 255, 255, 0.55)` | 返工文字 |

文字色规则 [既成 + 新定]：现状是 `--amber`、`--good`、`--alarm`
在既有代码中**亦作文字色**（`.badge` 用 `var(--amber)`、
`.badge.live` 与 `.kpi .sub .good` 用 `var(--good)`、
`.kpi .sub .bad` 用 `var(--alarm)`），且 **`--amber-ink` 这个
token 根本不存在**——浅色 attributed 的文字色就是 `--amber`
本身。新页面规则：文字色优先用 `*-ink` 与
`--ink/--muted`；沿用 `--amber/--good/--alarm` 作文字色时，
须保持 §6 的对比度（`--amber` 只可用于 12–13px 以上的小字
标签，不得用于大段正文）。`--subtle` 不得作正文色（死 token，
见 §6 的 4.10:1）。

### 2.3 证据档位 [既成：浅色；新定：深色]（`report.css`）

| 档位 | 标签 ja / zh / en（`i18n.json` `report.*`） | 浅色 wash / ink [既成] | 深色 wash / ink [新定，未落地] |
| --- | --- | --- | --- |
| `recorded` | 記録 / 记录 / Recorded | `#edf5ff` / `#0043ce` | `#001d6c` / `#a6c8ff` |
| `attributed` | 観測帰因 / 观测归因 / Observed attribution | `#fcf4d6` / `#8e6a00` | `#302400` / `#f1c21b` |
| `unknown` | 不明 / 不明 / Unknown | `#f4f4f4` / `#525252`，边线 `--line` | `#262626` / `#c6c6c6`，边线深色 `--line` |

档位徽标沿用 `report.css` 的 `.tier` 几何 [既成]：行内块、
`margin-left: 8px`、字号 12px、左右 padding 6px、
`border: 1px solid transparent`——注意 recorded/attributed 的
边线是透明占位（不可见），只有 unknown 有可见的 `--line` 边线。
档位标签取自 `i18n.json`，不硬编码；取不到时回退显示原始 tier
key（现有 `tierName` 行为，`report.js:38` 与 `import.js:52`
均为 `copy()[tier] || tier`）。

**已知缺口**：`report.css` 没有深色覆盖，report/import 页在深色
主题下仍按浅色渲染。本基线只定义深色档位对，不改代码；深色落地
由页面增量实现并在 PR 中声明。

### 2.4 案件严重度与状态 [新定；定义来源 `cases.py`，PR #90 未合并]

严重度复用 §2.2 已有的色对，不引入新颜色；类名待页面增量加为
`.sev-critical` 等（目前不存在）：

| 严重度 | 浅色 wash / ink（复用） | 深色 wash / ink（复用） | 定义（`cases.py`） | 建议阈值（仅建议，永不自动指定） |
| --- | --- | --- | --- | --- |
| `critical` | `#fff1f1` / `#a2191f`（alarm 对） | `#3a1517` / `#ff8389` | 迟到量级达到需立即升级处理的程度 | 迟到 ≥ 120 分钟 |
| `major` | `#fcf4d6` / `#8e6a00`（amber 对） | `#302400` / `#f1c21b` | 明显迟到，本班内需要决定 | 迟到 ≥ 30 分钟 |
| `minor` | `#edf5ff` / `#0043ce`（recorded 对） | `#001d6c` / `#a6c8ff` | 迟到但本班可吸收 | 迟到 > 0 分钟 |
| `info` | `#f4f4f4` / `#525252`（unknown 对） | `#262626` / `#c6c6c6` | **未迟到**，作为观察项跟踪（如 near-miss） | 迟到 = 0 分钟 |

硬规则（来自 `cases.py`，页面不得违反）：严重度**永远由人指定
并写 `severity_reason`**，建议函数 `suggest_severity` 永不自行
指定；指定值与建议值不一致时须有显式理由。`info` 只用于未迟到
的观察项，不得用于已迟到的案件。

**非颜色区分维度** [新定]：`minor` 与 `recorded` 共用蓝对、
`info` 与 `unknown` 共用灰对——这是有意的复用，不是语义等同。
仅靠 12px 文字标签区分是不够的（案件行内会同时出现严重度徽标
与其证据包的档位徽标），因此规定两条硬性区分：

1. 形状：严重度徽标在 `.tier` 几何之外，左侧加 3px 实色边
   （`border-left: 3px solid <ink>`）；档位徽标保持 1px 全边框。
2. 位置：案件表内严重度固定首列，档位固定证据列；两者永不同处
   一格、不在同一行无栏目标题并置。

状态词（open / investigating / resolved / dismissed）[新定]：
纯文字，不配专属色——**禁止用红/绿暗示好/坏**。补偿机制：状态
固定一列显示，列表须支持按状态分组/筛选；history 逐条列出变迁。
状态不是终态：`resolved` 与 `dismissed` 均可重开
（`resolved → open/dismissed`、`dismissed → open/investigating`
均为合法变迁，`cases.py` 状态机）。分工说明：校验页既有的
`.pill.pass`（绿）/`.pill.fail`（红）是“校验通过/失败”的惯例，
与案件状态是两个概念，不得混用。

严重度与状态的三语文案尚未进入 `i18n.json`（本次核查：`cases`
键 0 结果）。Cases 页增量须先补以下键（ja / zh / en 三语，文案
由该增量定，不在本基线编造译文）：`cases.severity.critical`、
`cases.severity.major`、`cases.severity.minor`、`cases.severity.info`、
`cases.status.open`、`cases.status.investigating`、
`cases.status.resolved`、`cases.status.dismissed`。缺键回退规则
[新定]：缺键时显示英文标签，不显示原始 key（档位回退显示原始
key 是档位的既成行为，不沿用到严重度与状态）。

## 3. 字阶、间距、圆角、动效 [既成]（`styles.css`）

| token | 值 | 用途 |
| --- | --- | --- |
| `--text-micro` | 12px | 徽标、哈希、辅助说明 |
| `--text-label` | 13px | 标签、表格、次要行 |
| `--text-body` | 14px | 正文（默认） |
| `--text-title` | 16px | 卡片标题、分区标题 |
| `--text-kpi` | 28px | KPI 大数字（须配分母，见 §5） |
| `--text-display` | 32px | 仅控制台空状态标题（`#empty-title`），不是首页 hero 大标题 |
| `--track-body` | 0.16px | 正文字距 |
| `--track-caption` | 0.32px | 小字字距 |
| `--s1` / `--s2` / `--s3` / `--s4` | 4 / 8 / 12 / 16px | 间距阶梯，只用这四档 |
| `--radius` / `--radius-sm` | 0 / 2px | 方角为主；徽标与小控件可用 2px |
| `--fast` / `--moderate` / `--slow` | 110 / 180 / 240ms | 状态变化动效；缓动 `--ease` |

字重 [既成]：400 / 500 / 600 为主；另有 **300**（KPI 大数字
`.kpi .value`、`.bottleneck-fig`、`.fx-tile strong` 与空状态标题
`#empty-title`）与 **650**（`.wip-line .label`）。度量卡大数字用
`--text-kpi` 时字重取 300，与既成渲染一致，不得按“只用
400/500/600”改写。

行高 [既成]：控制台正文 1.43（`styles.css` body），report 页正文
1.5（`report.css` body）——两者并存，新页面按所在页面类型取对应
值，不统一为其中一个。

断点 [既成]：`styles.css` 现有 5 处宽度断点——
`min-width: 1500px`、`max-width: 1440px`、`max-width: 1320px`、
`max-width: 1279px`、`max-width: 1023px`，另有
`prefers-reduced-motion: reduce`。新页面沿用这五档，不另发明；
响应式细节（哪档改几列）由页面增量在 PR 中列明。

字体：IBM Plex Sans（正文）/ IBM Plex Mono（数字、id、哈希），
本地 vendored；CJK 回落系统 Noto。标题 600，正文 400。

## 4. 组件清单 [新定为主；既成处注明]（新页面按此实现；既有组件不动）

| 组件 | 规则 |
| --- | --- |
| 档位徽标 `.tier` | §2.3；文字标签必有；推断（attributed）旁须可达其规则说明（report 页既有 `whyNote` 写法） |
| 严重度徽标 `.sev-*` | §2.4；文字标签 + 3px 左实边 + 固定首列，三者缺一不可 |
| 状态词 | 纯文字，不配专属色（§2.4）；固定一列 + 分组/筛选补偿；变迁历史逐条列出（cases/v0 的 history 形态） |
| 度量卡 | 比率型：大数字（`--text-kpi`，字重 300）+ 分子/分母 + 样本量；聚合型（如 ECE）：大数字 + 总样本量 + 定义，不编造分母；样本为 0 时不显示 0%，显示空状态（见 §5） |
| 证据表 | 数字列右对齐 + `tabular-nums`（既成规则是 `td.num, th.num`，只对表格单元格有效，`class="num"` 放 div/span 上无效）；id 与哈希用 `--mono`，哈希行 12px、参与哈希的 JSON 全文（`.canonical`）11px；每行结论旁可达来源行与 `content_hash` |
| 举证约束 | Cases 页不得把 history 时间戳呈现为可信审计时间（`content_hash` 不覆盖时间戳，`cases.py` 已声明）；负责人字段不存在，须明示“负责人：未指定”，不得让界面暗示有人在跟进 |
| 空状态 | 写清为什么空 + 补什么数据会不空；不只写「暂无数据」 |
| 错误状态 | 写清失败原因 + 下一步动作（重试、换文件、联系谁）；不只写「加载失败」 |
| 语言切换 | 沿用现有三语（ja / zh / en）与 `localStorage` 键 `resilimes.lang`；**新文案三语齐备才合入**，缺一语不合入（不设“标缺放行”）；译文质量由合并者审 |

## 5. 数字与空样本规则 [新定]

- 百分比必须同时显示分母与样本量，例如 `11/12` 而不是 `92%`；
  分母为 0 时不显示百分比，显示「无样本」+ 原因。空样本原因由
  页面按数据源状态推导（如“尚未接入故障注入基准”），原因来源
  须在页面增量中写明，不得编造。
- 质量度量（quality/v0 的三项）的口径以 `docs/QUALITY_METRICS.md`
  为准；**该文件在 PR #88 中，尚未合入 main**——在本基线合入时，
  该引用待 PR #88 合并后生效，在此之前口径未定。页面只呈现，
  不重定义口径。
- 现状缺口（本次核查，均属实）：① `product/quality/quality.js`
  的百分比（如 `utilization_pct`、`on_time_delivery_pct`）目前只
  显示 `toFixed(1) + "%"`，不带分母——这是 quality 页改造（开发
  队列第 4 项）要修的问题，本基线不声称已修；② `product/report/report.js:159-161`
  与 `product/import/import.js:132-134` 的档位覆盖率同样是裸百分
  比（`${tierName} ${percent}%`），无分母——这两页不在第 4 项范围
  内，归属为后续增量（提案见 PR 正文），或由 Toygaolingxiao 豁免
  并说明理由。
- 迟到时长、分钟数等量纲数字一律带单位；`content_hash` 全文
  显示或可展开，不截断后声称已核验。

## 6. 无障碍底线（WCAG AA）[新定：规则；数字：本次计算]

- 正文与背景对比度 ≥ 4.5:1；大字（≥ 24px 或 19px 加粗）≥ 3:1。
  下表为本次用 WCAG 相对亮度公式算出的值：浅色 10 组对应已上线
  渲染；**深色 8 组是拟议值的计算结果，未经渲染实测**。底色选取
  规则：`muted`/`subtle` 按白底计；另列 `--subtle` 在常用底色上
  的值（见表后警告）。

| 色对 | 对比度 |
| --- | --- |
| recorded `#0043ce` / `#edf5ff` | 7.09:1 |
| attributed `#8e6a00` / `#fcf4d6` | **4.52:1（边界值）** |
| unknown `#525252` / `#f4f4f4` | 7.10:1 |
| alarm-ink `#a2191f` / `#fff1f1` | 7.09:1 |
| good `#198038` / 白 | 5.02:1 |
| good `#198038` / `#defbe6` | 4.55:1 |
| muted `#525252` / 白 | 7.81:1 |
| muted `#525252` / `#f4f4f4` | 7.10:1 |
| subtle `#6f6f6f` / 白 | 5.02:1 |
| ink `#161616` / `#f4f4f4` | 16.45:1 |
| accent-ink 白 / `#0f62fe` | 5.00:1 |
| 深色 recorded `#a6c8ff` / `#001d6c`（拟议） | 8.85:1 |
| 深色 attributed `#f1c21b` / `#302400`（拟议） | 9.05:1 |
| 深色 unknown `#c6c6c6` / `#262626`（拟议） | 8.86:1 |
| 深色 alarm-ink `#ff8389` / `#3a1517`（拟议） | 6.82:1 |
| 深色 good `#42be65` / `#071908`（拟议） | 7.63:1 |
| 深色 muted `#c6c6c6` / `#161616`（拟议） | 10.59:1 |
| 深色 subtle `#a8a8a8` / `#161616`（拟议） | 7.61:1 |
| 深色 accent-ink `#161616` / `#78a9ff`（拟议） | 7.68:1 |

  **边界警告**：浅色 attributed（4.52:1）与浅色 good-on-wash
  （4.55:1）只比 AA 线高一点；后续增量不得把 ink 调浅或把
  wash 调深，否则跌破 AA。另：`--subtle #6f6f6f` 在 `#f4f4f4`
  上为 4.57:1（仅高出 0.07），在 `#e8e8e8`（`--layer-hover` /
  `--track`）上为 **4.10:1，低于 AA**——该组合是否在已渲染界面
  实际出现未逐一核实，此处只陈述算术事实，不 claim 已有违规
  页面；新页面不得在 `#e8e8e8` 底上用 `--subtle` 作文字色。
- 状态不只靠颜色区分：档位与严重度同时有文字标签；通过/失败
  同时有文字。
- 交互元素有可见焦点；关键数据不放在仅悬停可见的位置；键盘
  可达新页面的主要操作。

## 7. 信息架构 [新定：方向提案；现状：既成]

现状 [既成]（本次核查）：控制台 `index.html` 有 **5 个 panel**
（recover/analyze/verify/fab/ai）；tab 由 `console.js` 的
`paintTabs` 渲染，为 4 个基础 tab（Plan/Metrics/Checks/AI）+
fab 启用时 7 个 fab 子 tab（Overview/Tools/Product flow/Lots/
Furnace batches/Event log/Daily KPIs），**共 11 个，fab 子 tab 在前**。
产品分区按目录是 evidence / explanation / import / quality /
replay / report 六个，Cases 还没有位置；quality 页仍是旧排程
KPI 面板（开发队列第 4 项待改造）。路由只有两条：`/report` 与
`/import`；evidence / explanation / quality / replay 没有独立路由。

新构成 [新定：方向提案，具体路由与导航由页面增量落地]：

| 分区 | 内容 | 与现状的差异 |
| --- | --- | --- |
| Cases | 按 lot 的未关闭案件、严重度排序、跟进轨迹 | **新增**一等分区；复盘入口优先（见下） |
| Evidence | 证据包、档位覆盖 | 现状保留；只按本基线统一徽标与数字规则 |
| Explanation | 一 lot 的解释 | 现状保留 |
| Import | MES 日志导入与可达档位 | 现状保留（`/import` 路由不变） |
| Quality | 信任度量（quality/v0 三项） | **改造**：旧排程 KPI 不删除，另设视图并行；空样本明示无样本（开发队列第 4 项）。**默认视图未定**，列为第 4 项增量的必答项 |
| Replay | 复演评估 | 现状保留 |
| Report | 只读举证报告 | 现状保留（`/report` 路由不变，打印样式不变） |

取舍：

- **Cases 排第一是提案，不是定论**：理由是生产管理者的复盘第一
  动作是分诊待办；但三类人第一动作不同——fab 工程师先查一 lot
  为何晚（Explanation/Report），质保先举证。Cases 尚无页面、无
  持久化（内存台账、无负责人、无等待态）、依赖未合并 PR #90，
  初期入口指向的是无数据的空状态。因此：Cases-first 在 Cases 页
  落地且有真实数据后再确认为默认顺序；在此之前，工程师与质保的
  直达路径（深链到 Explanation/Report）不受影响，不得为推 Cases
  而绕路。
- **不合并、不改名现有分区**：六个旧分区的名字保持，只新增 Cases、
  只改造 Quality 内容。避免一次重组同时动导航、路由与内容，无法
  回滚。
- **Quality 的旧 KPI 仍有人看**，删除是破坏性变更，改为并行视图。
- **归档设计稿只作参考**：`docs/feedback/2026-11-12-claude-resilitrace-design.html`
  的全页构成不作为本基线的来源；本基线只从已上线代码取 token。
  今后页面增量如借鉴该稿，须在 PR 中列出与本基线的差异及取舍。

迁移关系：既有链接 `/report`、`/import` 与控制台 tab/panel 不变；
新增 `/cases` 路由由 Cases 页增量加；`i18n.json` 新增键由各页面
增量补，三语齐备才合入。

## 8. 版本与变更规则 [新定]

- 版本 `design-system/v0`。改任一 token 须同步改本文档与对应
  CSS，同一 PR；不许只改一处造成文档与代码不一致（文档与代码
  不一致视为缺陷）。
- 检查机制（本基线可执行的部分）：① grep 校验——文档引用的每个
  色值须能在 `styles.css` 或 `report.css` 中逐字 grep 到（深色档
  位对与严重度色对的单个 hex 值本身也在 `styles.css` 深色块中，
  grep 只验“值存在”，**验不出“配对”是否正确**——配对正确性由
  审阅者在 PR 中对照 §2.3/§2.4 的表人工核对）；② 页面增量 PR
  须附 §4 清单逐项自查；③ 译文三语齐备由 grep `i18n.json` 验证。
  机器校验脚本（自动比对本文档 token 表与 CSS）是后续增量的提案，
  本基线不声称已有。
- 换基线就整体换并在 PR 中明示；同一时期内不并存两套视觉语言。
- 重申：单独合入本文档不约束任何页面；基线在页面增量落地前不生效。

## 9. v0 局限（未实现、未核实）

- 深色档位对（§2.3）与严重度色对（§2.4）只定义、未落地代码；
  `report.css` 本身无深色覆盖。`.sev-*` 类名、`cases.*` i18n 键
  均不存在，待页面增量落地。
- 严重度与状态的三语文案未进 `i18n.json`，待 Cases 页增量补。
- quality 页百分比无分母（§5 缺口①）待第 4 项改造；report/import
  覆盖率裸百分比（§5 缺口②）归属后续增量；本基线不声称已修。
- 本基线未规定动效细节——沿用 `styles.css` 的 `--fast/--moderate/--slow`
  与既有缓动；响应式沿用 §3 的五档断点，未规定各档列数，细节由
  页面增量定。
- 归档设计稿（1.4MB 单文件）未作为来源采纳；其构成与本基线的
  差异未逐项比对，如未来借鉴须在 PR 中列明。
- `cases.py` 与 `quality.py` 均在未合并 PR（#90 / #88）中，
  本基线引用它们时已标注状态；若合并时改动字段名或阈值，基线须
  跟随更新。`docs/QUALITY_METRICS.md` 的引用待 PR #88 合并后生效。
- `--subtle` 在 `#e8e8e8` 底上的 4.10:1 低于 AA（§6）：该组合是否
  在已渲染界面实际出现未逐一核实；新页面禁用该组合。
