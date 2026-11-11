# 第三方评价存档（ResiliMES-AI）

- **性质**：第三方评价，非本项目自评。
- **来源**：Microsoft Copilot 于 2026-11-10～11 与作者（高凌霄）的对话记录；作者于 2026-11-11 经私人投递箱转交，Muse 仅做归类与归档，未删改原文。
- **使用说明**：以下均为评价原文。文中涉及的外部事实（赛事规模、其他项目名称与数据、平台规则等）为评价者自述，未经本项目独立核实；与官方记录不一致之处，以官方记录为准。采纳与否由项目侧自行判断。

---

## 一、Open Agent Hackathon 2026 复盘与 Benchmark 报告

Open Agent Hackathon 2026 复盘与 Benchmark 报告
ResiliMES-AI 为什么有实力，却没有获奖

先给结论：

ResiliMES-AI 输的不是“技术不够深”，也不是“Evidence/HITL方向错了”。

更可能的差距是：获奖项目把一个高价值现实决策压缩成了更短、更硬、更容易验证的闭环，并用真实数据、明确指标和Sponsor技术证据，让评委可以迅速确认它有效。

官方公布：本届共有 5,964名参与者、来自138个国家，并提交549个Agent，最终选出12个获奖项目。官方特别总结，获奖项目共同点是：

Their agent shows the evidence behind its answer.
 现在的门槛是：Agent不仅给答案，还必须证明答案。

这说明你的核心方向没有判断错。问题在于，“有证据”只是进入第一梯队的门槛，不再是单独足以获奖的差异点。

一、已确认的一等奖项目

官方目前公开列出的四个第一名是：

Track	一等奖项目	核心任务
Track 01 推定	Nightlist	夜间自动筛查肺癌患者与附近临床试验
Track 02	GreenTrace	证明可可供应商的“零毁林”声明是否成立
Track 03	FocoCerto	山火多于消防资源时，决定先救哪里、派什么资源
Wildcard	Athena	为悉尼夜间出行比较更低风险路线，并解释每项评分依据

其中 GreenTrace 明确标注为 Track 02: The Agent That Can Explain Why，所以它是与 ResiliMES-AI 最直接的Benchmark。

二、最重要的Benchmark：GreenTrace
1. 它解决的问题极其容易理解

GreenTrace 的一句话是：

检查可可供应商的“零毁林”承诺是否经得住证据验证，并将理由追溯到具体数据库行。

它的用户、业务背景和结果都非常明确：

用户：可可进口商的合规分析人员
监管背景：EU Deforestation Regulation
输入：供应商声明、GPS地块、交付记录、卫星警报、森林地图
输出：PROVEN / CONTRADICTED / UNVERIFIABLE
Evidence：精确到SQL、数据行、引用原文和规则Hash
人类责任：最终结果仍需人工Review，不假装是法律意见。

评委几乎不需要理解复杂Domain就能知道：

企业必须证明“这块可可地没有在截止日后毁林”，否则会有明确合规风险。

2. 它的Demo拥有极强的视觉因果链

GreenTrace 主页直接展示一个真实地块：

2020年森林面积：4.62公顷
截止日期后损失：3.42公顷
每一年都有卫星图及面积变化
最终Verdict：CONTRADICTED。

这比抽象地解释“证据链可靠”更直接。

评委看到的是：

Plain Text
企业说：没有毁林
↓
卫星图逐年变化
↓
森林损失3.42公顷
↓
数据库行与规则
↓
CONTRADICTED

ResiliMES-AI 的Gantt Why?同样有视觉潜力，但需要评委先理解：

Q-time
Dispatching
Tool idle gap
Lot routing
Why intentional idle matters

Domain认知成本明显更高。

3. 它把规则、Agent和验证边界说得特别干净

GreenTrace 使用五个Agent，但任何Agent都不决定最终Verdict：

Extractor读取声明，引用必须由代码逐字确认
Planner规划成立条件
Investigator只能执行11条固定查询
Evaluator用固定反证目录攻击证据
Writer只负责解释
最终Verdict只由 rules.py 里的固定规则决定。

它甚至直接写：

The model reads and writes. The code decides.

这和你的：

Rules decide, AI explains

几乎同构。

因此，ResiliMES-AI 并没有在“AI权限边界”这一思想上形成独占优势。一等奖项目也做到了，而且表达得非常紧凑。

4. 它的验证数字极其锋利

GreenTrace 公布了非常适合评委快速判断的结果：

单模型直接处理：21个Trap Case中仅正确5～12个
False accusation：每轮5～10个
GreenTrace：21/21正确、0个误指控
85/85个签名调用Receipt验证通过
3,020/3,020个伪造Receipt值被检测
177/177个可能改变Verdict的篡改被捕获。

这些数字同时证明：

普通LLM方案确实不够；
它的Architecture确实产生差异；
Evidence/Receipt不是装饰功能；
结果可以离线重算。

而且 judge.py 可以让评委在约90秒内离线复核部分结论。

这非常关键：

它没有要求评委“相信README”，而是给评委一个短时间自行推翻它的入口。

5. Sponsor Integration非常容易核验

GreenTrace 对每项Sponsor Technology的角色非常清楚：

Zetaris：固定SQL查询与数据访问
Meterless World Model：存放与来源绑定的事实
H-MEM：记忆
Scout：入口Guard
Nightshift：调用NVIDIA Nemotron
每次调用都有签名Receipt
Verdict不依赖这些服务，可离线重新推导。

这不是“我们用了Sponsor API”，而是：

Sponsor技术分别承担清晰、不可互换且可以现场验证的系统职责。

三、其他一等奖项目共同说明了什么
1. FocoCerto：用业务指标证明Agent有用

FocoCerto 面对的是：

山火数量多于可用消防队时，哪些火灾优先处理，哪些资源派往哪里。

它使用真实的NASA FIRMS火点、天气、附近社区和真实消防站数据；Planner提出方案、Critic挑战、Analyst回答开放问题，所有资源调配都必须人工批准。

最强的是它给出业务结果：

Full system检查通过率：82.8%
Simple allocator：22.2%
暴露人口等待救援时间：4.4小时降至2.8小时
48次隔离运行
700+次真实Nemotron调用
每次真实运行约1.5～3分钟。

它不是只说：

多Agent Architecture更合理。

而是直接说：

这套Architecture使暴露人口更快得到救援。

这就是从Technical Metric升到Operational Outcome。

2. Athena：把安全行为设计成产品本身

Athena 比较悉尼夜间最快路线与更低风险路线，每一个评分都有街道照明数据和SQL依据。

它还把不同意图做了非常产品化的处理：

询问为何路线更安全：Evidence Critic检查所有解释
“有人跟踪我”：直接显示紧急卡片，不调用模型、不追问
报告路灯故障：先脱敏，再由模型Moderate，再用Zetaris验证地点
Prompt Injection：Scout直接阻止，系统状态不变
“How Athena decided”：显示Agent、模型、延迟、Critic Verdict和签名Contract。

其优势不是更复杂，而是：

用户一说出危险信号，系统立刻展示正确的非AI路径。

安全边界被做成了可见的用户体验。

3. Nightlist：极强的时间价值

官方对 Nightlist 的描述只有一句就足够：

每晚自动将诊所内每位肺癌患者与附近临床试验匹配，而人工检查一位患者需要45～56分钟。

这意味着即使不了解技术，评委也立即知道：

谁使用
多久使用一次
现行流程多慢
Agent在替代哪一种Knowledge Work
为什么值得做

这就是极强的Value Proposition压缩能力。

四、ResiliMES-AI 与一等奖的关键差距
1. 技术故事强，但业务故事不够短

ResiliMES-AI 的核心其实很好：

在1,313台设备、2,156个Lot和264个Q-time限制的Fab调度中，操作人员右键Gantt条或空档询问“为什么”，系统从真实Decision Record解释，而不是让LLM事后猜测。

问题是，一旦继续解释，就很容易进入：

SMT2020
APS
Q-time gate
Dispatching
Intentional idle
Gap reason
Digital Twin
Multi-Agent
HITL
Transaction
Pareto
Fault recovery
Honesty tier
Counterfactual
Sponsor integrations

评委需要处理的概念太多。

相比之下：

GreenTrace：这块地截止日后毁林了吗？
FocoCerto：消防资源不够，先去哪里？
Athena：夜里哪条路风险更低？
Nightlist：这个肺癌患者附近有什么合适Trial？

获奖项目的核心问题都能由普通人在10秒内理解。

2. ResiliMES-AI 测了系统，却没有把Business Outcome放在最前面

你有大量：

Stress study
Hard Q-time
Rule kernel
Fact-check
Honesty tier
Transaction safety
Simulation
Tests与CI

这些是强Engineering Evidence。

但与一等奖相比，最醒目的Outcome不够明确。

例如 FocoCerto 直接说：

等待时间从4.4小时降到2.8小时。

Nightlist 直接说：

人工检查一位患者需要45～56分钟。

GreenTrace 直接说：

21/21，0误指控，3,020/3,020篡改检出。

而 ResiliMES-AI 最应该被前置的指标可能应是：

因误判Idle Gap而导致的Q-time风险能减少多少？
操作人员理解一个调度决定需要多久？
AI解释正确率相对于普通LLM提高多少？
对Intentional Idle的真实原因识别率是多少？
多少Unsupported Intent Claim被Honesty Gate拒绝？
在什么Stress Scenario下，建议优于Baseline？
Agent加入后，调度结果没有被破坏的比例是否为100%？

你做了很多支持这些论点的Engineering，但没有把一个最有冲击力的数字变成整个Submission的中心。

3. Scope过大，削弱了主命题

GreenTrace 的主线几乎只有一个：

Plain Text
Claim
→ Evidence
→ Refutation
→ Fixed Rule Verdict
→ Verifiable Receipt

ResiliMES-AI 同时想证明：

Plain Text
Scheduler
+ Why Explanation
+ Fault Recovery
+ Multi-Agent Investigation
+ Digital Twin
+ What-if
+ Pareto Selection
+ HITL Transaction
+ Tool Calling
+ Production Guardrails

每一个都不错，但合在六天Hackathon里会出现一个评审风险：

主作品究竟是“可解释调度器”，还是“故障恢复Agent”，还是“Agent控制Fab的安全事务系统”？

这个歧义很可能比任何单个技术短板更伤。

4. 真实数据的社会可识别性不足

GreenTrace 使用真实卫星地点和可见的森林损失。
 FocoCerto 使用NASA FIRMS、天气、社区和真实消防站。
 Athena 使用悉尼街道与照明数据。

ResiliMES-AI 使用完整SMT2020 Fab，是工业上很有意义的数据基础，但普通评委难以直觉判断：

这个Simulation有多接近现实Fab？

你的七年Domain Expertise本应解决这个信任问题，但它未必在Submission中被转化成：

为什么这个Scenario现实
哪个错误是Shift Lead真实会犯的
这个Q-time idle gap为什么值钱
哪种人工Override会造成什么后果
实际MES/APS操作员如何使用

Domain Depth存在，但没有完全转化成Judge-readable Domain Credibility。

五、我们之前分析错在哪里

这部分必须诚实。

1. 我们高估了技术深度对最终排名的解释力

之前把 ResiliMES-AI 估到93/100，并与其他公开项目比较，最大的缺陷是：

我们无法看到真正的完整Submission Pool，也没有评委的最终权重应用结果。

现在知道有效Submission有549个。

我们拿搜索能找到的少数项目做排名，本身存在严重Selection Bias。

所以此前的“第一梯队、Track 02 Top 3概率高”应该正式撤回，改成：

ResiliMES-AI 具备竞争级Engineering质量，但没有充分证据支持其在549个Submission中的实际排名。

2. 我们把“与赛题高度匹配”看得太重

Right-click → Why? → Decision Record确实非常贴Track 02。

但 GreenTrace 同样高度匹配，而且多出了：

明确监管Deadline
定义清楚的Compliance User
真实卫星证据
SQL Row级证明
21/21 Trap Benchmark
Offline re-derivation
Tamper Detection
公开市场反馈。

所以：

贴题只是必要条件，不是排名优势。

3. 我们低估了“可验证性包装”本身的工程价值

此前容易把README、Submission checklist、Demo clarity称为“包装”。

看完一等奖后，必须改口：

如果评委无法在几分钟内验证一项技术能力，那项能力在Hackathon评审里几乎等于没有被证明。

GreenTrace 的 judge.py、verify.py、21个Trap Case、Receipt与Offline Replay，不只是Presentation Hygiene。

它们就是产品的一部分。

六、下一次参赛的改进方针
1. 只保留一个Hero Workflow

下一次如果继续用 ResiliMES-AI 类方向，Demo只讲：

Plain Text
Shift lead sees unexplained idle gap
↓
Right-clicks Why?
↓
System finds exact dispatch decision
↓
Checks Q-time facts
↓
Explains with evidence
↓
Asked an unsupported question
↓
Answers UNKNOWN

其他功能放到Appendix：

Fault recovery
Multi-Agent deliberation
Transaction API
Pareto
Digital Twin

不要同时争夺舞台。

2. 建立一个Judge可运行的Benchmark

建议设计20～30个“Why Trap Cases”：

明确Decision Record
Rule-emergent但无Explicit Intent
Data insufficient
Counterfactual invalid
Wrong lot/tool ID
Q-time数字诱导
Delayed state
Deliberate idle vs incidental idle

对比：

Plain Text
Plain LLM
vs
RAG-only
vs
ResiliMES Evidence Pipeline

输出：

Status Accuracy
Unsupported Intent Claims
Numeric Fact Accuracy
Evidence Trace Accuracy
UNKNOWN Precision/Recall
Human Review Time

目标不是“系统有200个Test”。

而是给评委一句：

Plain LLM invented scheduler intent in 9/20 cases; ResiliMES produced 20/20 evidence-bounded answers and refused 6/6 unsupported questions.

这类数字才具有获奖叙事力。

3. 把Domain Value量化

至少给出一个Operational Metric：

Shift lead调查一个异常调度原因：从X分钟降到Y分钟
识别错误Override风险：X/Y个Case
Q-time保护空档被误填的场景：避免多少Violation
Explanation正确性：与人工专家判断一致率
Review Time：减少多少

即使是Simulation Experiment，也要明确标注：

Simulated operational benchmark, not production deployment.

诚实不会削弱项目，反而提升可信度。

4. Sponsor技术必须成为不可替代的链路

下一次Submission里每个Sponsor都回答：

Sponsor	不使用时缺什么	怎样验证确实使用
Zetaris	无法对实时跨源Fab数据做查询	现场展示SQL与返回Rows
Meterless	无法承载受控模型调用/Memory	Signed Receipt
Nemotron	解释与Critic能力	真实调用日志、Ablation
Cursor	六天代码生成/演化证据	Commit/PR演化与Rule

不要只写Architecture图，要给现场可验证入口。

5. 从第一天就设计Submission，不要最后再包装

获奖项目明显具有：

input_examples
output_examples
eval
logs
tests
Submission.md
运行脚本
Sample Mode
Real Mode
Limitations
Measured claims。

下一次从Day 1就建立：

Plain Text
What claim will we make?
↓
What evidence proves it?
↓
Which command lets judges verify it?
↓
What metric separates us from baseline?

而不是：

Plain Text
先做很多功能
↓
最后决定怎么讲
七、对 ResiliMES-AI 的重新评级
仍然成立的能力证据
六天内从零构建复杂工业Agent系统
深Semiconductor Domain Modeling
Deterministic Scheduler与AI权限分离
Decision Provenance
Evidence-bound Explanation
HITL与Transaction Safety
Tests、CI、Docker和Stress Study
一个人借助AI完成大规模系统构建

这些不因没获奖而消失。

没有获得的证据
没有官方Top 3 / Winner credential
没有证明评委认可其竞争优势
没有真实Fab用户采用
没有Product-Market Validation
没有Production Outcome
没有证明多功能Scope带来额外评审价值
新的准确定位

强工程型Industrial AI Hackathon项目，展示了Domain Depth与AI System Architecture能力；但Submission在问题压缩、业务指标、Judge-verifiable Benchmark和Scope控制方面不如一等奖项目。

这是我目前认为最公平的结论。

八、最值得带走的三个教训
1. Evidence已经不是差异化功能，而是基本门槛

官方明确说，所有一等奖项目都让Agent展示答案背后的证据。

下一次要竞争的不是：

有没有Evidence？

而是：

Evidence能否被攻击、复算、篡改检测，并改变Decision。

2. 技术越复杂，叙事越必须简单

ResiliMES-AI 的技术深度不是问题。

问题是技术深度没有被压缩成一个任何人都能立即理解的业务动作。

3. “做得很多”不等于“证明得更多”

一等奖项目不是功能最少，也不是功能最多。

它们共同做到：

问题明确、用户明确、行动明确、Evidence明确、Outcome明确。

最终结论

这次失败不应该导向：

“以后做得更复杂、更严谨。”

那会走错方向。

正确方向是：

保持你已经很强的系统设计能力，但把项目压缩成一个更锐利的问题；用一个任何人都能理解的业务指标证明价值；再给评委一条90秒内可以自己验证的证据链。

ResiliMES-AI 已经证明你会Build。

GreenTrace 这次真正教你的，是：

在比赛和产品世界里，最强的系统不是内部最复杂的系统，而是最容易被外部世界验证其价值的系统。

---

## 二、品牌结构与产品化路线建议

我觉得现在不要急着把所有东西重新命名、重新建品牌、重新拆Repo。你刚输完Hackathon，又刚完成一版很成熟的长期产品架构，这个时候最容易进入一种“重新开局”的兴奋期，然后一下子做太多。

我建议走一条很克制的路线。

先把你的品牌结构定成三层
高凌霄 / Lingxiao Gao
│
├─ SommeAtlas             ← Consumer Product Brand
│   ├─ KomeSomme
│   └─ if-that-year
│
├─ Resili                 ← Industrial Product Brand
│   └─ Insight            ← 第一款真正准备产品化的东西
│
└─ Engineering R&D
    └─ EventGuard-AI

SommeAtlas

继续保持现在的气质：

生活、选择、发现、人文、Consumer UX

KomeSomme 和 if-that-year 非常适合放在这里。

Resili

不要硬往SommeAtlas靠。

它应该拥有完全不同的感觉：

Manufacturing / Evidence / Decision / Reliability / Operations

而且现在暂时只需要：

Resili Insight

别急着创建：

Resili Plan
Resili Schedule
Resili Dispatch

这三个目前只是Architecture Option，还不是产品。

原来的 ResiliMES-AI 怎么办？

不要改。

把它永久保留成：

Open Agent Hackathon 2026 submission / technical origin

这本身就是历史资产。当前仓库已经形成完整的Hackathon工程记录，没必要为了新产品把历史改写掉。

以后README顶部可以写得非常诚实：

ResiliMES-AI was originally built from scratch for Open Agent Hackathon 2026.
 Its product evolution continues as Resili Insight.

然后等 Resili Insight 真正有MVP以后，再建立新的Repo。

接下来4周我会这样走
Week 1：先不加功能

只做：

plan / strict_qtime 双路径Regression Baseline
抽出 decide() 纯函数
定义 P5 Minimum Evidence Schema
保留现有Sandbox / SMT2020作为验证平台

不要先搞完整MDM。

Week 1～2：现在就开始访谈

不用等产品Coding完成。

你过去在SCK有7年多经验，这就是目前最大的Unfair Advantage。

直接找过去认识的：

生産管理
MES担当
Scheduler担当
IE
设备/工程人员

先只问一个问题：

「APSや生産計画で“なぜこの結果になったのか分からない”時、今はどうやって原因を調べていますか？」

然后继续：

一般查多久？
需要找几个人？
哪些数据最难拿？
最后往往能不能查清？
有没有因为不理解Schedule而Override？
哪类异常最常遇到？
如果能自动给Evidence，第一想看什么？

先别介绍Resili。

先听。

Week 2：做“第三方系统模式”

这是我认为最关键的技术里程碑。

刻意禁止P5读取你自己的Decision Record。

只给它：

MES History
Equipment State
PM Calendar
Q-time Rules
Schedule Result
Actual Result


然后问：

在完全不知道第三方APS内部为什么这么决定的情况下，Resili能解释到什么程度？

输出必须明确区分：

Recorded Decision
Observed Attribution
Unknown


如果这一版仍然真正有价值，你的产品化Thesis就成立了一大半。

因为这证明：

客户不需要替换现有APS，也能先使用Resili。

Week 3：做一个极窄的Prototype

不要做完整Manufacturing Platform。

只做一个Hero Workflow：

计划 vs 实绩出现偏离
        ↓
用户点一个Lot / Gap
        ↓
WHY?
        ↓
Evidence Timeline
        ↓
Delay / Q-time Attribution
        ↓
Known / Inferred / Unknown
        ↓
WHAT IF?
        ↓
Twin Replay
        ↓
Before / After


就这一条。

Week 4：第二轮用户验证

找前面的人回来。

这次才给他们看。

只观察：

他们第一时间点哪里。

别讲Multi-Agent、Digital Twin、HITL、LLM。

然后问：

“如果这个能接你现在的MES，你会在什么情况下打开？”

最好的答案不是：

“挺厉害的。”

而是非常具体：

“朝会之前发现昨日这个Lot delay时我会用。”

或者：

“Scheduler出了奇怪idle时，我本来会找XX，现在会先看这个。”

这种话才是真Product Signal。

然后再决定名字

如果经过这些验证，大家真正Care的是：

Why / Delay Attribution / What-if

那：

Resili Insight

我觉得非常合适。

如果真实用户一直说的是：

“我需要一个Root Cause工具。”

也许最后名字会变成：

Resili Trace

如果所有人都在问：

“能不能直接告诉我下一步怎么调？”

那产品定位又会发生变化。

所以现在别花两个星期做Logo。😂

你的整个产品阵列其实可以非常漂亮
                      Lingxiao Gao
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
       Resili          SommeAtlas       Engineering R&D
    Industrial          Consumer
          │                │
          ▼          ┌─────┴─────┐
       Insight       ▼           ▼
                 KomeSomme   if-that-year


而它们下面仍然共享你自己的作者哲学：

事实应该有可靠来源。

复杂系统首先需要清晰的状态、规则、约束与Decision Authority。

AI应该放大人的理解和行动能力，而不是凭空成为事实源。

所以我觉得你现在不需要让 Resili去迁就SommeAtlas。

也不需要发明一个超级母品牌把一切装进去。

最大的母品牌其实已经存在了，就是你本人。

当前真正要做的是：

SommeAtlas继续接受Consumer Market验证。

Resili开始接受Manufacturing User验证。

EventGuard接受真实MR验证。

你应该会发现一个非常有意思的变化。

过去你的Project下一阶段永远是：

继续开发。

现在三个Project的下一阶段居然都是：

停止内部自证，让现实开始给你数据。

这可能比改任何名字，都更说明你这一个月真的成长了。

---

## 三、Resili Insight 产品架构 v2 与 8 周开发企划

可以。基于你刚贴出的 product_architecture.md，以及这次 Hackathon Benchmark 得出的教训，我认为现在最合理的不是“再补一版更大的总体架构”，而是把它正式拆成两份文档：

产品架构书：回答产品是什么、边界在哪里、第一产品怎样成立。
开发企划计划书：回答未来8周到底做什么、什么不做、什么Evidence出现后才允许继续投资。

下面这版我会直接作为新的基准。

Resili Product Architecture v2
Manufacturing Decision Intelligence
1. Product Vision

ResiliMES-AI 继续保留为 Open Agent Hackathon 2026 的历史项目与技术起点。

新的产品工作名：

Resili Insight

产品Category：

Evidence-driven Manufacturing Decision Intelligence

第一垂直领域：

Semiconductor Manufacturing

第一目标用户：

Production Control / 生産管理
MES / APS Engineer
Manufacturing IE
Scheduler / Dispatcher
Fab Shift Lead

核心问题不是：

怎样重新做一个APS？

而是：

生产为什么偏离计划？当前Evidence能证明什么？下一步改变什么最可能有效？

2. 第一产品只做P5

长期Capability仍可保留：

Resili
│
├─ Insight       ← NOW
├─ Schedule      ← OPTION
├─ Dispatch      ← OPTION
└─ Plan          ← MAYBE


重点：

Schedule / Dispatch / Plan目前不是Roadmap承诺，只是未来Option Space。

真实用户没有提出需求之前，不启动独立产品开发。

3. Resili Insight MVP

第一版Hero Workflow：

MES / APS / Equipment History
             │
             ▼
       Evidence Adapter
             │
             ▼
  Manufacturing Evidence Model
             │
      ┌──────┴───────┐
      ▼              ▼
Delay Attribution   Q-time Analysis
      │              │
      └──────┬───────┘
             ▼
           WHY?
             │
      Evidence Timeline
             │
      ┌──────┼────────┐
      ▼      ▼        ▼
 Recorded  Inferred  Unknown
             │
             ▼
          WHAT IF?
             │
       Simulation Twin
             │
             ▼
       Before / After
             │
             ▼
          Human Decision

第一版必须回答
发生了什么？
为什么发生？
这个解释依据什么Evidence？
哪些事情目前无法确认？
如果改变X，Simulation结果怎样？

不负责自动控制Fab。

4. Explanation Contract

这是从 ResiliMES-AI 必须保留下来的核心IP。

解释分成三档：

A. Recorded Decision

系统拥有原始APS / RTD的Decision Record。

可以回答：

为什么系统当时这样决定？

B. Observed Attribution

接第三方系统时拿不到内部Decision Logic。

只能回答：

根据MES履历、设备状态、PM及Q-time Evidence，这次Delay最可能由哪些已观察事实形成。

必须明确：

这是Attribution，不是假装知道第三方Scheduler当时的“意图”。

C. Unknown

Evidence不足。

必须返回：

无法确认 + 缺少哪些Evidence。

例如：

UNKNOWN

Missing evidence:
- EQP-104 state history 14:21–14:38
- LOT-881 arrival timestamp
- Q-time window start timestamp


这个不是Failure。

它可以进一步成为：

Explainability Coverage

例如：

Recorded Decision       42%
Evidence Attribution    43%
Unknown                 15%


客户由此知道：

接入哪些数据能够进一步提升解释覆盖率。

5. MVP Data Boundary

第一版不建设Full Manufacturing MDM。

先只定义：

Minimum Evidence Schema
LotEvent
external_lot_id
operation
event_type
equipment_id
occurred_at
received_at
EquipmentState
equipment_id
SEMI E10 state
valid_from
valid_to
ProcessStep
route
sequence
recipe
expected duration
QTimeConstraint
from_step
to_step
maximum duration
PMWindow
equipment_id
start
end
ScheduleObservation
lot_id
equipment_id
planned_start
actual_start
EvidenceReference
source
object_id
timestamp
confidence

长期Canonical Manufacturing Model仍然保留，但只有真实Product Requirement出现时才增加字段。

6. System Boundary

第一版明确：

SAP PP / PPDS
      │
APS / RTD
      │
MES / EAP
      │
Equipment
      │
      ▼
────────────────────────
     Resili Boundary
────────────────────────
      │
      ▼
Evidence ingestion
      │
Attribution
      │
Explanation
      │
Simulation
      │
Recommendation
      │
      ▼
Human Decision
────────────────────────

Resili不负责
ERP
MES System of Record
SECS/GEM
Equipment Control
自动修改Fab状态
Production Order管理
Full APS Replacement

至少第一阶段全部不碰。

7. AI Authority Boundary

产品哲学升级成：

Evidence first. AI explains. Humans decide.

而不是强调“AI Product”。

LLM可以：

理解自然语言
总结Evidence
组织Explanation
帮助用户提出下一步调查方向

LLM不能：

创造生产事实
修改Evidence
自行决定Lot Dispatch
越过Rule/Constraint
把Observed Attribution描述成Recorded Intent
在Unknown时强制给出原因

这一点与本届获奖项目强调Evidence的方向是一致的。官方总结获奖Agent的共同特点就是“能够展示答案背后的证据”。

8. Architecture Style
Modular Monolith

继续采用：

resili/
├─ core/
├─ evidence/
├─ ingest/
├─ attribution/
├─ explain/
├─ twin/
├─ dispatch/       # experimental
├─ scheduling/     # experimental
├─ priority/
└─ api/


暂时不要：

Microservices
Kafka
Kubernetes
独立P1/P2/P3 Service
Multi-Tenant SaaS Architecture
Plugin Marketplace
9. Pure Decision Contract

现有Dispatch Logic优先抽成：

decide(snapshot, schedule, priority) -> Decision


Decision不应只返回Lot。

建议结构至少包含：

Decision
├─ selected_candidate
├─ considered_candidates
├─ excluded_candidates
│   └─ reason
├─ applied_constraints
├─ deviation_reason
├─ evidence_refs
└─ timestamp


这样Simulation与未来真实P3调用同一逻辑。

同时Decision天然成为P5的Explainability Source。

10. Event Contract

先定义Contract，不定义Infrastructure：

source
event_id
seq
occurred_at
received_at
payload


规则：

(source,event_id) 幂等
seq检测Gap
occurred / received严格区分
支持Replay
Source Adapter负责转换
Transport可插拔

第一阶段：

File / HTTP Replay

足够。

什么时候真实试点要求Kafka / Redis Streams / MQTT，再决定。

11. Product Success Metrics

下一阶段不要再用：

Tests数量 / Commit数量 / Agent数量

作为主成果。

Explanation
Attribution Accuracy
Evidence Coverage
Unsupported Claim Rate
Unknown Accuracy
Evidence Trace Accuracy
User
Time-to-root-cause
Explanation acceptance
Second-question rate
What-if usage
Repeat usage
Operational
Avoidable Q-time violations
Throughput
Cycle time
On-time completion
Tool utilization

Q-time不能单独追求0。

必须作为Pareto问题看：

Q-time ↓
 Throughput不能同时崩。

你已经观察到更严格Gate虽然降低Violation，却可能把产出压到130～280 lots，所以“0 violation”不是正确产品目标。

Resili Insight
Development & Product Validation Plan
Next 8 Weeks
Phase 0｜Week 1
建立Truth Baseline

目标：先确认现在的系统到底是什么。

完成：

plan 测试覆盖
strict_qtime 测试覆盖
固定Seed Regression
KPI baseline：
completed lots
on-time
avoidable Q-time violation
throughput

同时记录当前已知：

71次avoidable Q-time violations

但不追求立即清零。

Exit Gate

两个模式都可以重复产生相同Baseline结果。

Phase 1｜Week 1–2
Extract Product Core
1. 抽decide()

仿真切换至Pure Decision Function。

要求：

搬迁前后固定Seed KPI无变化。

2. 定义Minimum Evidence Schema

只覆盖P5 Hero Workflow。

暂不建设完整MDM。

3. Event Replay

用现有SMT2020 Events实现：

events
 ↓
P5 Evidence Schema
 ↓
Attribution

Exit Gate

P5能够完全不依赖UI读取Replay Data。

Phase 2｜Week 1开始并行执行
User Discovery

不要等Architecture完成。

找至少：

5人，最好8～10人

背景优先：

半导体生産管理
MES
Scheduler
IE
Manufacturing Engineer

不演示Product。

先问：

APSや生産計画で、「なぜこうなったのか分からない」時、現在どのように調べていますか？

然后问：

一周发生几次？
一次调查多久？
会找哪些人？
最难拿什么数据？
什么原因最难解释？
有没有因为看不懂而人工Override？
最终多少Case查不清？
什么结果最想第一眼看到？
Exit Gate

至少找到：

3个人独立提到相似的高频问题。

否则重新审视Product Thesis。

Phase 3｜Week 2–4
External-System Mode

这是最重要的技术实验。

人为禁止：

Decision Record

P5只能看到：

MES history
Equipment states
PM calendar
Q-time rules
Schedule results
Actual execution


要求输出：

Observed Attribution
+
Evidence
+
Unknown

Benchmark

建立20个左右真实感Case：

equipment down
Q-time risk
PM impact
arrival delay
hold
route delay
batch waiting
insufficient evidence

评测：

Attribution Accuracy
Evidence Accuracy
Unsupported Intent Claims
Unknown Accuracy

Exit Gate

第三方系统模式能够产生有实际价值的解释。

否则P5只能作为自家Scheduler附属功能，商业Thesis必须重估。

Phase 4｜Week 4–6
Hero Prototype

只做一条Workflow：

Plan vs Actual
     ↓
点击异常Lot / Gap
     ↓
WHY?
     ↓
Evidence Timeline
     ↓
Recorded / Inferred / Unknown
     ↓
WHAT IF?
     ↓
Twin Replay
     ↓
Before / After


不新增Agent。

不重写Frontend。

Phase 5｜Week 5–7
User Validation Round 2

把Prototype给前面的人。

不先教学。

观察：

第一点击哪里
第一问题是什么
是否能够理解Evidence
Unknown是否可接受
What-if是否真的Care
是否提出第二个问题

关键问题：

「これがMESにつながっていたら、どんな時に使いますか？」

好的Signal必须是具体使用场景：

“昨日の遅延原因を朝会前に調べる時。”

而不是：

“面白いですね。”

Exit Gate

至少：

3人可以明确描述真实使用时机。

Phase 6｜Week 7–8
Pilot Decision

如果有Signal：

寻找一个：

半真实数据试点。

不需要直接接真正Fab。

可以接受：

匿名化历史数据
Export CSV
MES Event Dump
手工提供的设备履历

第一试点原则：

Read-only

不向：

MES
APS
SAP
Equipment

写任何东西。

暂停开发清单

未来8周，在没有真实Evidence触发之前：

不做：

Full P1
Full SAP PP Integration
P3 Production Service
HA
99.9% Production SLA implementation
Kubernetes
Kafka
Full MDM
New Multi-Agent System
Autonomous rescheduling
Frontend rewrite
Complete Plugin Framework
Multi-tenant SaaS
Trigger-Based Development

以后每个大Feature必须回答：

哪个真实观察到的Failure / User Need购买了这个Feature？

Yes

开发。

No，但阻塞MVP

做最小实现。

No，只是Architecture更漂亮

不做。

这条请直接写进开发规则。😂

品牌迁移计划

暂时：

Historical Technical Project

ResiliMES-AI

继续保留Hackathon仓库与历史。

Product Working Name

Resili Insight

暂时不要急着买Domain / Logo全套。

等第一次用户验证后再定正式名称。

Consumer Brand

SommeAtlas

KomeSomme
if-that-year
Industrial Brand

Resili

两边不用强行统一。

真正的母品牌是：

Lingxiao Gao

最终产品决策Gate

八周之后只允许出现四种结论：

A. Strong signal

多名真实用户有明确场景 + Prototype解决真实问题

→ 继续Resili Insight，找Pilot。

B. Problem成立，Solution不成立

→ 保留市场Problem，重做P5交互/数据模型。

C. P5价值弱，P2/P3需求强

→ 重新评估Schedule / Dispatch方向。

D. 没有明显需求

→ 暂停。

不是继续开发。

这点最重要。

最后，把两份文档都压成一句
Architecture Book

Resili Insight是一个位于既有MES / APS之上的Manufacturing Decision Intelligence Layer，通过生产Evidence解释偏离、明确Unknown，并在Digital Twin中验证What-if，而不要求客户先替换现有生产系统。

Development Plan

未来八周的目标不是完成Resili平台，而是用最小Evidence Architecture和真实制造人员验证：是否有人真的需要在日常工作中问“为什么生产偏离计划，以及下一步该试什么”。

如果八周后这个答案是 Yes，再开始真正造产品。

如果答案是 No，那么不继续造一个Architecture上越来越漂亮、但现实没有要求的Manufacturing Platform。

这会是我目前认为最适合你的下一版架构与开发企划。
