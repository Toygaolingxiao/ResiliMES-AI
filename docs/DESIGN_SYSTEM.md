# ResiliTrace 设计系统（design-system/v1）

对应规划：`docs/LAYOUT_UNIFICATION_PLAN.md` §三（Wave 0 / #121）。
令牌唯一源：`docs/design/tokens.json`。生成物：`docs/design/TOKENS_REVIEW.md`（`python scripts/regen_tokens_review.py`）、`resilimes/demo/static/design/tokens.css`（`python scripts/regen_tokens_css.py`）、`resilimes/demo/static/design/tokens.js`（`python scripts/regen_tokens_js.py`）。控制台在 `styles.css` 之前链接 `tokens.css`。

## 0. 版本与效力

- 版本 **`design-system/v1`**（本文件由 v0 升版；v0 局限见文末迁移说明）。
- **文档与代码不一致视为缺陷。** 令牌表以 `tokens.json` 为源；Wave 1 起 review / CSS / JS 均由同一套生成器产出（棘轮测试见 §10）。
- 合入本文件 + tokens + 棘轮即约束后续增量：新代码不得抬高 `VIOLATION_BUDGET.json`；抬高预算须同步更新 `docs/design/VIOLATION_BUDGET_BASELINE.json`（测试 `test_budgets_do_not_exceed_baseline` 仅强制执行预算 ≤ 基线），并在 PR 正文说明理由（人工复核，测试不检查）；守卫清单项不得无声消失。
- 契约语义仍遵守全仓原则：**additive payloads only**。

## 1. 原则

1. **证据高于装饰**：数字带分母或来源；追溯不到则删或标未知。
2. **复用，不另起**：同一时期一套视觉语言；timeline **chrome** 并入本系统，**数据色**走 chart 登记（决策 1）。
3. **同角色同令牌**：完成绿的文字 / 浅底 / 图形可以是三个语义 token，禁止把不同角色捏成「一个值」。
4. **档位与严重度两套语义**：档位 = 证据可信度；严重度 = 跟进优先级。徽标必须带文字，不能只靠颜色。
5. **不明是一等公民**：空要说清为什么；错要给下一步；推断与事实必须可辨。
6. **密度优先**：工程师高信息密度；表格可扫读；数字右对齐 + `tabular-nums`。
7. **正常态中性**（ISA-101）：颜色留给异常；状态色与分类色分开。

## 2. 令牌架构

```
primitive  →  semantic（按角色，含 light/dark 映射）  →  component（仅偏离时）
                                                      ↘ chart（甘特/热力等，浅/深各一份）
```

### 2.1 语义色（摘录；完整表见 TOKENS_REVIEW）

| 角色 token | 浅色 | 深色 | 用途 |
| --- | --- | --- | --- |
| `--ink` / `--muted` | `#161616` / `#525252` | `#f4f4f4` / `#c6c6c6` | 正文 / 次要 |
| `--ground` / `--card` | `#f4f4f4` / `#ffffff` | `#161616` / `#1e1e1e` | 底 / 卡片 |
| `--text-success` / `--bg-success-subtle` / `--graphic-success` | `#198038` / `#defbe6` / `#24a148` | `#42be65` / `#071908` / `#42be65` | 成功：字 / 底 / 图 |
| `--text-danger` / `--bg-danger-subtle` | `#a2191f` / `#fff1f1` | `#ff8389` / `#3a1517` | 危险 |
| `--text-warning` / `--bg-warning-subtle` / `--graphic-warning` | **`#684e00`** / `#fcf4d6` / `#f1c21b` | `#f1c21b` / `#302400` / `#f1c21b` | 警告（决策 3） |
| `--text-info` / `--bg-info-subtle` | `#0043ce` / `#edf5ff` | `#a6c8ff` / `#001d6c` | 记录档 / 信息 |
| `--accent` | `#0f62fe` | `#78a9ff` | 主交互 |

`--text-warning` 及全部 `text-*` / `graphic-*` 对比度由 `text_contrast_rows()` 脚本入 CI（字 4.5:1，图形对 card 3:1）。测试：`test_text_warning_contrast_clears_aa`（含 `#684e00` 回归）。

### 2.2 证据档位

| 档位 | ja / zh / en | 浅 wash / ink | 深 wash / ink |
| --- | --- | --- | --- |
| recorded | 記録 / 记录 / Recorded | info 对 | 深 info 对 |
| attributed | 観測帰因 / 观测归因 / Observed attribution | warning 对（字色走 `--text-warning` 迁移） | 深 warning 对 |
| unknown | 不明 / 不明 / Unknown | gray 对 | 深 gray 对 |

几何：`.tier` 为唯一貌（Wave 2① 契约化）。缺 tier → 失败安全显示「不明」。非颜色冗余必有。

### 2.3 案件严重度语义

| 级 | 色对（复用） | 含义 | 期望响应 |
| --- | --- | --- | --- |
| critical | danger | 须立即升级 | 本班立刻动作 |
| major | warning | 本班内须决策 | 当班处理 |
| minor | info | 可吸收偏差 | 跟踪 |
| info | unknown 灰 | 未迟到的观察项 | 记录 |

形状：严重度左侧 3px 实边；档位 1px 全边。位置：严重度首列，档位证据列。

### 2.4 Chart vs chrome（决策 1）

- **Chrome（并入）：** 顶栏、字体、控件、焦点、主题、轴标签、网格、tooltip 外壳。
- **Chart（登记保留）：** 甘特条、热力格、泳道分类色、编码数据的图例点。
- canvas：运行期 `getComputedStyle` 读变量 → 缓存 → 主题变更重绘（Wave 1c）。

## 3. 字阶、间距、控件、动效

| token / 规则 | 值 | 说明 |
| --- | --- | --- |
| `--text-micro` … `--text-display` | 12 / 13 / 14 / 16 / 28 / 32 px | 既有六档 |
| CJK | 最小 12；正文 13–14 | fab 字阶等场景答复（工位 vs 看板） |
| 行高 | 按 lang：拉丁应用 ~1.43；CJK 正文 1.6–1.8；表 ~1.5 | 禁止全站锁死 1.43 |
| 控件/行高阶梯 | **24 / 32 / 40 / 48** | 决策 2；`.run` = 32 |
| 间距 lint | 允许数值集合；不强制 var() | 6/10 不入基线 |
| 断点 | 1500 / 1440 / 1320 / 1279 / **1023** | 外档并入最近 |
| 圆角 | 0 / 2px | |
| 动效 | 110 / 180 / 240ms | `prefers-reduced-motion` 必备 |
| 字体 | IBM Plex Sans/Mono + **显式 CJK 栈** | 混排基线；数字 `tabular-nums` |

## 4. 组件

| 组件 | 规则 |
| --- | --- |
| `.tier` | §2.2；单一 `renderTier`；缺省「不明」 |
| `.sev-*` | §2.3；文字 + 3px 左边 + 固定首列 |
| `.run` / `.run.quiet` | 主/次按钮；min-height 32 |
| 输入 | 控制台下划线 / 表单盒式；`--field-line`；radius 0 |
| `.field-error` | #117 范式推广 |
| 表格 | 数字右对齐 + tabular-nums；`.num` 单一定义 |
| `.kpi` / `.card` | 几何统一；色走语义层 |
| 浮层 | tooltip / 菜单 / 面板三规格 |
| 详情（决策 4） | hover 显示 → 点击钉住 → 再点本体取消；键盘可达；甘特浮层为例外 |
| 空 / 错 | 三段式空态；错误四要素 |
| 语言 | ja/zh/en；`resilimes.lang`；缺键 CI 红 |

画廊：`/design`（Wave 2 起）— 组件 × 状态 × 主题 × 语言。

## 5. 数字与截断

- 百分比必带分母/样本量；分母 0 显示「无样本」+ 原因。
- 凡 slice/上限/省略：同屏「显示 X / 共 Y」或展开路径，并**写明排序依据**。
- 单元格截断必须有详情承载（决策 4 模型）。

## 6. 状态十一条

见规划 §三「状态层」。摘要：双通道、加载三件套、空三段、错四要素、截断明示、#117 校验、i18n/Intl、a11y 底线、**陈旧数据**、**长耗时作业生命周期**、**高影响预览/确认/可撤销**。

## 7. 无障碍（WCAG 2.2 AA 清单）

- 1.4.3 / 1.4.11：字 4.5:1；非文字 3:1（`tests/test_style_budget.py::test_text_warning_contrast_clears_aa` + `text_contrast_rows()`）。
- 1.4.13：悬停/聚焦内容可关闭、可停留、不消失 → 决策 4 钉住模型。
- 2.4.7 / 2.4.11：焦点可见且不被粘性顶栏遮挡。
- 2.5.8：目标 ≥ 24×24 CSS px。
- 3.3.1 / 3.3.3 / 4.1.3：错误识别/建议/状态消息（#117）。
- canvas：甘特须有**等价表格视图**（Wave 3 单列一件）。
- `forced-colors` / `prefers-reduced-motion`。
- `/report` 打印：颜色编码的非颜色形态；长表表头重复（决策 5）。

## 8. 骨架

顶栏 48px（品牌/返回 + 页名｜语言 + 主题）→ 标题 → 筛选 → 状态行 → 内容 → 空/错。
`/report`：**840px 定宽保留**（决策 5）；共享组件与全站同构，整页骨架可不同。
窄幅 ~400px：**不承诺**。

## 9. 信息架构（方向）

Cases / Evidence / Explanation / Import / Quality / Replay / Report — 既有路由不变；Cases-first 待有真实数据后再定默认顺序。

## 10. 防回潮

| 机制 | 路径 |
| --- | --- |
| 违规预算棘轮 | `docs/design/VIOLATION_BUDGET.json` + `docs/design/VIOLATION_BUDGET_BASELINE.json`（冻结基线） + `tests/test_style_budget.py` |
| 守卫清单棘轮 | `docs/design/GUARD_CHECKLIST.json` + `tests/test_guard_checklist.py` |
| 令牌生成一致性 | `tests/test_guard_checklist.py::test_tokens_review_matches_generator`、`test_tokens_css_matches_generator`、`test_tokens_js_matches_generator` |
| 截图矩阵完整性 | `tools/screenshot-baseline/matrix.json` + 同文件测试 |
| 截图捕获 | `tools/screenshot-baseline/`（不给 app 加构建步骤） |

## 11. 自 v0 的迁移说明

- v0 中「同义同值」「间距仅 4/8/12/16 且必须 var()」「行高两值锁死」已按 #121 决策与评议作废，以本 v1 为准。
- v0 深色档位对 / `.sev-*` 仍可能未在 CSS 落地：Wave 1–2 实施；定义以 tokens.json 为准。
- `--subtle` 不得在 `#e8e8e8` 上作正文（对比度 4.10:1）。
- 单独改文档不代替代码迁移；预算棘轮保证迁移期间不回潮。
