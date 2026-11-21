# 全站页面整理与布局统一规划图（修订版 · Wave 0）

拟制：2026-11-22（Muse）｜修订：2026-11-22（Wave 0 / #121）
审查对象：原版对照 main `46093b5f`；本修订对照合入 Wave H（#123）后的 main
跟踪单：[Issue #121](https://github.com/Toygaolingxiao/ResiliMES-AI/issues/121)
关系：展开《控制台交付加固章程》工作线 4；评议稿见 `LAYOUT_UNIFICATION_PLAN_REVIEW.md`（保留为立项附件，不改写）

---

## 〇、修订说明（相对原版销账）

| 原问题（评议 §11 等） | 本修订处置 |
| --- | --- |
| 49 条头条未去重 | §一改用去重后计数；附录 A 保留三路原始 |
| 严重度无标尺 | §一.2 写入「影响面 × 频率 × 可逆性」+ 硬规则 |
| 第三节间距与决策点 2 矛盾 | §三按决策 2 改写：控件/行高 24/32/40/48；终态不再写死 4/8/12/16-only |
| 「二选一写死」canvas 取色未决 | 定为运行期读 CSS 变量 + 缓存 + 主题变更重绘 |
| 截图基线无人负责 | Wave 0 已落地 `tools/screenshot-baseline/` |
| 4b 与章程线 1 条件句 | Wave H 已先行 `/report` seq+busy；章程线 1 后做时在其 PR 内吸收复核 |
| 行高 1.43 与 CJK 未对账 | §三按语言分配行高令牌；CJK 最小 12 / 正文 13–14 |
| 附录 B 与语义层未对齐 | 收敛表注明「同角色同令牌」，`.kpi` 类走语义层 |
| 「返回」与独立页落点 | §三骨架：独立页顶栏「回控制台」为默认；多入口不另造同名 `.back` |
| Wave H / M7 过时条目 | §四标注已合入；挑战性复核见 §八 |

---

## 一、审查结论（去重后）

### 1.1 计数

三路原始合计见附录 A（49 = 高 9 / 中 24 / 低 16，含跨路重复）。
**去重后：37 条（高 7 / 中 18 / 低 12）**——去掉 timeline 独立体系、令牌未引用、档位多貌等跨路重复项。

### 1.2 严重度标尺

| 因子 | 高 | 中 | 低 |
| --- | --- | --- | --- |
| 影响面 | 主流程或证据可信度 | 单页/单组件 | 局部样式 |
| 发生频率 | 每次关键操作 | 常见路径 | 边角 |
| 可逆性 | 用户无法自行恢复或会误判 | 可绕过但成本高 | 仅观感 |

**硬规则：** 凡会让用户对**系统状态**或**证据强度**作出错误判断的，至少为「高」。
按此标尺：cases 档位缺失（误把推断当记录）= 高；同义绿三值（角色不同）= 低（改「同角色同令牌」，不强制并成一个值）。

### 1.3 四个结构性事实（仍成立；状态随 Wave H / M7 更新）

**事实 1：全站有三套视觉语言。** 控制台（Carbon + IBM Plex）、report/import（同值字面量）、timeline（Slate + Avenir，文件头自陈例外且基线未登记）。→ 高，Wave 3 收敛 chrome。

**事实 2：证据档位多种貌。** report `.tier`、coverage 仅子类、控制台 `.chip`、cases 在 Wave H 后有文字「不明」但仍无统一徽标；evidence/explanation/quality/replay 仍无档位 UI。→ 高（可信度）；完整契约化 Wave 2①。

**事实 3：基线令牌立而不用。** `--s1..s4` 引用极少；6px/10px 高频；`#684e00` 无令牌（现定为 `--text-warning`）；断点/字阶表外值并存。→ 中（卫生），Wave 1 棘轮下降。

**事实 4：状态纪律两套并行。** 明示截断与静默截断并存；i18n 回退四套；时长格式三套。
- ~~控制台主流程静默失败~~ → **Wave H① 已修**（`runError` + Retry）。
- ~~/report 无在途防护~~ → **Wave H② 已修**（`loadSeq` + busy）。
- ~~无效 lot 进最近查看~~ → **Wave H④ 已修**。
- ~~focus_bars 静默截断~~ → **#119 / M7 已标 truncation 字段**（挑战性复核证伪「仍静默」）。

---

## 二、标杆清单（收敛目标长相，仓内已落地）

| 维度 | 标杆实现 | 出处 |
| --- | --- | --- |
| 严重度徽标 | `.sev`：色对 + var() + 3px 左边非颜色维度 | styles.css / cases.js |
| 字段校验 | 文案 + aria-invalid/describedby + 提交时移焦 + alert 去重 | report（#117） |
| 空状态 | empty + emptyWhy | cases / quality-report |
| 错误带下一步 | 错误卡 + fileErrorNext | quality-report |
| 比率口径 | 大号百分比 + 分母行常显 | qualityRateCard、fab tile sub |
| 截断明示 | 「显示 X / 共 Y」 | timeline scopeNotice、cases capped |
| 加载进度 | 进度条 + 状态文案 | 控制台 shift-lead |
| 重绘保状态 | 保持滚动与焦点 | paintCases / paintAnalyze |
| 主按钮（候选） | `.run`：accent、min-height 32px、radius 0 | styles.css |
| 失败持久化 | `runError` 不被 paint 擦除 + Retry | console.js（Wave H） |
| 在途防护 | seq + busy/disable | report.js（Wave H） |

原则（所有者订正，2026-11-21）：来源标注紧凑、可查、按需。

---

## 三、目标设计系统 v1（与 `DESIGN_SYSTEM.md` v1 逐条对应）

### 令牌层

- 唯一源：`docs/design/tokens.json`（`resilimes.design.tokens/v1`）。
- 仓内生成器（仿 i18n→i18n_review）：`scripts/regen_tokens_review.py` → `docs/design/TOKENS_REVIEW.md`；Wave 1 再增 CSS/JS 生成。
- **同角色同令牌**（非「同义同值」）：原始层 → 语义层（按角色）→ 组件层（仅偏离时）。
- `#684e00` → `--text-warning`（决策 3）；对比度由脚本给出（浅色常见底均 ≥6.4:1，见 TOKENS_REVIEW）。
- 图表数据色登记在 `tokens.json` 的 `chart`；浅/深各一份。
- canvas：**运行期**读 CSS 变量 + 缓存 + 监听主题变更重绘（非构建时常量）。

### 间距与控件阶梯（决策 2）

- **先定控件/行高：24 / 32 / 40 / 48**（`.run` 的 32 已是其一）；内边距由高度反推。
- lint 管**允许的数值集合**，不强制每个值写成 `var()`。
- 密度需求走紧凑/默认整体切换，不往基线塞 6/10。
- 画面落地后再由所有者终审间距观感（决策 2 原文）。
- 字号：`--text-*` 六档；CJK 最小 12px、正文 13–14px。
- 行高：按 `lang` 分配（拉丁应用 ~1.43；CJK 正文 1.6–1.8；表格约 1.5）。

### 断点与主题

- 五档：1500 / 1440 / 1320 / 1279 / 1023；fab 1200、timeline 720 并入最接近档。
- 每页必备：`@media print`、`prefers-reduced-motion`、全局 `:focus-visible`。
- report/import/timeline 补主题初始化；timeline 接入 IBM Plex（chrome）。

### 组件层

主按钮 `.run`、幽灵 `.run.quiet`、语言 `.langs`、输入两型、`.field-error`、表格（`tabular-nums`）、`.tier`（唯一貌）、`.sev`、`.pill`、`.kpi`、`.card`、浮层三规格、`.lamp`、`.swatch` 拆名。
领域组件（Wave 4 设计范围）：diff 行、约束违反卡、方案状态条、停止/接管入口。

### 骨架层

顶栏 48px → 页面标题 → 筛选区 → 状态行（一条 `role="status"`）→ 内容区 → 空/错误块。
独立页「返回」= 回控制台；父子关系用面包屑，不造同名异指的 `.back`。
`/report` 保留 840px 定宽 + 打印定位（决策 5）；打印时颜色编码须有非颜色形态、长表表头重复。

### 状态层（原八条 + 评议补三条 = 十一条）

1. 状态双通道：`role="status"` 与 `role="alert"`；禁止静默成功/失败；重绘不得覆盖未读错误。alert 仅用于必须立刻知道的打断型错误。
2. 加载三件套：文案 + 进度/量级 + 取消或超时去向；fetch 统一 seq + 在途禁用。
3. 空状态三段式。
4. 错误四要素：本地化说明、影响、下一步、旧数据标「未更新」。
5. 截断必明示 + **写明排序依据**（取前 N 的规则）。
6. 校验范式即 #117。
7. i18n：缺键 CI 失败；运行期回退英文仅兜底并上报；时长/数字走 Intl.*。
8. 无障碍底线：`:focus-visible`；非颜色冗余；关键信息不只在 hover（决策 4 的钉住模型除外且须满足 WCAG 1.4.13）。
9. **陈旧数据**：凡展示数据有时间戳与新鲜度（实时 / 缓存 / 已过期）。
10. **长耗时作业生命周期**：作业 ID、后台可跑、可取消、刷新后能找回、完成可通知。
11. **高影响动作**：预览差异 → 确认 → 可撤销/回滚入口。

### 详情面板（决策 4）

默认：**悬停显示 + 点击钉住；再点本体取消钉住**（所有者拍板；满足 WCAG 1.4.13 可关闭/可停留）。
行内展开仍可用于长表格场景（保持滚动与焦点）。甘特条等画布对象保留浮层为例外，登记在册。悬停不得单独承载关键信息。

### 严重度语义（ISA-18.2 取向，Wave 0 文档定；Wave 4 实施）

| 级 | 含义 | 期望响应 |
| --- | --- | --- |
| critical | 须立即升级 | 本班立刻动作 |
| major | 本班内须决策 | 当班处理 |
| minor | 可吸收的偏差 | 跟踪 |
| info | 未迟到的观察项 | 记录 |

状态色与分类色分开；**正常态默认中性**（ISA-101：颜色留给异常）。

### timeline chrome vs 数据色（决策 1 边界）

见 `docs/design/tokens.json` → `chrome_vs_chart`：轴/网格/标签/tooltip/顶栏/字体/焦点/主题 = chrome（并入全站）；甘特条/热力/泳道 = chart（登记保留，色盲安全 + 非颜色冗余）。

---

## 四、执行波次（#121 施工结构）

### 波次 H — **已合入 #123**

1. 控制台静默失败 → `runError` + Retry  
2. `/report` seq + busy  
3. cases 档位缺失 →「不明」  
4. 无效 lot 不进最近查看  

### 波次 0 — **本修订（文档 + CI）**

- 本文件修订 + `DESIGN_SYSTEM.md` v1  
- 截图基线工具 `tools/screenshot-baseline/`（矩阵 49 张定义；不给 app 加构建步骤）  
- 违规预算棘轮 `docs/design/VIOLATION_BUDGET.json` + `tests/test_style_budget.py`  
- 守卫清单棘轮 `docs/design/GUARD_CHECKLIST.json` + `tests/test_guard_checklist.py`  
- `tokens.json` 格式定版 + `regen_tokens_review.py`  
- 决策定版（§六）+ 挑战性复核（§八）  
- **未决：** fab 工位桌面 vs 远距看板（不阻塞其余）

### 波次 1：令牌层

语义层 + 深色映射 + 对比度脚本入 CI → 1a report / 1b styles+fab / 1c JS+canvas 运行期读取。1a/1b/1c 文件面不重叠时可并行。

### 波次 2：组件收敛

① 档位契约化（之首）→ 按钮/语言 → 输入 → 表格 → 徽标族 → 卡片/浮层；建 `/design` 画廊。

### 波次 3：页面骨架

timeline（最大件）→ report/import → 控制台内部 → fab；甘特等价表格视图单列一件。

### 波次 4：状态与文案

§三状态 9–11 实施；静默截断清零；i18n/CJK；出处收敛；导入页加固（#110 债）。

### 波次 5：验收

预算归零；三任务认知走查 + 5 秒测试；实机三语×两主题×两档宽；文档与代码由生成物保证一致。窄幅 ~400px：**不承诺**（非「未验证」）。

---

## 五、每页动作清单（速查）

| 页面 | 主要动作 | 波次 |
| --- | --- | --- |
| 控制台外壳 | `.swatch` 拆名、死令牌、panel 滚动、banner 合规 | 1b / 3c / 4 |
| console.js | JS 色板单源、浮层切语言重绘 | 1c / 4 |
| fab | 令牌化、字号入阶、断点并入、slice 明示；**字阶定版等 fab 场景答复** | 1b / 3d / 4 |
| quality | 静默 slice 明示 | 4 |
| cases | `.tier` 契约化（文字保底已在 H） | 2① |
| AI 证据 | 档位改挂 `.tier`、错误本地化 | 2① / 4 |
| /timeline | chrome 并入；数据色按决策 1 保留 | 3a |
| /report | 令牌化、顶栏主题、1023、打印 a11y（840px 保留） | 1a / 3b |
| /import | 同 report 骨架 + 截断改详情 | 3b / 4 |

---

## 六、决策定版与未决

| # | 决策 | 定版 | 来源 |
| --- | --- | --- | --- |
| 1 | timeline chrome | **并入全站**；数据色登记保留；边界见 tokens.json `chrome_vs_chart` | 所有者 2026-11-21 |
| 2 | 间距 | **控件/行高 24/32/40/48 先行**；画面出来后所有者终审；不扩 6/10 为基线 | 所有者 + 评议 |
| 3 | `#684e00` | **`--text-warning`**；脚本对比度：白底 7.84:1，amber-wash 7.11:1（均过 AA） | 所有者暂同 + 脚本 |
| 4 | 详情面板 | **hover 显示 + 点击钉住；再点本体取消**（WCAG 1.4.13） | 所有者 |
| 5 | report 骨架 | **保留 840px + 打印**；打印非颜色形态与表头重复 | 所有者 |

**未决（不阻塞 Wave 0/1）：** fab 视图是**工位桌面**还是**远距离看板**？字阶/观看距离依赖此答。请所有者在本单或后续评论答复。

---

## 七、非目标

- 不动排程核心与契约语义；呈现层字段只做加法（additive payloads）。
- 不做一次性大重写；WIP=1（视觉收敛）；Wave H 类热修已结束。
- 图表数据色不在「同角色合并」范围，只要求来源单一、登记在册。
- 窄幅 ~400px：**不承诺**移动端形态。

---

## 八、高发现挑战性复核

方法：以证伪为目标，对去重后高项对照合入 #123 后的代码（2026-11-22）。

| id | 主张 | 结论 | 证据摘要 |
| --- | --- | --- | --- |
| H1 | 三套视觉语言 | **成立** | styles/fab vs report 字面量 vs timeline `#1e293b` + Avenir |
| H2 | 档位多貌 / cases 不渲染 | **部分过时** | Wave H 后 cases 有文字档位/「不明」；仍无统一 `.tier` 貌；他模块仍无 |
| H3 | 令牌立而不用 / `#684e00` | **成立** | `--s*` 引用少；`#684e00` ×5 无令牌（现登记 `--text-warning`） |
| H4 | 控制台静默失败 | **已证伪（已修）** | `runError` + `statusLineFor`；契约测试 |
| H5 | /report 无在途防护 | **已证伪（已修）** | `loadSeq` + `setBusy`；契约测试 |
| H6 | quality/fab 静默 slice | **成立** | quality/overview 多处 slice 无「显示 X/共 Y」 |
| H7 | i18n 回退四套 | **成立** | ja 默认 / en 空串 / en 常量 / 时长三套 |
| H8 | `.swatch` 双定义 | **成立** | styles.css 圆点后被矩形覆盖 |
| H9 | focus_bars 静默截断 | **已证伪（已标）** | payload `truncated` + UI + `test_focus_bars_are_marked_when_cut_at_400` |

**仍为高、进入后续波次：** H1（Wave 3）、H2 契约化（Wave 2①）、H6（Wave 4）。H3 走预算棘轮（Wave 1）。H7/H8 中高，Wave 1–4。

---

## 附录 A：发现计数（三路原始，保留）

- 布局结构：高 3 / 中 8 / 低 3  
- 视觉令牌与组件：高 3 / 中 6 / 低 1  
- 交互状态与多语言：高 3 / 中 10 / 低 12  
- 合计原始 49；去重后见 §一.1  

## 附录 B：组件收敛表（Wave 2 依据）

| 组件 | 保留 | 动作要点 |
| --- | --- | --- |
| 主按钮 | `.run` | `.fx-btn`、`.tl-btn.primary`、report 提交并入 |
| 档位徽标 | `.tier` | 契约化 + 单一 `renderTier`；缺省「不明」 |
| 严重度徽标 | `.sev` | 已收敛（标杆） |
| 表格 | `table` + `.compare` | `.fx-table` 并入；`tabular-nums` |
| 度量卡 | `.kpi` | 几何并入；色走语义层 |
| 字段校验 | `.field-error` | 令牌化后推广 |
| 状态点 | `.lamp` | `.fx-dot` 等并入 |
| 图例 | `.swatch` 拆名后 | 先消双定义，再分圆/方 |

## 附录 C：Wave 0 交付物索引

| 产物 | 路径 |
| --- | --- |
| 本规划修订 | `docs/LAYOUT_UNIFICATION_PLAN.md` |
| 设计系统 v1 | `docs/DESIGN_SYSTEM.md` |
| 令牌源 | `docs/design/tokens.json` |
| 令牌表（生成） | `docs/design/TOKENS_REVIEW.md` |
| 违规预算 | `docs/design/VIOLATION_BUDGET.json` |
| 守卫清单 | `docs/design/GUARD_CHECKLIST.json` |
| 截图工具 | `tools/screenshot-baseline/` |
| 棘轮测试 | `tests/test_style_budget.py`、`tests/test_guard_checklist.py` |
