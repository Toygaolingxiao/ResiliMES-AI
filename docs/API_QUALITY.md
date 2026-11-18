# /api/quality（quality-api/v0）

实现：`resilimes/api/quality.py`（路由）+ `resilimes/insight/quality_adapter.py`
的 `summarize()`（与 CLI 共用的自描述 summary）；契约测试：
`tests/test_api_quality.py`（7 件）；页面消费：
`resilimes/demo/static/product/quality/quality-report.js`
（`qualityLoadServer` / `qualityServerReport`）+ `docs/QUALITY_PAGE.md`。

## 这是什么

Quality 页的信任视图原来只能读用户手选的 QualityReport JSON 文件。
本端点把项目自己的首次实测接成 API：请求时实时用
`insight.quality_adapter.evaluate_file()` 对仓内已保存的故障注入
基准文件跑适配→评估，返回 quality/v0 报告。调用方拿到的报告，
就是适配器从该文件产出的样本列算出的报告；跳过情况随 `summary`
一起返回。

## 契约（quality-api/v0）

`GET /api/quality?variant=v2`（既定值；`v1` 可选）：

```json
{
  "api_version": "quality-api/v0",
  "variant": "v2",
  "source": "results_pc/investigator_nightshift_v2.json",
  "adapter_version": "adapter/v0",
  "metrics_version": "quality/v0",
  "report": { "metrics_version": "quality/v0", "total_samples": 24, "...": "..." },
  "summary": { "samples": 24, "skipped": {}, "system_answers_used": 0, "...": "..." }
}
```

- `variant`：`v1` / `v2`。`v1` 是旧 investigator（11/22），`v2`
  是当前 investigator（4/24）。未知 variant → **404**。
- `source`：仓内相对路径。页面把它显示在"已加载"行里，作为报告的
  出处；`report` 本身不带出处字段（quality/v0 的口径，见
  `docs/QUALITY_METRICS.md`）。
- `report`：`QualityReport`（quality/v0）的 `model_dump(mode="json")`。
  三项率的分母全在里面：误归因分母 = 已回答且真值已知的样本；
  过度不明分母 = 真值已知的全部样本；不明占比分母 = 全部样本。
  空样本列时三项率均为 `None`（分母 0：数据不足，不是 0.0）。
- `summary`：与 CLI `--report` / stdout 的 summary 是同一个对象
  （`quality_adapter.summarize()`）：adapter 版本、source、shape、
  样本数、skips、system 答案使用数、taxonomy 外计数、headline 率
  （分子/分母/值齐全）。只拿 summary 也能复原测了什么、跳过了什么。
- **无缓存、无存储报告**：两文件各 24 行，请求时重算的成本可忽略；
  缓存会多出"过期报告"的 stale 问题，本增量不引入。
- **只读**：不改排程、不改 KPI、不改基准文件。`POST /api/quality`
  → 405。

## 边界与失败

- 基准文件缺失、读不出、JSON 损坏、重复 `case_id`（适配器
  `ValueError`）→ **503**。文件是服务端数据、不是客户端输入，
  故用 5xx 而非 422；detail 截断到 300 字符（与仓内其他数据源
  处理一致）。
- 校验失败的报告永远不会被返回：`evaluate_file()` 只产出真实
  `QualityReport`；页面侧仍用同一校验器复核（`qualityServerReport`，
  node parity 覆盖），信封缺 `report` 或缺 `source` 时拒绝加载。
- 校准仍为空：investigator 不输出置信度（见 `docs/QUALITY_ADAPTER.md`），
  故 `calibration_samples=0`、`expected_calibration_error=None`。
  这是本体问题，不是端点问题。

## 首次实测（由测试固定，非手工数字）

- v2：误归因 **4/24**、过度不明 **0/24**；v1：误归因 **11/22**、
  过度不明 **2/24**；校准 0 / ECE None（两者皆然）。
  固定点：`tests/test_api_quality.py::test_default_variant_is_v2_first_measurement`
  与 `test_variant_v1_first_measurement`，以及
  `tests/test_explain_quality_adapter.py` 的复现测试。

## 非目标

- 不做新基准运行（不做 LLM 调用，只读已保存输出）；不接 study 侧
  自动跑基准（study 的 `--quality-report` 是后续提案）。
- 不做报告对比（多报告并排）、不做钻取到 lot/样本/Cases、不做
  持久化与历史报告（见 `docs/QUALITY_PAGE.md` 后续增量）。
- 不给报告加 run id / 时间戳 / 基准配置字段（quality/v0 的局限；
  对外举证仍须等 v0.x 或 v1，见 `docs/QUALITY_PAGE.md`）。
- 不改任何映射规则（adapter/v0）与任何度量口径（quality/v0）。
