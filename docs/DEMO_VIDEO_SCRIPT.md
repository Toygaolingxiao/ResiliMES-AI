# Demo video script (submission film, v2)

Target **≤ 4:00** (rules: demo video 1–4 minutes, show one real request through Meterless Nightshift, hide all keys and tokens; [hackathon/HACKATHON_RULES.md](hackathon/HACKATHON_RULES.md) §4). No narration: the film is silent with burned-in English subtitles (one short line per cue, bottom centre, small white text on a grey box). Console at 1920×1080, browser zoom 100%, Light theme.

**Positioning the film has to carry:** the scheduler stays rule-based and auditable, like mainstream APS. AI makes its decisions understandable to the people who run the fab.

v2 is the v1 film (3:51) re-cut with two new clips. Nothing in the kept v1 footage is re-shot.

- **Clip A (~25 s):** deck slide 7, "Q-time first". It replaces the v1 segment 1:46–2:08, whose subtitle and slide described the old comparison.
- **Clip B (~28 s):** the Gantt right-click investigation, inserted right after the litho reschedule. It continues from the Gantt that is already on screen.
- The v1 cue at 2:30–2:44 described the explainer wrongly. In v2 its subtitle box is masked and a corrected line is burned in.

Setup and the live-request recipe stay in [DEMO_SCRIPT.md](DEMO_SCRIPT.md) ("Before you hit record").

## Rules for this film

- **Secrets.** Never open `.env`, PowerShell history, the Nightshift token file or the Zetaris login files on camera. Start servers from a terminal that was opened and cleared before recording (`cls` / `clear`). Blur any frame that shows a header value.
- **One real request.** It is already in v1, and v2 keeps it: a live Nemotron call through Nightshift (`http://127.0.0.1:8088/v1`, model `nvidia/nemotron-3.5-lightning-30b-a3b`), with the reply's `response_models` on screen.
- **Honest labels.** Clip B is recorded on `make demo` (offline, no token), so its answer text comes from the scripted path. Its subtitles say so ("offline demo") and never call it a live Nemotron answer. The tier and evidence on screen are real and computed by code.
- **Numbers.** A subtitle quotes only numbers that are on screen in that frame or on the deck slide being shown, and every deck number cites its repo doc.
- **Q-time first.** A schedule with an avoidable Q-time violation is infeasible. EDD appears only as an infeasible reference (1,719 avoidable violations). Never say we "beat" EDD, are "ahead of" it, or "lose to" it.
- **AI never decides.** No subtitle may say the AI scheduled, chose or improved the plan. It explains, advises, and is fact-checked.

## v2 timeline

Nominal times, built by `build_v2.sh` from v1 + clip A + clip B. The final times shift by the real clip lengths: `[TBD after re-record]`.

| # | v2 time | Source | Screen | Subtitle (burned) |
|---|---|---|---|---|
| 1 | 0:00–0:20 | v1 0:00–0:20 | Title, problem, Overview | v1 cues 1–3, unchanged |
| 2 | 0:20–0:46 | v1 0:32–0:58 (12 s of static Overview cut) | Overview → Tools → litho Plan | v1 cues 3–4 |
| 3 | 0:46–1:10 | v1 1:14–1:38 (16 s reschedule wait cut) | litho reschedule cards → Gantt | v1 cue 5 |
| 4 | **1:10–1:38** | **clip B** | Gantt: zoom → right-click a family-row gap → question → panel (answer, tier, evidence) → a tool-row gap | new, 3 cues (below) |
| 5 | 1:38–1:46 | v1 1:38–1:46 | deck flash | "Rules schedule first. AI only explains and advises; it never writes the schedule." |
| 6 | **1:46–2:11** | **clip A** | deck slide 7, Q-time first | new, 2 cues (below) |
| 7 | 2:11–2:33 | v1 2:08–2:30 | deck slide 8, what's left after the gate | v1 cue 8 |
| 8 | 2:33–2:47 | v1 2:30–2:44, old subtitle box masked | Investigator UI (live) | corrected cue (below) |
| 9 | 2:47–3:54 | v1 2:44–3:51 | live explainer request, Zetaris parity, agents, AI results, close | v1 cues 10–14 |

Total ≈ 3:54. If the real clips run long, trim clip B's idle frames first and keep the total ≤ 4:00. Never cut segment 9 (the live request and parity).

### New subtitles

| When | Text |
|---|---|
| clip B, first ~9 s | "Right-click a gap on the Gantt to ask why it is idle. Offline demo, same code path." |
| clip B, middle ~10 s | "The tier (decision record / rule-emergent / unknown) is set by code, with the evidence." |
| clip B, last ~9 s | "A tool-row gap: advice only. The schedule does not change." |
| clip A, first ~12 s | "Q-time first: the hard gate is on by default. An avoidable violation makes a schedule infeasible. 99.26%, 71 avoidable over 3 seeds." |
| clip A, last ~13 s | "EDD is only an infeasible reference (1,719 avoidable). Q-time first costs about 17 lots and 10 on-time points per run." |
| seg. 8 (corrected) | "Live AI: NVIDIA Nemotron through Meterless Nightshift. Investigator: at most 6 evidence calls, one cause from a fixed list, rule answer if it fails." |

The full retimed subtitle file (draft) and the build script are kept outside the repo, next to the footage (`film/subs_v2_draft.srt`, `film/build_v2.sh`). The build script burns subtitles only into clip A, clip B and segment 8, because the kept v1 segments already carry correct burned subtitles. It also writes the shifted full `.srt` for a soft-subtitle upload.

## Recording clips A and B

- **Clip A.** Open `docs/deck/index.html#7` full screen (F11) at 1920×1080. Hold still about 25 s and move the mouse only to point at the 99.26% row, then at the EDD column. No slide changes.
- **Clip B.** `make demo` → http://localhost:8000 → SMT2020 → Gantt. Zoom into about 2 h on a busy family, then:
  1. click a gap;
  2. right-click a gap on a **family row** and pick the question;
  3. wait for the panel (answer, tier chip, evidence list) and hold 3 s;
  4. right-click a gap on a **tool row** and pick "why idle?";
  5. hold on the answer.

  Mouse moves are slow and deliberate, one target per second at most.
- Record with Xbox Game Bar (Win+Alt+R), browser only, notifications off. Keep the raw files: `clipA_slide7.mp4`, `clipB_gantt.mp4`.

## 中文摘要（给自己看）

| # | v2 时间 | 来源 | 内容 |
|---|---|---|---|
| 1–3 | 0:00–1:10 | v1（剪掉总览静止 12 s、重排等待 16 s） | 标题、问题、总览、Tools、光刻宕机重排 |
| 4 | 1:10–1:38 | **新片段 B** | 甘特图右键：家族行空档 → 选问题 → 面板（答案/等级/证据）→ 机台行空档。字幕注明"离线演示"，不说是实时 Nemotron |
| 5 | 1:38–1:46 | v1 | "规则先排程，AI 只解释和建议，不写排程" |
| 6 | 1:46–2:11 | **新片段 A** | 幻灯片第 7 页：Q-time 优先、硬门控默认开、可避免违约即不可行；99.26%、71；EDD 只是不可行参考（1,719）；代价约 17 批、准时率约 10 点 |
| 7 | 2:11–2:33 | v1 | 第 8 页：门控之后剩下的违约 |
| 8 | 2:33–2:47 | v1，旧字幕盖掉 | 改正字幕：调查员最多 6 次证据调用、从固定原因表选一个、失败就回到规则答案 |
| 9 | 2:47–3:54 | v1 | 实时解释请求、Zetaris PARITY OK、各代理职责、AI 结果、结尾 |

注意：`.env`、token、PowerShell 历史一律不入镜；不说"AI 排得更好"，也不说"超过 / 领先 EDD"；最终时间以 v2 实际剪辑为准（[TBD after re-record]）。
