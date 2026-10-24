# ResiliMES UI strings

Every key the console can show. Chinese is zh-CN. Japanese is the wording a fab engineer would use on a shift.
Times in critic messages are the shift clock (the scenario horizon plus the minute offset), not `t=` minutes.

| Key | English | 中文 | 日本語 |
| --- | --- | --- | --- |
| `taglineIdle` | This shift | 本班 | 当直 |
| `taglineBay` | This disruption | 这次异常 | この異常 |
| `taglineScale` | 1,000 lots | 1000 个批次 | 1000ロット |
| `versionNote` | The first screen is the decision. Metrics holds the other numbers. Checks lists every constraint. | 第一屏是决策。指标页放其余数字。校验页列出每条约束。 | 最初の画面が判断です。指標に残りの数字、検証に制約の一覧を出します。 |
| `lang` | Language | 语言 | 言語 |
| `disruption` | Scenarios | 场景 | シナリオ |
| `bay` | Tools | 装置 | 装置 |
| `describe` | Or describe one | 或直接描述 | または文章で |
| `placeholder` | ETCH-02 down for 5 hours | ETCH-02 宕机 5 小时 | ETCH-02 が5時間停止 |
| `run` | Run | 重排 | 実行 |
| `runLong` | Reschedule | 按描述重排 | この内容で再スケジュール |
| `refused` | Request refused. | 请求未执行。 | 依頼は実行されませんでした。 |
| `refusedLine` | Refused: | 未采用： | 不採用： |
| `idle` |  |  |  |
| `working` | Rescheduling. | 正在重排。 | 再スケジュール中。 |
| `emptyTitle` | This shift | 本班 | 当直 |
| `emptyHint` | Run a scenario to compare the current plan with the reschedule. | 选一个场景，对比当前计划与重排结果。 | シナリオを実行すると、現在の計画と再スケジュールを比べます。 |
| `mock` |  |  |  |
| `live` |  |  |  |
| `offline` | Sample | 示例 | サンプル |
| `clock` | Shift clock | 班次时钟 | 直の時刻 |
| `tabRecover` | Plan | 排程 | 計画 |
| `tabAnalyze` | Metrics | 指标 | 指標 |
| `tabVerify` | Checks | 校验 | 検証 |
| `details` | Details | 详情 | 詳細 |
| `now` | Now | 现在 | 現在 |
| `due` | Due | 交期 | 納期 |
| `moved` | Moved | 已改机 | 装置変更 |
| `fresh` | New | 新增 | 追加 |
| `down` | Down | 宕机 | 停止 |
| `maint` | Maintenance | 保养 | 保全 |
| `held` | Held | 暂扣 | 保留 |
| `heldAside` | held lots left out | 暂扣批次不计入 | 保留ロットは含めない |
| `lots` | Lots | 批次 | ロット |
| `lot` | Lot | 批次 | ロット |
| `pri` | Pri | 优先级 | 優先度 |
| `step` | Step | 工序 | 工程 |
| `from` | From | 从 | 変更前 |
| `to` | To | 到 | 変更後 |
| `before` | Before | 重排前 | 変更前 |
| `after` | After | 重排后 | 変更後 |
| `tardy` | Tardiness | 延误 | 遅延 |
| `change` | Change | 变化 | 変化 |
| `verified` | contract verified | 约束已校验 | 制約を検証済み |
| `explainer` | Explanation | 说明 | 説明 |
| `checkpoint` | Checkpoint | 检查点 | チェック |
| `of` | of | / | / |
| `computed` | computed | 已算出 | 算出済み |
| `nodeScout` | Detect | 发现 | 検知 |
| `nodeZetaris` | Read data | 读数 | データ参照 |
| `nodePlant` | Read data | 读数 | データ参照 |
| `nodeSense` | Read data | 读数 | データ参照 |
| `nodePlan` | Plan | 排程 | 計画 |
| `nodeCritic` | Check | 校验 | 判定 |
| `nodeExplain` | Explain | 说明 | 説明 |
| `nodeExplainer` | Explain | 说明 | 説明 |
| `nodeCommit` | Save | 下发 | 確定 |
| `wait` | Waiting | 等待 | 待機 |
| `runState` | Running | 进行中 | 実行中 |
| `done` | Done | 完成 | 完了 |
| `reads` | reads | 次读取 | 件の参照 |
| `facts` | facts | 条事实 | 件の事実 |
| `ops` | steps | 道工序 | 工程 |
| `holds` | holds | 个暂扣 | 件保留 |
| `events` | events | 条记录 | 件 |
| `loopLabel` | Recovery steps | 重排步骤 | 復旧の手順 |
| `byArea` | Utilization by area | 各区利用率 | エリア別稼働率 |
| `kpiOtd` | On-time delivery | 准时交付率 | 納期遵守率 |
| `kpiTardy` | Weighted tardiness | 加权延误 | 加重遅延 |
| `kpiSpan` | Makespan | 总工期 | 総工期 |
| `kpiUtil` | Utilization | 利用率 | 稼働率 |
| `kpiChange` | Changeovers | 换型 | 段取り替え |
| `kpiRisk` | Lots at risk | 风险批次 | 遅延リスクロット |
| `kpiMoved` | Lots moved | 改机批次 | 装置を変えたロット |
| `kpiLead` | Mean lead time | 平均周期 | 平均リードタイム |
| `kpiWait` | Mean wait | 平均等待 | 平均待ち |
| `kpiX` | X-factor | 流动因子 | Xファクタ |
| `otdTip` | Lots finished by their due time, divided by lots on the plan. | 在交期内完工的批次，除以计划上的批次数。 | 納期までに終わったロットを、計画上のロット数で割った値です。 |
| `tardyTip` | Sum of lateness, weighted by priority. A held lot is not given a finish time. | 延误时间按优先级加权求和。暂扣批次不假设完工时间。 | 遅延時間を優先度で重み付けした合計です。保留ロットに完了時刻は置きません。 |
| `riskTip` | Lots that miss their due time, including lots the plan could not place. Priority 1 and 2. | 错过交期的批次，含排不进去的。只计优先级 1 和 2。 | 納期に遅れるロット。置けなかったロットを含みます。優先度 1 と 2 です。 |
| `spanTip` | Finish of the last step on that plan. | 这版计划最后一道工序的完工时间。 | その計画で最後の工程が終わる時刻です。 |
| `leadTip` | Mean time from the shift clock to completion, for lots the plan finishes. Held lots are omitted. | 从班次时钟到完工的平均时间，只计排得下的批次。暂扣批次不算。 | 直の開始から完了までの平均です。置けたロットだけを見ます。保留は除きます。 |
| `waitTip` | Mean gap between consecutive steps of the same lot. | 同一批次相邻工序之间的平均间隔。 | 同じロットの連続する工程の平均間隔です。 |
| `utilTip` | One window for both plans: the longer makespan. Busy time divided by the time tools are up. | 两版计划用同一个时间窗，取较长的总工期。忙碌时间除以装置可用时间。 | 両方の計画で同じ時間窓です。長い方の総工期を使います。稼働時間を装置の可用時間で割ります。 |
| `xTip` | Mean completion time divided by raw process time. 1.0 is all processing. Held lots are omitted. | 平均完工时间除以纯加工时间。1.0 表示没有等待。暂扣批次不算。 | 平均完了時間を正味加工時間で割った値です。1.0 は待ちなし。保留は除きます。 |
| `changeTip` | Setups charged because the recipe family changed. | 因配方族变化而计入的换型次数。 | レシピ族が変わって計上した段取り替えです。 |
| `qtimeTitle` | Queue time | 等待时限 | キュータイム |
| `qtimeNote` | End of one step to the start of the next. | 上一道结束到下一道开工。 | 前工程の終了から次工程の着工まで。 |
| `qtimeTip` | Pairs that start inside the limit, including pairs past 80 percent of it. Holds and violations are the misses. | 在时限内开工的工序对，含已用掉 80% 时限的。暂扣和超时算未守住。 | 制限内に着工した組です。制限の 80% を超えた組も含みます。保留と超過は未達です。 |
| `violationTip` | Placed pairs whose gap is longer than the limit. | 已排上、但间隔超过时限的工序对。 | 計画に載り、間隔が制限を超えた組です。 |
| `atRiskTip` | Placed pairs still inside the limit, past 80 percent of it. | 已排上、仍在时限内、但已超过 80% 的工序对。 | 計画に載り、制限内だが 80% を超えた組です。 |
| `bottleneckTitle` | Bottleneck | 瓶颈 | ボトルネック |
| `bottleneckNote` | Most remaining minutes per up-tool minute, over one day. Down tools add no time. | 一天内，剩余加工时间相对可用装置时间最多的区域。宕机装置不计入。 | 1日あたり、残り加工時間が稼働装置の時間に対して最も多いエリアです。停止装置は入れません。 |
| `bottleneckTip` | Same-priority work in this area, and the step that feeds it, is dispatched first. | 同优先级时，先派这个区域以及给它供料的工序。 | 同じ優先度では、このエリアとそこへ供給する工程を先に差し立てます。 |
| `compliance` | Inside limit | 时限内 | 制限内 |
| `violations` | Misses | 超时 | 超過 |
| `atRisk` | At risk | 临近时限 | 制限間近 |
| `rework` | Rework | 返工 | 再加工 |
| `reticle` | Reticle | 光罩 | レチクル |
| `areaTip` | Busy time in this area divided by up-time in this area, on the shared window. | 该区域忙碌时间除以可用时间，两版计划用同一个时间窗。 | このエリアの稼働時間を可用時間で割った値です。両方の計画で同じ時間窓です。 |
| `waitPair` | Mean gap from {from} to {to} on the new plan, across {n} lots. | 新计划上从 {from} 到 {to} 的平均间隔，共 {n} 个批次。 | 新しい計画で {from} から {to} までの平均間隔です。{n} ロット。 |
| `tardyCellTip` | Lateness before, then after. A held lot is not given a finish time. | 左边是重排前的延误，右边是重排后。暂扣批次不假设完工时间。 | 左が変更前、右が変更後の遅延です。保留ロットに完了時刻は置きません。 |
| `movedTip` | Lots whose tool changed on a step that exists in both plans. | 两版计划都有的工序里，换了装置的批次。 | 両方の計画にある工程で、装置が変わったロットです。 |
| `downTip` | Minutes down or in maintenance inside the shared window. Left out of the utilization denominator. | 同一时间窗内的宕机或保养时间。不放入利用率的分母。 | 同じ時間窓の中の停止または保全の時間です。稼働率の分母には入れません。 |
| `progressTip` | Steps finished, out of the six in the recovery. | 重排六个步骤里已完成的步数。 | 復旧 6 手順のうち終わった数です。 |
| `dueTip` | Due time of a priority-1 lot, on the same scale as the bars. | 优先级 1 批次的交期，与条形同一时间刻度。 | 優先度 1 の納期です。バーと同じ時間軸です。 |
| `heldOut` | Held lots left this figure. It is not a win. | 暂扣批次没有进入这个数。这不是变好。 | 保留ロットはこの数字に入っていません。改善ではありません。 |
| `downWindow` | Down in this window | 本时间窗内宕机 | この時間窓で停止 |
| `byTool` | By tool | 按装置 | 装置別 |
| `byLot` | By lot | 按批次 | ロット別 |
| `whereWait` | Where the wait is | 等待出在哪 | 待ちの場所 |
| `route` | Route | 工艺路线 | 工程経路 |
| `waitGap` | wait | 等待 | 待ち |
| `themeLight` | Light | 浅色 | ライト |
| `themeDark` | Dark | 深色 | ダーク |
| `pass` | Pass | 通过 | 合格 |
| `fail` | Fail | 未通过 | 不合格 |
| `rejected` | Refused | 未采用 | 不採用 |
| `check` | Check | 检查项 | 項目 |
| `result` | Result | 结果 | 結果 |
| `reason` | Reason | 原因 | 理由 |
| `verifyLead` | One row per check. Open a row for the reason. | 每项检查一行。展开可看原因。 | 検査ごとに 1 行です。開くと理由が出ます。 |
| `category` | Category | 类别 | 分類 |
| `checkStatus` | Status | 状态 | 状態 |
| `passed` | Passed | 通过 | 合格 |
| `failed` | Failed | 未通过 | 不合格 |
| `skipped` | Skipped | 跳过 | 対象外 |
| `refusedPlan` | Refused plan | 未采用的方案 | 不採用の案 |
| `categories.equipment` | Equipment | 装置 | 装置 |
| `categories.lot` | Lot | 批次 | ロット |
| `categories.process` | Process | 工艺 | 工程 |
| `categories.material` | Material | 物料 | 資材 |
| `categories.time` | Time | 时间 | 時間 |
| `figures` | Figures | 指标 | 指標 |
| `figuresNote` | Gray is not a direction. A hold cannot turn a shorter plan green. | 灰色不是变好或变差。暂扣不会让更短的计划变成改善。 | 灰色は改善でも悪化でもありません。保留があっても、短い計画を改善とは呼びません。 |
| `utilNote` | Highest share of up-time first. | 按可用时间占比从高到低。 | 可用時間に占める割合の高い順です。 |
| `waitNote` | Largest gaps on the new plan. | 新计划上间隔最大的工序。 | 新しい計画で間隔の大きい工程です。 |
| `lotNote` | The step whose tool changed. The first tool if the lot did not move. | 换了装置的那道工序。没换机则显示第一台装置。 | 装置が変わった工程です。変わっていなければ最初の装置です。 |
| `lotNoteScale` | Steps whose tool differs from EDD dispatch. First 12. | 与 EDD 派工装置不同的工序。前 12 条。 | EDD 差し立てと装置が違う工程です。先頭 12 件。 |
| `intents.machine_down` | tool down | 装置宕机 | 装置停止 |
| `intents.rush_order` | rush lot | 急单 | 特急ロット |
| `intents.material_shortage` | material short | 缺料 | 資材不足 |
| `intents.query_status` | status | 状态 | 状態 |
| `intents.explain` | explain | 说明 | 説明 |
| `intents.emergency_stop` | emergency stop | 紧急停止 | 緊急停止 |
| `intents.rework` | rework | 返工 | 再加工 |
| `intents.qtime` | queue time | 等待时限 | キュータイム |
| `verdicts.accept` | Accepted | 已接受 | 採用 |
| `verdicts.conditional` | Conditional | 有条件接受 | 条件付き |
| `verdicts.reject` | Rejected | 已拒绝 | 不採用 |
| `checks.equipment_status` | Tool status | 装置状态 | 装置状態 |
| `checks.capability` | Qualification | 工艺资格 | プロセス資格 |
| `checks.overlap` | One lot at a time | 同时只跑一批 | 同時は1ロット |
| `checks.wip` | WIP limit | 在制上限 | 仕掛上限 |
| `checks.operators` | Operators | 人员 | 人員 |
| `checks.material` | Material | 物料 | 資材 |
| `checks.precedence` | Route order | 工艺顺序 | 工程順 |
| `checks.preemption` | Running lot | 加工中不撤批 | 加工中は維持 |
| `checks.qtime` | Queue time | 等待时限 | キュータイム |
| `checks.other` | Other | 其他 | その他 |
| `status.IDLE` | Idle | 空闲 | 空き |
| `status.RUNNING` | Running | 加工中 | 加工中 |
| `status.DOWN` | Down | 宕机 | 停止 |
| `status.SETUP` | Setup | 换型 | 段取り |
| `status.MAINTENANCE` | Maintenance | 保养 | 保全 |
| `status.ok` | In stock | 有库存 | 在庫あり |
| `status.short` | Short | 短缺 | 不足 |
| `areas.Lithography` | Lithography | 光刻 | 露光 |
| `areas.Etch` | Etch | 刻蚀 | エッチング |
| `areas.CMP` | CMP | CMP | CMP |
| `areas.Deposition` | Deposition | 成膜 | 成膜 |
| `areas.Metrology` | Metrology | 量测 | 測定 |
| `areas.Clean` | Clean | 清洗 | 洗浄 |
| `areas.Furnace` | Furnace | 炉管 | 炉 |
| `areas.Diffusion` | Diffusion | 扩散 | 拡散 |
| `scenarios.litho_down.0` | Lithography breakdown | 光刻故障 | リソグラフィ故障 |
| `scenarios.litho_down.1` | Litho_FE_92-1 is down for the published 705.59 min lithography repair. Snapshot 2018-01-01. | Litho_FE_92-1 按已发表的光刻维修时间 705.59 分钟停机。快照时刻 2018-01-01。 | Litho_FE_92-1 が公開されたリソグラフィ修理 705.59 分のあいだ停止。スナップショット 2018-01-01。 |
| `scenarios.rush_order.0` | Rush lot | 急单 | 特急ロット |
| `scenarios.rush_order.1` | A hot lot is due in 3 h. Running lots stay on their tools. | 急单 3 小时内交货。正在加工的批次不撤下。 | 特急の納期は3時間。加工中ロットは装置に残します。 |
| `scenarios.material_shortage.0` | Resist short | 光刻胶短缺 | レジスト不足 |
| `scenarios.material_shortage.1` | RESIST-UV is at zero. Lots that still need it wait. | RESIST-UV 库存为零，还要用的批次等待。 | RESIST-UV の在庫はゼロ。未使用ロットは待ちます。 |
| `scenarios.rework.0` | Overlay rework | 套刻返工 | 重ね合わせ再加工 |
| `scenarios.rework.1` | LOT-1004 failed overlay. Strip, expose, and measure once. | LOT-1004 套刻失败。去胶、再曝光、复测一次。 | LOT-1004 は重ね合わせ不良。剥離、再露光、再測定を1回。 |
| `scenarios.qtime.0` | Queue time | 队列时间 | 待ち時間 |
| `scenarios.qtime.1` | Published CQT limits. ResiliMES adds PED risk and a Wet_Etch gate. That gate fired 0 times on the stored seeds. FIFO does not use the gate. | 已发表的 CQT。ResiliMES 增加 PED 风险和湿法刻蚀闸门。该闸门在已存储的种子上触发 0 次。FIFO 不使用该闸门。 | 公開された CQT。ResiliMES は PED リスクとウェットエッチのゲートを加える。そのゲートは保存済みシードで 0 回だった。FIFO はそのゲートを使わない。 |
| `scenarios.scale.0` | 1,000 lots | 1000 批次 | 1000ロット |
| `scenarios.scale.1` | 36 tools. One scanner is down for 10 h. Compare with EDD. | 36 台装置，一台光刻机宕机 10 小时。与 EDD 派工对比。 | 36台。スキャナー1台が10時間停止。EDD 差し立てと比較。 |
| `chartBefore.litho_down` | EDD on this seed | 本种子的 EDD | このシードの EDD |
| `chartBefore.rush_order` | Without the rush | 无急单 | 特急なし |
| `chartBefore.material_shortage` | Resist in stock | 光刻胶有库存 | レジスト在庫あり |
| `chartBefore.rework` | No rework | 无返工 | 再加工なし |
| `chartBefore.qtime` | FIFO | FIFO | FIFO |
| `chartBefore.scale` | EDD dispatch | EDD 派工 | EDD 差し立て |
| `chartAfter.litho_down` | ResiliMES on this seed | 本种子的 ResiliMES | このシードの ResiliMES |
| `chartAfter.rush_order` | With the rush | 含急单 | 特急あり |
| `chartAfter.material_shortage` | Resist stockout | 光刻胶断料 | レジスト欠品 |
| `chartAfter.rework` | Strip and re-expose | 去胶再曝光 | 剥離して再露光 |
| `chartAfter.qtime` | ResiliMES, published CQT | ResiliMES，已发表 CQT | ResiliMES、公開 CQT |
| `chartAfter.scale` | Priority plan | 优先级排程 | 優先度計画 |
| `scaleWindow` | First 12 hours | 前 12 小时 | 最初の12時間 |
| `scaleNote` | Busy share of each tool, by hour. A hatch means the tool is down. | 每台装置每小时的忙碌占比。斜线表示宕机。 | 装置ごとの 1 時間の稼働割合です。斜線は停止です。 |
| `scheduleWord` | Schedule | 排程 | 計画 |
| `criticWord` | Checks | 校验 | 検証 |
| `stepsWord` | steps | 道工序 | 工程 |
| `toolsWord` | tools | 台装置 | 台 |
| `optTitle` | Best known result | 与最优解的差距 | 最適解との差 |
| `optNote` | The released plan stays this schedule. The row is a reference search under the same rules. | 下发的仍是这版排程。这一行是同一规则下搜到的参考解。 | 確定するのはこの計画のままです。この行は同じルールで探した参照解です。 |
| `optProvedZero` | Weighted tardiness matches the best result (proved) | 加权延误与最优解一致（已证明） | 加重遅延は最適解と一致（証明済み） |
| `optProvedTardy` | The reference cuts weighted tardiness by {delta} (proved) | 参考解把加权延误缩短 {delta}（已证明） | 参照解は加重遅延を {delta} 短縮（証明済み） |
| `optProvedSpan` | Weighted tardiness matches. The schedule is {delta} shorter (proved) | 加权延误与最优解一致。总工期短 {delta}（已证明） | 加重遅延は最適解と同じ。総工期は {delta} 短い（証明済み） |
| `optFeasible` | This plan is within {gap}% of the bound | 当前排程在下界的 {gap}% 以内 | この計画は下界の {gap}% 以内 |
| `optLnsTardy` | A local search cut weighted tardiness by {delta} in {seconds} s | 局部搜索在 {seconds} 秒内把加权延误缩短 {delta} | 近傍探索が {seconds} 秒で加重遅延を {delta} 短縮 |
| `optLnsSpan` | A local search cut makespan by {delta} in {seconds} s | 局部搜索在 {seconds} 秒内把总工期缩短 {delta} | 近傍探索が {seconds} 秒で総工期を {delta} 短縮 |
| `optKept` | No shorter plan in {seconds} s. This schedule stays. | {seconds} 秒内没有更短的方案。保留当前排程。 | {seconds} 秒では短縮なし。この計画を残します。 |
| `optHeuristic` | This plan | 当前排程 | この計画 |
| `optBest` | Reference | 参考解 | 参照解 |
| `optBound` | Bound | 下界 | 下界 |
| `optChanged` | Steps that differ in the reference | 参考解里不同的工序 | 参照解で違う工程 |
| `optStart` | Start | 开工 | 着工 |
| `toolsLabel` | Tools | 装置 | 装置 |
| `materialsLabel` | Materials | 物料 | 資材 |
| `runRecommended` | Reschedule this shift | 重排本班 | 当直を再スケジュール |
| `recommended` | Recommended | 建议 | 推奨 |
| `productLine` | When a tool stops, ResiliMES rebuilds the shift so lots still meet their due times. | 机台宕机后，重排本班计划，让批次赶上交期。 | 装置が止まったとき、当直の計画を組み直して納期を守ります。 |
| `boardTitle` | Tool state | 装置状态 | 装置状態 |
| `states.idle` | Idle | 空闲 | 空き |
| `states.run` | Run | 加工 | 加工 |
| `states.setup` | Setup | 换型 | 段取り |
| `states.down` | Down | 宕机 | 停止 |
| `states.pm` | PM | 保养 | 保全 |
| `queueHead` | Bottleneck queue | 瓶颈排队 | ボトルネック待ち |
| `queueRunning` | {lot} running · done {time} | {lot} 加工中 · {time} 完工 | {lot} 加工中 · {time} 完了 |
| `queueNext` | Next {lot} · {time} | 下一道 {lot} · {time} | 次 {lot} · {time} |
| `queueCount` | {count} waiting | 等待 {count} | 待ち {count} |
| `queueBlocked` | {lot} cannot start · down until {time} | {lot} 不能开工 · 宕机至 {time} | {lot} は着工不可 · {time} まで停止 |
| `scoreCr` | CR | 临界比 | CR |
| `scoreSlack` | Slack | 松弛 | スラック |
| `scoreSetup` | Setup | 换型 | 段取り |
| `scoreQtime` | Q-time | 排队时限 | キュータイム |
| `scorePending` | The weighted score is not on this dispatcher yet. | 加权评分还没接到这台调度上。 | 加重スコアはまだこの差し立てにありません。 |
| `wipByStep` | WIP by step | 工序在制 | 工程別仕掛品 |
| `wipNone` | No pile-up limit on this plant yet. | 这条线还没有积压上限。 | このラインに滞留の上限はまだありません。 |
| `wipOver` | {step} {lots} lots · limit {limit} | {step} {lots} 批 · 上限 {limit} | {step} {lots}ロット · 上限 {limit} |
| `triggers.breakdown` | Tool down | 装置宕机 | 装置故障 |
| `triggers.hot_lot` | Hot lot | 急件 | 特急ロット |
| `triggers.wip_threshold` | WIP limit | 在制超限 | 仕掛上限 |
| `proposeMove` | Move to {tool} | 改到 {tool} | {tool} へ移す |
| `noAlternate` | No other qualified tool. | 没有其他合格装置。 | 他に資格のある装置はありません。 |
| `analyzeEmpty` | Run a reschedule first. The other numbers show up here. | 先重排一次，其余指标会出现在这里。 | 先に再スケジュールしてください。残りの指標はここに出ます。 |
| `verifyEmpty` | Run a reschedule first. Every constraint shows up here. | 先重排一次，每条约束的结果会出现在这里。 | 先に再スケジュールしてください。制約ごとの結果はここに出ます。 |
| `planTitle` | Current plan · {tool} down | 当前计划 · {tool} 宕机 | 現在の計画 · {tool} 停止 |
| `planTitleUp` | Current plan | 当前计划 | 現在の計画 |
| `badgeLive` | Nightshift | Nightshift | Nightshift |
| `modeDetailMock` | Local schedule · sample plant | 本地排程 · 示例产线 | ローカル計画 · サンプルライン |
| `modeDetailLive` | {model} · {data} | {model} · {data} | {model} · {data} |
| `modeTipMock` | The schedule and the checks run on this machine. Nightshift and Zetaris are not called. The plant is the sample. | 排程和校验在本机运行，不调用 Nightshift 和 Zetaris。数据是示例产线。 | 計画と検証はこの端末で動きます。Nightshift と Zetaris は呼びません。データはサンプルラインです。 |
| `modeTipLive` | Explanation: {model} through Nightshift. Data: {data}. | 说明由 Nightshift 上的 {model} 生成。数据来自{data}。 | 説明は Nightshift 上の {model} です。データは{data}です。 |
| `dataSample` | sample plant | 示例产线 | サンプルライン |
| `dataZetaris` | Zetaris | Zetaris | Zetaris |
| `sourceSample` | Sample plant | 示例产线 | サンプルライン |
| `sourceZetaris` | Zetaris | Zetaris | Zetaris |
| `tabRecoverTip` | The recovery for this shift | 本班怎么排 | 当直の計画 |
| `tabAnalyzeTip` | On-time delivery and the other numbers | 准时率和其余数字 | 納期とその他の数字 |
| `tabVerifyTip` | Every constraint on the plan | 这版计划的每条约束 | 計画が満たす制約 |
| `stepDetect` | Detect | 发现 | 検知 |
| `stepData` | Read data | 读数 | データ参照 |
| `stepPlan` | Plan | 排程 | 計画 |
| `stepCheck` | Check | 校验 | 判定 |
| `stepExplain` | Explain | 说明 | 説明 |
| `stepSave` | Save | 下发 | 確定 |
| `kpiWip` | WIP | 在制品 | 仕掛品 |
| `wipTip` | Lots on the plan for this shift. | 本班计划上的批次数。 | 当直の計画に載っているロット数です。 |
| `legendUp` | Running or idle | 加工或空闲 | 加工または空き |
| `legendDown` | Down | 宕机 | 停止 |
| `legendMaint` | Maintenance | 保养 | 保全 |
| `legendShort` | Short | 短缺 | 不足 |
| `runningLot` | {lot} · done {time} | {lot} · {time} 完工 | {lot} · {time} 完了 |
| `nextLot` | Next {lot} · {time} | 下一道 {lot} · {time} | 次 {lot} · {time} |
| `idleTool` | Idle | 空闲 | 空き |
| `downUntil` | Down until {time} | 宕机至 {time} | {time} まで停止 |
| `maintUntil` | Maintenance until {time} | 保养至 {time} | {time} まで保全 |
| `onHand` | {qty} {unit} | {qty} {unit} | {qty} {unit} |
| `impactOtd` | On-time {before} → {after} | 准时率 {before} → {after} | 納期遵守率 {before} → {after} |
| `impactTardy` | Tardiness {before} → {after} | 加权延误 {before} → {after} | 加重遅延 {before} → {after} |
| `impactScale` | Compare with EDD. On-time delivery stays level. | 与 EDD 对比。准时率持平。 | EDD と比較。納期遵守率は同水準です。 |
| `requestId` | request {id} | 请求 {id} | リクエスト {id} |
| `messages.unknown_tool` | {tool} is not in the plant. | 计划里出现了产线上没有的装置 {tool}。 | 計画に、ラインにない装置 {tool} があります。 |
| `messages.starts_before_up` | {lot} {step} starts on {tool} at {start}, before the tool is up at {up}. | {lot} 的 {step} 在 {start} 就排上 {tool}，但这台要到 {up} 才可用。 | {lot} の {step} は {start} に {tool} へ入っています。装置が使えるのは {up} からです。 |
| `messages.lacks_capability` | {tool} cannot run {step} for {lot}. It is not qualified for {capability}. | {tool} 不能加工 {lot} 的 {step}，没有 {capability} 资格。 | {tool} は {lot} の {step} を流せません。{capability} の資格がありません。 |
| `messages.overlap` | {tool} overlaps {lot_a} ({a_start}–{a_end}) and {lot_b} ({b_start}–{b_end}). | {tool} 上 {lot_a}（{a_start}–{a_end}）和 {lot_b}（{b_start}–{b_end}）时间重叠。 | {tool} で {lot_a}（{a_start}–{a_end}）と {lot_b}（{b_start}–{b_end}）が重なっています。 |
| `messages.wip_over` | {tool} has {count} lots at {at}. The limit is {max}. | {at} 时 {tool} 上有 {count} 个批次，上限是 {max}。 | {at} に {tool} へ {count} ロット載っています。上限は {max} です。 |
| `messages.operators_over` | Operators needed at {at}: {used}. The pool is {pool}. | {at} 需要 {used} 名人员，当班只有 {pool} 名。 | {at} に人員が {used} 人必要です。当直は {pool} 人です。 |
| `messages.material_short` | {lot} needs {qty} of {material}. On hand is {have}. | {lot} 需要 {material} {qty}，库存是 {have}。 | {lot} は {material} が {qty} 必要です。在庫は {have} です。 |
| `messages.precedence` | {lot} starts {step} before {prev} finishes. | {lot} 在 {prev} 完成前就开始了 {step}。 | {lot} は {prev} が終わる前に {step} を始めています。 |
| `messages.preemption_moved` | {lot} was moved off {tool} while it was running. | {lot} 还在 {tool} 上加工时被换走了。 | {lot} は {tool} で加工中なのに外されています。 |
| `messages.qtime_gap` | {from_step} ended at {anchor}. {lot} {to_step} starts at {start}, past the {limit} queue time. | {from_step} 于 {anchor} 结束。{lot} 的 {to_step} 在 {start} 才开工，超过 {limit} 的等待时限。 | {from_step} は {anchor} に終了。{lot} の {to_step} は {start} の着工で、キュータイム {limit} を超えています。 |
| `messages.rework_over` | {lot} has {total} rework passes. The limit is {limit}. | {lot} 已返工 {total} 次，上限是 {limit}。 | {lot} の再加工は {total} 回です。上限は {limit} です。 |
| `messages.rework_return` | {lot} rework enters {step}. The return step is {expected}. | {lot} 的返工进了 {step}，应回到 {expected}。 | {lot} の再加工が {step} に入っています。戻る工程は {expected} です。 |
| `messages.reticle_overlap` | Reticle {reticle} is on {tool_a} for {lot_a} ({a_start}–{a_end}) and on {tool_b} for {lot_b} ({b_start}–{b_end}). | 光罩 {reticle} 在 {a_start}–{a_end} 给 {tool_a} 上的 {lot_a} 用，又在 {b_start}–{b_end} 给 {tool_b} 上的 {lot_b} 用。 | レチクル {reticle} が {a_start}–{a_end} に {tool_a} の {lot_a}、{b_start}–{b_end} に {tool_b} の {lot_b} で使われています。 |
| `messages.inhibit_run` | {lot} cannot run {recipe} on {tool}. | {lot} 不能在 {tool} 上跑 {recipe}。 | {lot} は {tool} で {recipe} を流せません。 |
| `messages.release_early` | {lot} starts at {start}, before release at {release}. | {lot} 在 {start} 开工，早于放行时间 {release}。 | {lot} は {start} に着工しています。着手時刻は {release} です。 |
| `messages.release_block` | {lot} cannot start at {start}. Release is {release}. | {lot} 不能在 {start} 开工。放行时间是 {release}。 | {lot} は {start} に着工できません。着手時刻は {release} です。 |
| `messages.unknown_dest` | {tool} is not a tool in this plant. | {tool} 不是这厂的装置。 | {tool} はこのラインの装置ではありません。 |
| `messages.equipment_down` | {tool} is down until {until}. {lot} cannot start at {start}. | {tool} 宕机至 {until}。{lot} 不能在 {start} 开工。 | {tool} は {until} まで装置停止です。{lot} は {start} に着工できません。 |
| `messages.equipment_maint` | {tool} is in maintenance until {until}. {lot} cannot start at {start}. | {tool} 保养至 {until}。{lot} 不能在 {start} 开工。 | {tool} は {until} まで保全です。{lot} は {start} に着工できません。 |
| `messages.equipment_blocked_down` | {tool} is down. It cannot take {lot} now. | {tool} 宕机，现在不能接 {lot}。 | {tool} は停止中です。今は {lot} を受けられません。 |
| `messages.equipment_blocked_maint` | {tool} is in maintenance. It cannot take {lot} now. | {tool} 保养中，现在不能接 {lot}。 | {tool} は保全中です。今は {lot} を受けられません。 |
| `messages.qtime_block` | {from_step} ended at {anchor}. {lot} {step} cannot start at {start}. The limit is {limit}. | {from_step} 于 {anchor} 结束。{lot} 的 {step} 不能在 {start} 开工。时限是 {limit}。 | {from_step} は {anchor} に終了。{lot} の {step} は {start} に着工できません。制限は {limit} です。 |
| `messages.cannot_run` | {tool} cannot run {step}. It needs qualification {capability}. | {tool} 不能跑 {step}，需要 {capability} 资格。 | {tool} は {step} を流せません。必要な資格は {capability} です。 |
| `messages.already_running` | {lot} is already running on {tool}. | {lot} 正在 {tool} 上加工。 | {lot} は {tool} で加工中です。 |
| `messages.material_need` | {material} on hand is {have}. {lot} needs {qty}. | {material} 库存 {have}，{lot} 需要 {qty}。 | {material} の在庫は {have} です。{lot} は {qty} 必要です。 |
| `messages.reticle_busy` | Reticle {reticle} is on {tool} with {holder} until {until}. {lot} cannot start on {dest} at {start}. | 光罩 {reticle} 在 {tool} 上跟 {holder} 用到 {until}。{lot} 不能在 {start} 上 {dest}。 | レチクル {reticle} は {until} まで {tool} で {holder} が使用中です。{lot} は {start} に {dest} へ着工できません。 |
| `messages.rework_limit_action` | {lot} would pass the rework limit of {limit}. | {lot} 会超过返工上限 {limit} 次。 | {lot} は再加工の上限 {limit} 回を超えます。 |
| `messages.hold_pin` | The running step of {lot} could not stay on {tool}. | {lot} 正在加工的工序无法继续留在 {tool}。 | {lot} の加工中工程を {tool} に残せませんでした。 |
| `messages.hold_material` | {lot} is short of {material}. It needs {qty}; on hand is {have}. | {lot} 缺 {material}。需要 {qty}，库存 {have}。 | {lot} は {material} が不足です。必要 {qty}、在庫 {have}。 |
| `messages.hold_capability` | No tool is qualified for {step} ({capability}). | 没有装置具备 {step} 的资格（{capability}）。 | {step} の資格（{capability}）を持つ装置がありません。 |
| `messages.hold_qtime` | {from_step} ended at {anchor}. {lot} {step} must start by {latest}. | {from_step} 于 {anchor} 结束。{lot} 的 {step} 必须在 {latest} 前开工。 | {from_step} は {anchor} に終了。{lot} の {step} は {latest} までに着工が必要です。 |
| `messages.hold_slot` | No open slot for {lot} {step} on {tools}. | {lot} 的 {step} 在 {tools} 上没有可排的时段。 | {lot} の {step} は {tools} に空いている時間帯がありません。 |
| `messages.hold_tool` | No tool can take {lot} {step}. | 没有装置能接 {lot} 的 {step}。 | {lot} の {step} を受けられる装置がありません。 |
| `messages.rationale_hard` | A hard constraint failed. This plan cannot be released. | 有硬约束没过，这版计划不能下发。 | 制約違反があるため、この案は確定できません。 |
| `messages.rationale_conditional` | No hard constraint failed. Some lots are on hold. Review them before releasing the plan. | 硬约束都过了。有批次暂扣，下发前请看一眼。 | ハードな制約違反はありません。保留ロットがあるので、確定前に確認してください。 |
| `messages.rationale_accept` | The plan meets the constraints. | 这版计划满足约束。 | この計画は制約を満たしています。 |
| `brief.move_headline` | {lot} leaves {tool} | {lot} 调离 {tool} | {lot} を {tool} から外す |
| `brief.rush_headline` | {lot} finishes {late} late | {lot} 交期延误 {late} | {lot} は納期から {late}遅れ |
| `brief.queue_headline` | {lot} misses the clean queue time | {lot} 超过清洗后的等待时限 | {lot} は洗浄後のキュータイム超過 |
| `brief.scale_headline` | EDD dispatch already meets the dues | EDD 派工已满足交期 | EDD 差し立てで納期は守れている |
| `brief.named_headline` | {tool} is down for {span} | {tool} 宕机 {span} | {tool} は {span}停止 |
| `brief.named_headline_bare` | {tool} is down | {tool} 宕机 | {tool} は停止 |
| `intent.placeholder` | ETCH-02 down 30 min, notify Yamamoto-san, check inventory | ETCH-02 宕机 30 分钟，通知 Yamamoto-san，核对库存 | ETCH-02 が30分停止。通知 Yamamoto-san。在庫確認 |
| `intent.submit` | Parse | 解析 | 解析 |
| `intent.confirm` | Confirm | 确认执行 | 実行する |
| `intent.cancel` | Cancel | 取消 | 取り消す |
| `intent.call` | Tool call | 解析出的指令 | 解析した指令 |
| `intent.signature` | Scout signature | Scout 签名 | Scout 署名 |
| `intent.noContract` | No signature. These ids are not in this plant. | 没有签名。这些编号不在本产线。 | 署名はありません。このラインにない番号です。 |
| `intent.fallback` | Local parser. This text is not from the model. | 本地解析。这段文字不是模型原文。 | ローカル解析です。モデルの原文ではありません。 |
| `intent.degraded` | The note did not match the result, so the local sentence stays. | 说明与结果不符，已改用本地句子。 | 結果と合わないため、ローカルの文に戻しました。 |
| `intent.notify` | {name} · recorded, not sent | {name} · 已记录，未发送 | {name} · 記録のみ、未送信 |
| `intent.suggestions` | Suggestions do not change the schedule. | 建议不改变排程。 | 提案は計画を変えません。 |
| `intent.safety` | Safety test | 安全测试 | 安全テスト |
| `intent.safetyNote` | The refused plan is a safety test. It does not change the schedule. | 被拒方案是安全测试，不改变排程。 | 拒否した案は安全テストです。計画は変わりません。 |
| `intent.rounds` | Repair rounds | 修复轮次 | 修正ラウンド |
| `intent.checkInventory` | Check stock | 核对库存 | 在庫確認 |
| `intent.notifyPe` | Notify | 通知 | 連絡 |
| `intent.yes` | Yes | 是 | あり |
| `intent.no` | No | 否 | なし |
| `intent.unknownLot` | Unknown lot {id}. | 未知批次 {id}。 | 不明なロット {id}。 |
| `intent.unknownTool` | Unknown equipment {id}. | 未知装置 {id}。 | 不明な装置 {id}。 |
| `intent.injection` | Prompt injection detected. | 检测到提示注入。 | プロンプト注入を検知しました。 |
| `intent.runningHold` | Cannot hold {lot}: it is running on {tool}. | 不能暂扣 {lot}：正在 {tool} 上加工。 | {lot} は {tool} で加工中のため保留できません。 |
| `intent.leaveRunning` | Leave the running lot in place and reschedule queued work. | 加工中的批次留在原装置，只重排排队的批次。 | 加工中ロットは装置に残し、待ちロットだけ再計画します。 |
| `intent.affected` | Affected lots | 影响批次 | 影響ロット |
| `intent.none` | none | 无 | なし |
| `intent.committed` | Written to the plan | 已写入计划 | 計画に反映 |
| `intent.simulated` | Trial only. The plan is unchanged. | 仅试算，计划未改。 | 試算のみ。計画は未更新。 |
| `intent.notWritten` | Not written. The plan is unchanged. | 未写入。计划未改。 | 未反映。計画はそのままです。 |
| `intent.status.pending_confirmation` | Pending confirmation | 待确认 | 確認待ち |
| `intent.status.rejected` | Rejected | 已拒绝 | 不採用 |
| `intent.status.executed` | Executed | 已执行 | 実行済み |
| `intent.status.aborted` | Aborted | 已中止 | 中止 |
| `intent.names.insert_hot_lot` | Hot lot | 急件 | 特急ロット |
| `intent.names.move_pm` | Move PM | 调整保养 | 保全の移動 |
| `intent.names.mark_tool_down` | Tool down | 装置宕机 | 装置停止 |
| `intent.names.hold_lot` | Hold lot | 暂扣批次 | ロット保留 |
| `intent.names.release_lot` | Release lot | 解除暂扣 | 保留解除 |
| `intent.names.what_if` | What-if | 假设 | 想定 |
| `intent.roles.process_equipment` | Process equipment | 工艺设备 | プロセス・装置 |
| `intent.roles.production_control` | Production control | 生产管理 | 生産管理 |
| `intent.roles.risk` | Risk | 风险 | リスク |
| `intent.review.approve` | Approve | 同意 | 承認 |
| `intent.review.approve-with-changes` | Approve with changes | 附带修改后同意 | 条件付き承認 |
| `intent.review.reject` | Reject | 拒绝 | 却下 |
| `intent.agreement.unanimous` | Unanimous | 一致 | 全員一致 |
| `intent.agreement.majority` | Majority | 多数 | 多数 |
| `intent.agreement.split` | Split | 分歧 | 分かれ |
| `intent.params.lot_id` | Lot | 批次 | ロット |
| `intent.params.equipment_id` | Tool | 装置 | 装置 |
| `intent.params.eta_min` | Repair | 修复 | 復旧 |
| `intent.params.reason` | Reason | 原因 | 理由 |
| `intent.params.target_station_group` | Station group | 设备组 | 装置群 |
| `intent.params.priority_override` | Priority override | 提高优先级 | 優先度変更 |
| `intent.params.fault_code` | Fault | 故障码 | 故障コード |
| `intent.params.new_start_min` | Start | 开始 | 開始 |
| `intent.params.duration_min` | Duration | 时长 | 時間 |
| `intent.params.question` | Question | 问题 | 質問 |
| `intent.concernDown` | {id} is down or in maintenance. | {id} 宕机或保养中。 | {id} は停止または保全中です。 |
| `intent.concernHeld` | {id} is held. | {id} 被暂扣。 | {id} は保留中です。 |
| `intent.suggestHold` | Review the hold on {id} before the book is published. | 发布前复核 {id} 的暂扣。 | 公開前に {id} の保留を確認してください。 |
| `shiftLead.title` | AI shift lead · study run | AI班长 · 实验运行 | AI当直 · 検証の実行 |
| `shiftLead.runs` | Runs | 轮次 | ラン |
| `shiftLead.sim` | Sim time | 仿真时间 | シミュレーション時刻 |
| `shiftLead.exceptions` | Exceptions | 异常 | 異常 |
| `shiftLead.calls` | AI calls | AI 调用 | AI 呼び出し |
| `shiftLead.accepted` | Accepted | 已采纳 | 採用 |
| `shiftLead.fallback` | Rule fallback | 规则兜底 | ルールで代替 |
| `shiftLead.timeout` | timeout | 超时 | タイムアウト |
| `shiftLead.invalid` | invalid reply | 回复无效 | 無効な応答 |
| `shiftLead.guardrail` | guardrail | 护栏拦截 | ガードレール |
| `shiftLead.budget` | over budget | 超出预算 | 予算超過 |
| `shiftLead.error` | error | 错误 | エラー |
| `shiftLead.latency` | LLM latency avg / last | 模型延迟 平均 / 最近 | モデル応答 平均 / 直近 |
| `shiftLead.waiting` | waiting for the model | 等待模型回复 | モデルの応答待ち |
| `shiftLead.elapsed` | Elapsed | 已用时 | 経過 |
| `shiftLead.eta` | ETA | 预计剩余 | 残り目安 |
| `shiftLead.running` | Running | 运行中 | 実行中 |
| `shiftLead.done` | Done | 已完成 | 完了 |
| `shiftLead.failed` | Failed | 失败 | 失敗 |
| `shiftLead.stale` | No update for over a minute | 超过 1 分钟未更新 | 1分以上更新なし |
| `tabAi` | AI evidence | AI 证据 | AI エビデンス |
| `tabAiTip` | Investigator, late-lot explainer and shift handover; advice only | 根因调查、迟交批次解释与交班报告；仅供参考 | 原因調査・遅延ロット説明・シフト引き継ぎ（助言のみ） |
| `ai.intro` | Answers are written by the model from simulator evidence. Every number is checked against the tool results; nothing here changes the plan. | 回答由模型根据仿真证据撰写。每个数字都与工具结果核对；这里不会改动计划。 | 回答はシミュレーションの証拠からモデルが書きます。数字はすべてツール結果と照合し、計画は変更しません。 |
| `ai.mock` | offline stand-in | 离线替身 | オフライン代替 |
| `ai.live` | Nemotron | Nemotron | Nemotron |
| `ai.factOk` | Fact check passed: every number and ID comes from a tool result. | 事实核对通过：每个数字和编号都来自工具结果。 | 事実確認に合格：数字と ID はすべてツール結果に由来します。 |
| `ai.factFlag` | Not found in any tool result: | 以下内容在工具结果中找不到： | ツール結果に見つからない値： |
| `ai.working` | Working… | 处理中… | 処理中… |
| `ai.invTitle` | Investigator | 根因调查 | 原因調査 |
| `ai.invHelp` | Pick an injected-fault case. The investigator re-runs it, gathers evidence in at most 6 calls and names one cause. | 选择一个注入故障的案例。调查器会重跑仿真，最多调用 6 次工具收集证据，并给出一个原因。 | 故障を注入したケースを選びます。調査役はシミュレーションを再実行し、最大 6 回の呼び出しで証拠を集め、原因を 1 つ挙げます。 |
| `ai.invRun` | Investigate | 开始调查 | 調査する |
| `ai.cause` | Primary cause | 主要原因 | 主因 |
| `ai.second` | second | 次要 | 次点 |
| `ai.lever` | Suggested lever | 建议措施 | 推奨アクション |
| `ai.adviceOnly` | advice only, not applied | 仅为建议，未执行 | 助言のみ・未適用 |
| `ai.calls` | Evidence calls | 证据调用 | 証拠の呼び出し |
| `ai.truth` | Injected fault | 注入的故障 | 注入した故障 |
| `ai.baseline` | Biggest-anomaly baseline | 最大异常基线 | 最大異常ベースライン |
| `ai.causes.tool_down` | tool down | 机台宕机 | 装置ダウン |
| `ai.causes.pm_in_peak` | PM in the arrival peak | 到货高峰期间做 PM | 到着ピーク中の PM |
| `ai.causes.release_burst` | release burst | 集中投料 | 投入の集中 |
| `ai.causes.setup_thrash` | setup thrash | 频繁换线 | 段取り替えの多発 |
| `ai.causes.batch_cap` | batch size cap | 批量上限 | バッチサイズ上限 |
| `ai.causes.upstream_starvation` | upstream starvation | 上游断料 | 上流からの供給切れ |
| `ai.expTitle` | Late-lot explainer | 迟交批次解释 | 遅延ロットの説明 |
| `ai.expHelp` | Pick a late lot from the 48 h run. Its lateness is split into exact parts; the model explains it and proposes one change, which is checked by re-running the simulation. | 从 48 小时仿真中选择一个迟交批次。迟交时间被精确拆分；模型给出解释并提出一项改动，再通过重跑仿真来验证。 | 48 時間シミュレーションから遅延ロットを選びます。遅延時間を正確に内訳し、モデルが説明と変更案を 1 つ示し、シミュレーションの再実行で検証します。 |
| `ai.expRun` | Explain | 解释 | 説明する |
| `ai.lateBy` | late by | 迟交 | 遅延 |
| `ai.sumOk` | The parts add up exactly to the lateness. | 各部分之和与迟交时间完全一致。 | 内訳の合計は遅延時間と完全に一致します。 |
| `ai.sumBad` | The parts do not add up to the lateness. | 各部分之和与迟交时间不一致。 | 内訳の合計が遅延時間と一致しません。 |
| `ai.cfTitle` | What-if | 假设分析 | もしも分析 |
| `ai.cfExpected` | expected saving | 预计节省 | 想定短縮 |
| `ai.cfActual` | re-run saving | 重跑后节省 | 再実行での短縮 |
| `ai.cfHit` | confirmed | 已证实 | 確認済み |
| `ai.cfMiss` | not confirmed | 未证实 | 未確認 |
| `ai.buckets.processing` | processing | 加工 | 処理 |
| `ai.buckets.setup` | setup | 换线 | 段取り |
| `ai.buckets.transport` | transport | 搬送 | 搬送 |
| `ai.buckets.down` | tool down | 机台宕机 | 装置ダウン |
| `ai.buckets.pm` | PM | PM | PM |
| `ai.buckets.batch_wait` | waiting for a batch | 等待凑批 | バッチ待ち |
| `ai.buckets.lots_ahead` | lots ahead | 前方排队批次 | 先行ロット |
| `ai.buckets.qtime` | Q-time | Q-time | Q-time |
| `ai.buckets.ai_decision` | AI decision | AI 决策 | AI の判断 |
| `ai.buckets.dispatch_other` | other dispatch | 其他派工原因 | その他の払い出し要因 |
| `ai.buckets.release_hold` | release hold | 投料保留 | 投入保留 |
| `ai.buckets.late_at_snapshot` | already late at the start | 开始时已迟交 | 開始時点で遅延 |
| `ai.levers.prioritise` | make it the hot lot | 设为急件 | 特急ロットにする |
| `ai.levers.clear_down` | no tool down while it waits | 等待期间机台不宕机 | 待ち中に装置ダウンなし |
| `ai.levers.skip_pm` | defer PM while it waits | 等待期间推迟 PM | 待ち中の PM を延期 |
| `ai.hoTitle` | Shift handover report | 交接班报告 | シフト引き継ぎレポート |
| `ai.hoHelp` | A 12 h shift summarised in 2 h chunks: top issues, WIP bubbles, at-risk lots, tools down with repair ETA, next-shift PM and overrides with their outcome. Every number is checked against the run. | 将 12 小时班次按 2 小时分段汇总：主要问题、WIP 堆积、有延误风险的批次、停机设备及预计修复时间、下一班 PM，以及被让行的批次及其结果。所有数字均与仿真结果核对。 | 12 時間のシフトを 2 時間ごとに要約します：主な問題、WIP 滞留、遅延リスクのあるロット、ダウン中の装置と復旧見込み、次シフトの PM、後回しにされたロットとその結果。すべての数値はシミュレーション結果と照合します。 |
| `ai.hoRun` | Write handover | 生成交接报告 | 引き継ぎを作成 |
| `ai.hoShift` | Shift | 班次 | シフト |
| `ai.hoEngine` | Engine | 引擎 | エンジン |
| `ai.hoChunks` | Chunks | 分段 | チャンク |
| `ai.hoRecall` | Must-mention recall | 必提项召回率 | 必須項目の再現率 |

## AI shift lead study progress (new, needs zh/ja review)

The `shiftLead.*` keys label the study progress card in the console rail
(`GET /api/shift-lead/status`, fed by `<out>.progress.json`). zh follows
"AI班长" from docs/AI_SHIFT_LEAD.md; ja uses "当直" for the shift. The fallback
causes (`timeout`, `invalid`, `guardrail`, `budget`, `error`) are the reasons the
shift lead fell back to the rules.

## zh / ja strings for owner review

After the merge of main into this branch, these SMT2020 strings live in `resilimes/demo/static/i18n.json`. They replace the six-lot bay rows above for `scenarios.litho_down`, `scenarios.qtime`, `chartBefore.litho_down`, `chartBefore.qtime`, `chartAfter.litho_down` and `chartAfter.qtime`.


PR #14 (`cursor/first-impression-8a58`) also edits `resilimes/demo/static/app.js`. The strings below are the only zh/ja copy changed on this branch for the SMT2020 scenario list. English is included so the meaning is fixed. Please correct the wording. Do not treat these lines as approved.

Scenario buttons prefer `copy.scenarios` over the API text. These two ids were still the six-lot bay (LITHO-02, LOT-1001, 15-minute film). They now name the SMT2020 incidents. Other scenario ids in that object were not edited.

### zh

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

### ja

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

### en (not for translation review)

| Key | New string |
| --- | --- |
| `scenarios.litho_down` | Lithography breakdown / Litho_FE_92-1 is down for the published 705.59 min lithography repair. Snapshot 2018-01-01. |
| `scenarios.qtime` | Queue time / Published SMT2020 CQT. The look-ahead is the adjacent 1-hour dry etch to wet etch pairs, not a 15-minute film step. |
| `chartBefore.litho_down` | EDD on this seed |
| `chartAfter.litho_down` | ResiliMES on this seed |
| `chartBefore.qtime` | FIFO |
| `chartAfter.qtime` | ResiliMES, published CQT |

The scenario clock shows `2018-01-01 00:00` when `health.fab` is `smt2020`. That is a clock value, not a translated sentence. The API now returns that snapshot as `horizon`. The page no longer overwrites it in JavaScript.

### Round 2 — queue-time button

The previous qtime sentence described a dry-etch look-ahead that the code no longer runs. On the SMT console the button uses the API summary. The copy below is the fallback and must match that summary. Please correct the wording. Do not treat these lines as approved.

#### zh

| Key | New string |
| --- | --- |
| `scenarios.qtime[0]` | 队列时间 |
| `scenarios.qtime[1]` | 已发表的 CQT。ResiliMES 增加 PED 风险和湿法刻蚀闸门。该闸门在已存储的种子上触发 0 次。FIFO 不使用该闸门。 |

Previous round-2 zh body: SMT2020 已发表的 CQT。前瞻是相邻的 1 小时干法刻蚀到湿法刻蚀，不是 15 分钟成膜。

#### ja

| Key | New string |
| --- | --- |
| `scenarios.qtime[0]` | 待ち時間 |
| `scenarios.qtime[1]` | 公開された CQT。ResiliMES は PED リスクとウェットエッチのゲートを加える。そのゲートは保存済みシードで 0 回だった。FIFO はそのゲートを使わない。 |

Previous round-2 ja body: SMT2020 の公開 CQT。見通しは隣接する 1 時間のドライエッチからウェットエッチで、15 分の成膜ではない。

#### en (not for translation review)

| Key | New string |
| --- | --- |
| `scenarios.qtime` | Queue time / Published CQT limits. ResiliMES adds PED risk and a Wet_Etch gate. That gate fired 0 times on the stored seeds. FIFO does not use the gate. |

### fab-logic-r1 — operation logic (note only, no string edited)

This branch changes SMT2020 batching, breakdown rework, metrology sampling, and ResiliMES dispatch order. No zh or ja string was edited. The strings below were checked against the new numbers and logic:

| Key | Status |
| --- | --- |
| `scenarios.qtime[1]` | Still correct. The Wet_Etch gate fired 0 times on every stored seed in the regenerated `benchmark.json`. |
| `scenarios.litho_down[1]` | Still correct. The 705.59 min repair is the published MTTR, unchanged. |
| `scenarios.rush_order[1]` | Still correct for the six-lot sample bay it describes ("Running lots stay on their tools"). On the SMT2020 console a lot in process on a tool that breaks now goes to rework and redoes the step on another tool; the rush-order button does not break a tool, so the sentence is not contradicted. Review if this copy is ever reused for a breakdown. |
| `impactScale`, `scenarios.scale[*]`, `taglineScale` | Scale preset only (1,000 lots, 36 tools). Not touched by this branch. |

The SMT2020 scenario summaries and incident text whose numbers changed (tight VIP, X-factor, published dues) are English-only strings in `resilimes/smt/scenarios.py`, served by the API. They are not in `i18n.json` and need no zh/ja change. If the console later shows batch-wait reasons, rework holds, or skipped metrology steps, those will need new keys and a translation round.

### qtime-urgent — Q-time-urgent override and lot transport (note only, no string edited)

This branch adds a Q-time-urgent override to ResiliMES dispatch and a fixed 1/3-minute lot transport to every SMT2020 policy. No zh or ja string was edited. `app.js` and `i18n.json` were searched for the numbers that changed (433/435, 99.54%, 159/280, 163/280, 28/105, 19/105, 388.8, 436.8) and for transport wording; none appear in zh or ja copy.

| Key | Status |
| --- | --- |
| `scenarios.qtime[1]` | Still correct. The Wet_Etch gate fired 0 times on every stored seed in the regenerated `benchmark.json`. The string does not mention the new override; if the console should describe it, that needs a new sentence and a translation round. |
| `scenarios.litho_down[1]` | Still correct. The 705.59 min repair is unchanged, and the 12 h click is still a 2/19 tie. |

The numbers that changed (tight VIP, X-factor, published dues) are English-only strings in `resilimes/smt/scenarios.py`, served by the API, and are updated there. If the console later shows the override count, the override reason, or transport time, those will need new keys and a translation round.
