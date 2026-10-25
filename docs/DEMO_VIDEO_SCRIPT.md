# Demo video script (submission film)

Target **3:00**, hard limit **4:00** (rules: demo video 1–4 minutes, show one real request through Meterless Nightshift, hide all keys and tokens; [hackathon/HACKATHON_RULES.md](hackathon/HACKATHON_RULES.md) §4). English narration. Record the console at 1920×1080, browser zoom 100%, Light theme, language English. The deck is [deck/index.html](deck/index.html); shots 1, 5 and 9 cut to its slides (14 slides).

This file replaces the shot list in [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the submission film. The setup there ("Before you hit record": `make demo-live`, badge, banner, Zetaris load) still applies and is not repeated here. The older shot lists in that file quote numbers from before the planning-layer default and are not used in this film.

## Rules for this film

- **Secrets.** Never open `.env`, PowerShell history, the Nightshift token file or the Zetaris login files on camera. Start the server from a terminal that was opened and scrolled clear before recording. If a terminal must be on screen, run `cls` / `clear` first. Blur any frame that shows a header value. Do not read a token aloud.
- **One real request.** Shot 6 is a live Nemotron call through Nightshift (`http://127.0.0.1:8088/v1`, model `nvidia/nemotron-3.5-lightning-30b-a3b`). The chip next to the answer must read `Nemotron`, not `offline stand-in`. If it reads `offline stand-in`, stop: the token is not set and that take is not this film.
- **Numbers.** Speak only numbers that are on screen in that frame, or that are on the deck slide being shown. Every deck number cites its repo doc. Do not tune a seed, due or weight to get a nicer take.
- **Q-time first.** Q-time first: the gate admits a lot only if the whole Q-time segment can finish in time. Never say we "lose to" or "beat" EDD; EDD is only the industry reference (infeasible: 1,719 avoidable Q-time violations).
- **Done.** Live Nemotron evals, video link and the live reply values (`response_models`, `mocked: false`, `advice_only: true`) are filled in the deck and the film.

## Shot list

| # | Time | Screen | Narration (English, spoken) |
|---|---|---|---|
| 1 | 0:00–0:15 | Deck slide 2 (Problem), then cut to the console Overview tab, idle. | "A fab shift lead trades delivery, queue time and plan stability every hour, and has to explain every call. ResiliMES-AI schedules the full public SMT2020 fab and with Q-time as a hard constraint, and uses AI only to explain and advise." |
| 2 | 0:15–0:40 | Overview tab. Point at the banner (106 groups, 1313 tools, 102 litho, 2156 lots), then the Bottlenecks and WIP pile-ups cards. | "This is the public industry benchmark SMT2020: one thousand three hundred thirteen tools and two thousand one hundred fifty-six lots. These families are busy over their queue limit, and these are the WIP pile-ups the next shift inherits." |
| 3 | 0:40–0:50 | Tools tab, Busiest families. Hover the first family's Next-up list (setup chip, slack chip). | "Per tool: the running lot and the next lots, with setup and slack. A daily plan sets every step's due, and a hard Q-time gate guards dispatch." |
| 4 | 0:50–1:15 | Plan tab → **Lithography breakdown** → **Reschedule this shift**. Wait for the six cards. Point at re-cleans, Q-time violations and on-time with its denominator, then at the study line under the cards. | "Litho FE 92-1 goes down for the published repair. One click reschedules the shift. Read the cards with their denominators" *(read the before → after values on screen)*. "The line under the cards says this click is seed one, twelve hours, and is not the five-seed study." |
| 5 | 1:15–1:45 | Deck slide 7, hold 18 s; then slide 8, hold 12 s. | "Q-time comes first. A schedule with an avoidable Q-time violation is infeasible, so we discard it, not compare it. The hard gate is on by default: ninety-nine point two six percent compliance, seventy-one avoidable misses over three seeds. EDD, the industry reference, has one thousand seven hundred nineteen. Feasibility costs about seventeen lots and ten on-time points per run. The seventy-one left are chained furnace windows: our remaining work." |
| 6 | 1:45–2:15 | **Live request.** AI evidence tab → Investigator → keep the first case → **Investigate**. While it works, keep the console in frame. When it answers, point at the `Nemotron` chip, the primary cause, the evidence-call chain, the fact-check line, and the injected fault and rule baseline shown beside it. Do not claim a win from one case. | "This is a real request to NVIDIA Nemotron through Meterless Nightshift on this PC. The investigator re-runs the faulted case, gets at most six evidence calls on the simulator run, names one cause from a fixed list, and every number in its answer is checked against a tool result. If the check fails or the model times out, it degrades to the rule answer, labelled. The lever is advice only." |
| 7 | 2:15–2:30 | Cut to a cleared terminal (no env, no history). Run the response check below and show only its output: `response_models` with the Nemotron id and `advice_only: true`. Optional 3 s cut to the Nightshift console request list with the key column cropped. | "The reply records the model that answered: Nemotron. The key never appears; it lives in the environment and is never logged." |
| 8 | 2:30–2:40 | Terminal: `python scripts/check_zetaris_smt.py` → scroll to `PARITY OK`. | "The fab master data, eleven tables and six thousand nine hundred thirty-five rows, is loaded in Zetaris, and this check matches it row for row against the files: parity OK." |
| 9 | 2:40–3:00 | Deck slide 11 (AI results), then slide 14 for the last second. | "Every live reply was Nemotron. The investigator equals the rule baseline, twenty of twenty-four, all fact-checked. The explainer names the right cause on eleven of twelve lots, but only one of its twelve levers held up in the simulator, so every claim is verified. The shift lead escalated zero times: the rules already hold Q-time." |

Total 3:00. If a shot runs long, trim shot 2 or 4; do not cut shot 6 or 7.

### Shot 7 command

Run from a fresh terminal after `make demo-live` is serving. It sends no credentials; the server holds the token.

```bash
curl -s -X POST http://127.0.0.1:8000/api/ai/explain \
  -H 'content-type: application/json' \
  -d '{"lot_id":"Init_Lot_6_2","seed":1,"lang":"en"}' \
  | python -m json.tool | grep -E -A2 '"(response_models|advice_only)"'
```

If `Init_Lot_6_2` is not in `GET /api/ai/explainer/lots?seed=1` on your build, use the first lot that list returns. On PowerShell, put the JSON body in a file and pass `-d @body.json`.

### Before the first take

- `make demo-live` with the Nightshift token and Zetaris credentials in `.env` (see [DEMO_SCRIPT.md](DEMO_SCRIPT.md) "Before you hit record"). The query line under the banner must not say `local extract (Zetaris not called)`.
- Rehearse shot 6 once: a live investigator answer takes model time. If it takes longer than about 20 s, record it as its own take and cut the wait; say in the edit that time was cut (a small "time cut" caption is enough).
- Close every other app and browser tab. Turn off notifications.

## 中文摘要（给自己看）

| # | 时间 | 这一镜做什么 |
|---|---|---|
| 1 | 0:00–0:15 | 幻灯片第 2 页（问题），再切到控制台总览。讲：班长每小时都在交期、Q-time、计划稳定性之间取舍；我们排程全 SMT2020 工厂，AI 只解释和建议。 |
| 2 | 0:15–0:40 | 总览页：指横幅（106 组、1313 台、2156 批）、瓶颈卡、WIP 堆积卡。 |
| 3 | 0:40–0:50 | Tools 页：每台机当前批次、下一批（换型/余量）；计划层给每步交期，硬 Q-time 门控守住派工。 |
| 4 | 0:50–1:15 | Plan 页：光刻宕机 → 重排本班；只念屏幕上的卡片数字和分母，并指出“这是 seed 1、12 小时，不是五种子研究”。 |
| 5 | 1:15–1:45 | 幻灯片第 7、8 页：Q-time 优先——有可避免 Q-time 违约的排程不可行，直接舍弃，不做比较。硬门控默认开：合规 99.26%，3 种子可避免违约 71；EDD 仅作行业参考（不可行，1,719）。代价约每次 17 批、准时率约 10 点。剩余 71 主要是扩散炉连锁窗口，是待办。 |
| 6 | 1:45–2:15 | **真实请求**：AI evidence → Investigator → Investigate。必须看到“Nemotron”标签（不是 offline stand-in），指出主因、证据调用链、事实核查行。 |
| 7 | 2:15–2:30 | 干净终端跑 curl，只显示 `response_models`（Nemotron 型号）和 `advice_only: true`；可选 3 秒 Nightshift 请求列表，遮住 key 列。 |
| 8 | 2:30–2:40 | 终端跑 `check_zetaris_smt.py`，停在 `PARITY OK`（11 张表、6935 行）。 |
| 9 | 2:40–3:00 | 幻灯片第 11 页：全部回复均为 Nemotron；调查员 20/24 与规则持平；解释器原因 11/12 正确，但改进杠杆仿真复核仅 1/12 命中，所以每条主张都要仿真验证；AI 班长 0 次升级（规则已守住 Q-time）。最后一秒第 14 页。 |

注意：`.env`、token、PowerShell 历史一律不入镜；只念屏幕上或幻灯片上有出处的数字；第 6、7 镜不能剪掉。
