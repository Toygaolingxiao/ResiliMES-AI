# Open Agent Hackathon 2026 — 比赛规则与评审标准（中文整理）

**抓取日期：** 2026-10-23（日本时间 UTC+9）

**官方来源：**
- [A] 官方活动页（主办方 GenAI.Works，平台 HackOS）：https://hackathon.genai.works/event/open-agent-hackathon-2026
  （含 About / Key dates / Tracks / Prizes & scoring / Official rules 共 10 节 / FAQ）
- [B] 官方 GenAI Academy 课程页：https://academy.genai.works/courses/open-agent-hackathon-2026/details
  （含课程大纲、工作坊时间、FAQ，其中有更细的赞助技术要求）
- 联系邮箱：hackathons@genai.works；Discord：https://discord.gg/tfwSeqVWmR
- 英文原文摘录见同目录 `HACKATHON_RULES_original.md`

> 说明：Academy 中的 “How the Week Runs: Tracks, Rules, Judging and Submission” 课程（官方称“完整规则/完整提交清单 (full checklist)”在此课中）需要登录且为 JS 渲染，**未能抓取**，其内容 **未在官网找到（需登录查看）**。

---

## 1. 比赛概览
- 名称：Open Agent Hackathon 2026；口号 “Build an agent that does real work.”
- 主办：GenAI Works（GenAI.Works）
- 赞助/合作方（Sponsors & partners）：NVIDIA、Zetaris、SpaceX AI（链接到 x.ai）、Meterless；Academy 页另列 Cursor 为赞助技术（Sponsor technologies: Zetaris, Cursor, Meterless and NVIDIA Nemotron）
- 形式：完全线上（Fully online），144 小时，6 天构建冲刺
- 队伍规模：1–5 人；免费参赛
- 目标：构建面向明确用户、解决真实问题的、可用于生产的 AI 智能体（production-oriented agents），**不是又一个聊天机器人或 demo**（not another chatbot or demo）；强调实用方案而非简单原型
- 技术分层（Academy）：
  - Data：通过 Zetaris 连接组织真实的碎片化数据
  - Build：用 Cursor 或任意 AI 编码工具 vibe coding，并实现一个 Meterless Engine（用于 memory、长任务、共享状态或意图路由）
  - Power：通过 Meterless Nightshift 在 NVIDIA Nemotron 上运行产品，“为每条通道选择合适的模型”(put the right model in each lane)
- 评委（Judges）：Michael Hay（Zetaris CTO）、Michael Armentano（SpaceXAI 技术合作负责人）、Sam Cummings、Shestakov Vladyslav、Remus Ranca（均为 GenAI Works）

## 2. 时间线
官方所有时间均为 UTC，“时区不会延长窗口”(Time zones do not extend the window)。

| 事项 | 官方时间 (UTC) | 日本时间 (JST, UTC+9) |
|---|---|---|
| 报名开放 Registration opens | 2026-08-14 00:00 | 2026-08-14 09:00 |
| Data Day 工作坊（Zetaris） | 2026-10-12 22:00（3 PM PT） | 2026-10-13 07:00 |
| Power Day 工作坊（Meterless + Nemotron） | 2026-10-19 22:00（3 PM PT） | 2026-10-20 07:00 |
| Build Day 工作坊（Cursor + Meterless） | 2026-10-21 04:00（Oct 20, 9 PM PT） | 2026-10-21 13:00 |
| Build Day Session 2 (APAC) | 2026-10-21 09:00 | 2026-10-21 18:00 |
| 入营说明会 Onboarding Call | 2026-10-21 12:00 | 2026-10-21 21:00 |
| **构建窗口开启 Build window opens** | 2026-10-22 00:00 | 2026-10-22 09:00 |
| **报名截止 Registration closes（硬截止）** | 2026-10-22 23:59 | **2026-10-23 08:59** |
| 开幕式 Opening Ceremony | 2026-10-23 09:00 | 2026-10-23 18:00 |
| 评审开启 Judging opens | 2026-10-27 00:00 | 2026-10-27 09:00 |
| **提交截止 Submissions close（硬截止）** | **2026-10-27 23:45** | **2026-10-28 08:45** |
| 结果公布 Results announced | 2026-11-06 16:00 | 2026-11-07 01:00 |

工作坊均有录像，可在课程中回看。

## 3. 参赛资格
- 全球开放，构建窗口开始时年满 16 岁（aged 16 or older）。
- 主办方及评审赞助方（judging sponsors）员工可参赛，但**不能获得现金奖**。
- 每人仅限一个账号；重复账号将导致**整队取消资格**。
- 组队：1–5 人，个人参赛与团队同池竞争；**首次创建提交时队伍成员锁定**，之前可自由加入/退出/合并；每人只能属于一个队；导师可指导任意队伍。
- 高校可申请 cohort code 将同校报名归组（邮件 hackathons@genai.works）。

## 4. 提交要求 / 交付物（Submission requirements）
提交平台：HackOS（Academy FAQ）。官方要求四项：
1. **演示视频 (demo video) 1–4 分钟**：展示主要工作流、智能体如何解决所选赛道挑战、关键功能，以及 Zetaris 与 Meterless 如何集成。Academy 补充：演示应展示**一次真实请求经过 Meterless Nightshift**，且**隐藏所有 key 和 token**。
2. **幻灯片 (slide deck)**：问题与目标用户、解决方案、智能体工作流或架构、技术栈、如何使用 Zetaris 和 Meterless、赞助技术使用的独特之处、产品视觉图 (product visuals)、未来改进 (future enhancements)。
3. **GitHub 仓库**：包含全部源代码，README 涵盖安装 (setup)、使用 (usage) 和依赖 (dependencies)；如在 Google Colab 运行需附 Colab 链接。
4. **赞助技术使用说明**：Zetaris 和 Meterless 如何集成、开发中如何使用 Cursor、NVIDIA 技术在哪里起作用、赞助技术使用的独特之处。Academy 补充：需说明**实现了哪个 Meterless Engine 以及证明其可用的测试 (the test that shows it works)**。
- 提交表单中须声明预先存在的产品代码（pre-existing product code）。
- 完整提交清单 (full checklist)：在 “How the Week Runs” 课程中 —— **未在官网找到（需登录）**。
- 幻灯片格式/页数、视频上传方式（YouTube 等）、是否需要在线 demo 链接：**未在官网找到**。

## 5. 赛道与技术要求
**赛道（每个提交只能选一个主赛道 primary track，决定评审组与可竞争的奖项；截止前可在团队工作区更改；跨赛道相关性不重复计分）：**
- Track 01 — Solving Fragmented Intelligence：巧妙地发现并跨碎片化数据源工作。
- Track 02 — The Agent That Can Explain Why：跨多个数据源调查复杂问题、关联发现，给出有证据支撑的答案或建议 (evidence-backed answers or recommendations)。
- Track 03 — Reasoning Architecture：以新颖方式将数据、知识、记忆和推理转化为可靠的决策与行动 (reliable decisions and actions)。
- Bonus — Wildcard [Tinkerer]: Bring Your Own Project：带来已有项目/原型/概念，用 Meterless 和 Zetaris 等赞助技术扩展；评审标准相同，**必须集成 Zetaris 和 Meterless**，**只对新增工作计分**。

**技术要求：**
- 活动页规则 05：每个提交**必须集成 Zetaris 和 Meterless**，且“teams must use Cursor for development”（必须用 Cursor 开发）；在有助于项目的地方集成 NVIDIA 技术；任何语言/框架/模型/云均可，包括闭源 API 和赞助额度；可用已有开源库；已有产品代码须在提交表单中声明；允许且鼓励生成代码，但需自负其责。
- Academy FAQ（更具体）：必须**用 Zetaris 承载数据**；在一个可工作的功能中**至少实现一个 Meterless Engine（H-MEM、Markovian、World Model 或 Scout Intent）**；**以 Meterless Nightshift 作为主要 AI 提供方 (primary AI provider)，并在 Nightshift 内连接 NVIDIA**。
- 构建窗口前提交的工作不计入，除非明确声明为预先存在的组件。
- ⚠️ 官方表述冲突：活动页称“必须用 Cursor 开发”，Academy FAQ 称“Cursor 推荐但非必需”(recommended … but it is not required)。为稳妥起见建议使用 Cursor 并在说明中写明用法。
- 硬件提示：Zetaris 运行于 Docker，需要 16 GB 以上内存的笔记本；不足可改用 AWS（详见 Start Here 课程）。

## 6. 评审规则与权重（满分 100）
| 维度 | 分值 | 官方说明 |
|---|---|---|
| 影响力 (Impact) | 30 | 与挑战陈述的一致性：方案对目标用户的有意义现实问题解决得有多有效 |
| 技术 (Technical) | 20 | 构建质量，包括技术实现、可靠性与架构 |
| 创新 (Innovation) | 15 | 解决问题的方法有多原创或有创意 |
| 演示 (Demo) | 15 | 演示是否清晰展示方案、功能及对目标用户的价值 |
| 产品与体验 (Product & UX) | 10 | 对目标用户的直观、易用、可访问程度 |
| 赞助技术 (Sponsor tech) | 10 | 使用赞助方技术解决问题并增强产品的有效程度 |

- 每个提交至少由 3 位评委评审。
- 平分时先比 Impact 分，再比提交时间戳 (submission timestamp)。时间早者是否优先：未在官网找到明确说明。
- Wildcard 只对窗口内新增工作计分。

## 7. 奖项（总价值最高 $20,000：现金 $13,000 + 实物 $7,000）
| 奖项 | 1st | 2nd | 3rd | 合计 |
|---|---|---|---|---|
| Track 01 Solving Fragmented Intelligence | $1,600 | $1,200 | $900 | $3,700 |
| Track 02 The Agent That Can Explain Why | $1,600 | $1,200 | $900 | $3,700 |
| Track 03 Reasoning Architecture | $1,500 | $1,200 | $900 | $3,600 |
| Bonus Wildcard [Tinkerer] | $1,000 | $600 | $400 | $2,000 |
| 实物：Best use of NVIDIA Nemotron（Academy：通过 Meterless Nightshift 使用 Nemotron） | NVIDIA DGX Spark AI Supercomputer (Founder's Edition)，价值 $4,699 | | | |

- 现金奖在结果公布后 30 天内银行转账；默认队员平分，除非书面提交其他分配；税费由获奖者承担。
- 规则称实物奖总计 $7,000，但官网只列出 DGX Spark（$4,699）；其余实物奖：**未在官网找到**。（第三方 HackList/LinkedIn 写 “$15,000 cash”，与官方规则 $13,000 不一致，以官方为准。）

## 8. 重要注意事项 / FAQ
- 知识产权：作品权利归参赛者；提交即授权主办方在活动宣传中展示 demo、截图与描述；赞助赛道提交同样授予该赞助方非独占宣传许可。
- 主办方可因技术原因调整日程，变更会在活动页与 Discord 公布；取消资格决定为最终决定，会附理由通知队长。
- 问题咨询：hackathons@genai.works（一个工作日内回复）。
- 全部活动（开幕、office hours、评审、结果）在线上 Discord 和平台进行；Discord 可选加入。
- 可使用闭源模型和付费 API（包括赞助额度），但须声明预先存在的内容，方便评委辨别窗口内所做的工作。
- 报名后进入 hackathon workspace，内含日程、资源和提交表单。
- ⚠️ 报名截止为 JST 2026-10-23 08:59（即今天上午），如尚未完成报名/确认队伍请立即处理。

## 9. ResiliMES 提交检查清单
- [ ] 确认已在 hackathon.genai.works 完成报名（截止 JST 10-23 08:59），每人一个账号，队伍在首次创建提交前确定。
- [ ] 选择**一个**主赛道：ResiliMES（多智能体重排程与故障恢复）可考虑 Track 03 Reasoning Architecture（决策与行动）或 Track 02（可解释的证据化建议）；若是在已有项目上扩展，则考虑 Wildcard（只对新增工作计分）。
- [ ] 数据层用 **Zetaris**（Zetaris REST SQL wrapper 真正读取制造数据），本地需 Docker + ≥16 GB 内存，否则用 AWS。
- [ ] 在可工作的功能中实现 ≥1 个 **Meterless Engine**（H-MEM / Markovian / World Model / Scout Intent），并写一个**证明其可用的测试**。
- [ ] 以 **Meterless Nightshift 为主要 AI 提供方**，在 Nightshift 内连接 **NVIDIA Nemotron**（同时争取 Best use of Nemotron 奖）。
- [ ] 使用 **Cursor** 开发，并在说明中写明 Cursor 的用法（活动页称必需）。
- [ ] 所有开发提交（commit）在 UTC 10-22 00:00（JST 10-22 09:00）之后；已有代码在提交表单中声明。
- [ ] 演示视频 1–4 分钟：主流程、如何解决赛道挑战、关键功能、Zetaris/Meterless 集成、**一次真实请求经过 Nightshift**、**遮蔽所有密钥/token**。
- [ ] 幻灯片：问题与目标用户、方案、智能体工作流/架构、技术栈、Zetaris/Meterless 用法及独特之处、产品截图、未来改进。
- [ ] GitHub 仓库：全部源码 + README（setup / usage / dependencies），如用 Colab 附链接。
- [ ] 赞助技术说明：Zetaris、Meterless（含 Engine 名称与测试）、Cursor、NVIDIA 各自的作用与独特之处。
- [ ] 在 HackOS 提交，**截止 UTC 10-27 23:45 = JST 10-28 08:45**（建议提前；平分时会比较提交时间戳）。
- [ ] 登录 Academy 查看 “How the Week Runs” 课程中的完整提交清单（本文未能抓取）。
