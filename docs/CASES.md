# ResiliTrace 案件体系（cases/v1，v0 仍可加载）

案件是「一 lot 迟到之后怎么办」的跟进记录。解释层回答一 lot 为什么迟到；
案件回答：哪些 lot 还在等人工处理、按什么顺序处理、每 lot 决定了什么。

新案件是 `cases/v1`。`cases/v0` 台账仍可加载，其封印不覆盖 `owner`。
`explain()` 不自动建案件。Cases 页面读 v0 和 v1，不改状态、不落盘。

## 模型

`resilimes/explain/cases.py`。代码里新建的台账是 `cases/v1`；文件省略
`book_version` 时按 `cases/v0` 读（与页面 `normalizeCaseBook` 一致），
案件省略 `cases_version` 时跟台账版本走。与 `insight/notes_cases.py`
的 `NotesCase` 无关——那是 investigator 评测用的注记难例，本模块是
ResiliTrace 的跟进案件。

| 字段 | 含义 |
| --- | --- |
| `case_id` | 台账内顺序号（`case-0001`…）。只在同一 `CaseBook` 内稳定，不作跨台账键 |
| `lot` | 涉事 lot id（建案时去首尾空白后存储） |
| `run` | `RunRef`（seed / horizon / policy / label），案件可复演 |
| `title` | 一句话标题（非空、单行） |
| `severity` | 严重度（下表），人工指定，须附 `severity_reason` |
| `severity_reason` | 为什么是这个严重度（非空）。省略时仅当指定值与建议值一致才自动记为建议来源；不一致须显式写理由 |
| `owner` | 负责人。仅 `cases/v1`。空（`None`）表示未指定；v0 案件带了名字会被拒绝 |
| `status` | 状态（下表），初始 `open` |
| `lateness_min` | 迟到分钟数（≥ 0 且有限，未知为 `None`） |
| `evidence_hash` | 所据证据包的 `content_hash`（`sha256:<64 小写 hex>` 格式，未知为 `None`） |
| `notes` | 跟进备注行（建案时或 `add_note` 追加） |
| `history` | 每次状态变迁（旧状态 → 新状态、时间、备注），只增不改；首条为创建事件 |
| `content_hash` | SHA-256 封存，与证据包、声明台账同款模式；覆盖内容不覆盖时间戳 |

## 严重度

| 等级 | 定义 | 迟到建议阈值（仅建议，不自动指定） |
| --- | --- | --- |
| `critical`（緊急） | 迟到量级达到需要立即升级处理的程度 | ≥ 120 分钟 |
| `major`（重大） | 明显迟到，本班次内需要决定 | ≥ 30 分钟 |
| `minor`（軽微） | 迟到，但班次可吸收 | > 0 分钟 |
| `info`（情報） | 未迟到，作为观察项跟踪（如 near-miss） | 0 分钟 |

`suggest_severity(lateness_min)` 只给建议：返回 `None` 表示迟到未知；
负数、NaN、无穷大、布尔值抛错。严重度本身永远由人指定并写理由；
自动理由只在指定值与建议值一致时生成，否则建案拒绝并要求显式理由。

## 状态机

```
open ──► investigating ──► resolved ──► open（重开）
 │           │  ▲              │
 │           └──┤              └──► dismissed ──► open / investigating
 └────► resolved / dismissed ──┘
```

上图是主干。`waiting` 与 `open` / `investigating` 互通，也可以直接到
`resolved` / `dismissed`。完整边见下列。

- `open` → `investigating`、`waiting`、`resolved`、`dismissed`
- `investigating` → `open`、`waiting`、`resolved`、`dismissed`
- `waiting` → `open`、`investigating`、`resolved`、`dismissed`
- `resolved` → `open`、`dismissed`
- `dismissed` → `open`、`investigating`、`waiting`

`waiting` 是阻塞态：等维修、等 PM 窗口、等别人决定。仍算未关闭。
`investigating` 是有人在查，`waiting` 是下一步不在本案里。

`open → resolved` 是有意放开的：分诊时直接解决（重复、lot 已恢复、
无需处理）是真实路径，逼着先走一次假 `investigating` 会让 history
说谎。同理 `resolved → dismissed`（解决后发现是重复案）与
`dismissed → investigating`（驳回后出现新证据）也是直接变迁。
非法变迁抛 `ValueError` 并列出允许的去向。`resolved` / `dismissed`
不是终态：任何案件都可重开，重开同样记入 `history`。

`history` 自创建事件起是一条链：首条 `previous` 为 `None`、状态为
`open`，后续每条的 `previous` 等于上一条的状态，且该步必须是上表允许的
变迁，末条状态等于案件当前状态。链是连续的但走了非法边（例如
`resolved → investigating`）同样拒绝。直接构造或 `from_json` 导入
不满足该链的数据会被拒绝。尚无 history 的 `open` 案件在第一次
`transition` 时补上创建事件，补完后的记录同样通过这条校验。

## lot-first 列表接口（`CaseBook`）

`CaseBook` 是内存集合，方法返回新台账（不原地改；请保留返回的新台账，
旧台账继续使用会分叉出两条互斥历史，无合并机制）：

- `add_case(...)` → `(新台账, 已封存案件)`。`case_id` 由台账按序分配；
  `next_seq` 恒大于已有最大序号，`case_id` 不可重复（`from_json`
  导入同样校验）。
- `transition(case_id, to, note="", at=None)` → 新台账。
- `add_note(case_id, note, at=None)` → 新台账（只追加备注，不改状态）。
- `get(case_id)`：未知 id 抛 `KeyError`。
- `cases_for_lot(lot, run=None)`：该 lot 的案件，严重度最重在前，同级按创建时间；
  未知 lot 返回空元组，不抛错；不传 `run` 时跨 run 聚合。
- `for_run(run)`：该 run 的全部案件，同上排序。
- `lots(run=None)`：每 lot 一行（`LotSummary`：lot、案件总数、未关闭数、最重
  严重度、**最重未关闭严重度**（无未关闭案件时为 `None`）、最新更新时间、案件 id 列表）。
  排序按最重**未关闭**严重度（已解决的 critical 不驱动待办队列），无未关闭
  案件的 lot 排在最后；同级按未关闭数多在前，再按 lot id。`open_count`
  计 `open` + `investigating` + `waiting`。
- `summary()`：只给计数——总数、lot 数、未关闭总数、按状态计数、按严重度
  计数。不给比率；比率是品质模块的事，且须带分母。
- `verify_all()`：封存与内容不符的 `case_id` 列表（逐案检查，无台账级封存：
  删案或调换顺序发现不了）。
- `to_json()` / `from_json(...)`：导出与重建，重建后封存仍有效；
  导入时校验 `case_id` 唯一、`next_seq` 下限与 history 链合法性。

空台账时三者都返回空（列表为空、计数为 0），不抛错。

## 口径与版本规则

- 计数只给分子与分母的原材料（`summary` 只给计数，不给比率）。
- `content_hash` 覆盖案件内容（含 `history` 的状态与备注），不覆盖
  `created_at` / `updated_at` 与 `history` 的时间戳；改时间戳不改 hash，
  改内容则 `verify()` 为假。hash 是内容自洽性检查，不是签名，也不是
  「记录封存后未被改过」的证明：时间戳可改而不破封存，质保/客户审核
  举证若需可信时间，须另有来源。
- 时间戳须为带时区信息的 ISO 8601（`Z` 或 `±hh:mm`）；无时区与纯日期
  会被拒绝。排序按解析后的时刻，不按字符串。
- 新案件是 `cases/v1`。`cases/v0` 仍可加载，封印不覆盖 `owner`。改严重度定义、状态变迁、建议阈值或字段，即升版本，不静默改。`owner` 与 `waiting` 就是这次升版。v1 的 `content_hash` 覆盖 `owner`（未指定为 `null`）。

## v0 局限

- 无持久化：台账只在内存，`to_json` / `from_json` 是唯一导出。带保留策略
  的存储是后续增量。
- 负责人只是一个名字，没有账号、移交或通知。
- Cases 页面只读：不在浏览器里改状态，也不把台账存下来。
- `case_id` 只在台账内唯一，不作跨台账键。
- `evidence_hash` 只校验格式，不校验该证据包是否存在；悬空链接是录入
  错误，不是校验错误；只接受小写 hex（与 `EvidenceBundle` 自身输出一致）。
- 建议严重度只看迟到分钟数。非迟到原因开的案件（质量 hold、仅注记原因）
  须人工指定严重度并写理由。
- 案件覆盖率未度量：台账只计已有案件，无法回答「多少迟到 lot 根本没有
  案件」；该比率需 explain 侧提供分母（全部迟到 lot 数）。
- `lateness_min` 是建案时快照，会过期；案件不存 lot 的 due 时间，复盘时
  须回 run 记录重算当前迟到。
