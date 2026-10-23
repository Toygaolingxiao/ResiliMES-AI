# zh / ja strings for owner review

PR #14 (`cursor/first-impression-8a58`) also edits `resilimes/demo/static/app.js`. The strings below are the only zh/ja copy changed on this branch for the SMT2020 scenario list. English is included so the meaning is fixed. Please correct the wording. Do not treat these lines as approved.

Scenario buttons prefer `copy.scenarios` over the API text. These two ids were still the six-lot bay (LITHO-02, LOT-1001, 15-minute film). They now name the SMT2020 incidents. Other scenario ids in that object were not edited.

## zh

| Key | New string |
| --- | --- |
| `scenarios.litho_down[0]` | 光刻故障 |
| `scenarios.litho_down[1]` | Litho_FE_92-1 按已发表的光刻维修时间 705.59 分钟停机。快照时刻 2018-01-01。 |
| `scenarios.qtime[0]` | 队列时间 |
| `scenarios.qtime[1]` | SMT2020 已发表的 CQT。前瞻是相邻的 1 小时干法刻蚀到湿法刻蚀，不是 15 分钟成膜。 |
| `chartBefore.litho_down` | 本种子的 EDD |
| `chartAfter.litho_down` | 本种子的 ResiliMES |
| `chartBefore.qtime` | FIFO |
| `chartAfter.qtime` | ResiliMES，已发表 CQT |

Previous zh: 设备故障 / 光刻机 02 宕机 10 小时。LOT-1001 被挡住，交期 18:00 UTC。 / 清洗已经结束。下一道成膜必须在 15 分钟内开工。 / 修理等待 / 已重排 / 8 小时队列 / 15 分钟队列.

## ja

| Key | New string |
| --- | --- |
| `scenarios.litho_down[0]` | リソグラフィ故障 |
| `scenarios.litho_down[1]` | Litho_FE_92-1 が公開されたリソグラフィ修理 705.59 分のあいだ停止。スナップショット 2018-01-01。 |
| `scenarios.qtime[0]` | 待ち時間 |
| `scenarios.qtime[1]` | SMT2020 の公開 CQT。見通しは隣接する 1 時間のドライエッチからウェットエッチで、15 分の成膜ではない。 |
| `chartBefore.litho_down` | このシードの EDD |
| `chartAfter.litho_down` | このシードの ResiliMES |
| `chartBefore.qtime` | FIFO |
| `chartAfter.qtime` | ResiliMES、公開 CQT |

Previous ja: 装置故障 / リソ 02 が 10 時間停止。LOT-1001 が詰まり、納期 18:00 UTC。 / 洗浄は終了済み。次の成膜は 15 分以内に始める。 / 修理を待つ / 再計画 / 待ち 8 時間 / 待ち 15 分.

## en (not for translation review)

| Key | New string |
| --- | --- |
| `scenarios.litho_down` | Lithography breakdown / Litho_FE_92-1 is down for the published 705.59 min lithography repair. Snapshot 2018-01-01. |
| `scenarios.qtime` | Queue time / Published SMT2020 CQT. The look-ahead is the adjacent 1-hour dry etch to wet etch pairs, not a 15-minute film step. |
| `chartBefore.litho_down` | EDD on this seed |
| `chartAfter.litho_down` | ResiliMES on this seed |
| `chartBefore.qtime` | FIFO |
| `chartAfter.qtime` | ResiliMES, published CQT |

The scenario clock shows `2018-01-01 00:00` when `health.fab` is `smt2020`. That is a clock value, not a translated sentence. The API now returns that snapshot as `horizon`. The page no longer overwrites it in JavaScript.

## Round 2 — queue-time button

The previous qtime sentence described a dry-etch look-ahead that the code no longer runs. On the SMT console the button uses the API summary. The copy below is the fallback and must match that summary. Please correct the wording. Do not treat these lines as approved.

### zh

| Key | New string |
| --- | --- |
| `scenarios.qtime[0]` | 队列时间 |
| `scenarios.qtime[1]` | 已发表的 CQT。ResiliMES 增加 PED 风险和湿法刻蚀闸门。该闸门在已存储的种子上触发 0 次。FIFO 不使用该闸门。 |

Previous round-2 zh body: SMT2020 已发表的 CQT。前瞻是相邻的 1 小时干法刻蚀到湿法刻蚀，不是 15 分钟成膜。

### ja

| Key | New string |
| --- | --- |
| `scenarios.qtime[0]` | 待ち時間 |
| `scenarios.qtime[1]` | 公開された CQT。ResiliMES は PED リスクとウェットエッチのゲートを加える。そのゲートは保存済みシードで 0 回だった。FIFO はそのゲートを使わない。 |

Previous round-2 ja body: SMT2020 の公開 CQT。見通しは隣接する 1 時間のドライエッチからウェットエッチで、15 分の成膜ではない。

### en (not for translation review)

| Key | New string |
| --- | --- |
| `scenarios.qtime` | Queue time / Published CQT limits. ResiliMES adds PED risk and a Wet_Etch gate. That gate fired 0 times on the stored seeds. FIFO does not use the gate. |
