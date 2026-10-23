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
| `verified` | contract verified | 合约已核对 | 契約を確認 |
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
| `status.MAINTENANCE` | Maintenance | 保养 | 保全 |
| `status.ok` | In stock | 有库存 | 在庫あり |
| `status.short` | Short | 短缺 | 不足 |
| `areas.Lithography` | Lithography | 光刻 | 露光 |
| `areas.Etch` | Etch | 刻蚀 | エッチング |
| `areas.CMP` | CMP | CMP | CMP |
| `areas.Deposition` | Deposition | 成膜 | 成膜 |
| `areas.Metrology` | Metrology | 量测 | 測定 |
| `areas.Clean` | Clean | 清洗 | 洗浄 |
| `scenarios.litho_down.0` | Litho down | 光刻机宕机 | 露光装置停止 |
| `scenarios.litho_down.1` | LITHO-02 is down for 10 h. LOT-1001 is on that tool. | LITHO-02 宕机 10 小时，LOT-1001 排在这台。 | LITHO-02 が10時間停止。LOT-1001 が載っています。 |
| `scenarios.rush_order.0` | Rush lot | 急单 | 特急ロット |
| `scenarios.rush_order.1` | A hot lot is due in 3 h. Running lots stay on their tools. | 急单 3 小时内交货。正在加工的批次不撤下。 | 特急の納期は3時間。加工中ロットは装置に残します。 |
| `scenarios.material_shortage.0` | Resist short | 光刻胶短缺 | レジスト不足 |
| `scenarios.material_shortage.1` | RESIST-UV is at zero. Lots that still need it wait. | RESIST-UV 库存为零，还要用的批次等待。 | RESIST-UV の在庫はゼロ。未使用ロットは待ちます。 |
| `scenarios.rework.0` | Overlay rework | 套刻返工 | 重ね合わせ再加工 |
| `scenarios.rework.1` | LOT-1004 failed overlay. Strip, expose, and measure once. | LOT-1004 套刻失败。去胶、再曝光、复测一次。 | LOT-1004 は重ね合わせ不良。剥離、再露光、再測定を1回。 |
| `scenarios.qtime.0` | Queue time | 等待时限 | キュータイム |
| `scenarios.qtime.1` | Clean is done. The next film must start within 15 min. | 清洗已结束。下一道成膜须在 15 分钟内开工。 | 洗浄は終了。次の成膜は15分以内に着工します。 |
| `scenarios.scale.0` | 1,000 lots | 1000 批次 | 1000ロット |
| `scenarios.scale.1` | 36 tools. One scanner is down for 10 h. Compare with EDD. | 36 台装置，一台光刻机宕机 10 小时。与 EDD 派工对比。 | 36台。スキャナー1台が10時間停止。EDD 差し立てと比較。 |
| `chartBefore.litho_down` | Wait for repair | 等待修复方案 | 復旧待ち案 |
| `chartBefore.rush_order` | Without the rush | 无急单 | 特急なし |
| `chartBefore.material_shortage` | Resist in stock | 光刻胶有库存 | レジスト在庫あり |
| `chartBefore.rework` | No rework | 无返工 | 再加工なし |
| `chartBefore.qtime` | 8 h limit | 8 小时时限 | 制限8時間 |
| `chartBefore.scale` | EDD dispatch | EDD 派工 | EDD 差し立て |
| `chartAfter.litho_down` | Reschedule | 重排方案 | 再スケジュール案 |
| `chartAfter.rush_order` | With the rush | 含急单 | 特急あり |
| `chartAfter.material_shortage` | Resist stockout | 光刻胶断料 | レジスト欠品 |
| `chartAfter.rework` | Strip and re-expose | 去胶再曝光 | 剥離して再露光 |
| `chartAfter.qtime` | 15 min limit | 15 分钟时限 | 制限15分 |
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
