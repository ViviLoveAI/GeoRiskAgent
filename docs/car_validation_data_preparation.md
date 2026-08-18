# CAR validation data preparation

本文档说明如何在手工准备数据后运行 GeoRisk 的 CAR validation workflow。这里的 validation 是 ex-post exposure validation：它检查 GeoRisk 标记的资产在事件窗口内是否出现 abnormal movement。它不是 price prediction，不是 investment advice，也不证明因果关系。

## Held-out validation event 是什么

`held-out validation event` 是用于验证的事件，不能参与 GeoRisk historical case knowledge base 的构建、调参或人工补强。它应该像一个考试题：先冻结 GeoRisk 的 `predicted_exposures`，再观察事件后的价格数据并计算 CAR。

如果事件已经出现在 `data/historical_cases.json`，或你在看到事件后价格表现之后才调整预测资产，那么 validation 会产生 look-ahead bias。

## 为什么不能和 KB 重叠

GeoRisk 的核心 pipeline 会从 `data/historical_cases.json` 检索 historical analogs。如果 validation event 本身或高度近似的同一事件已经在 KB 中，系统可能等于在验证时“看见了答案”。因此每个 validation event 都需要在 `validation_events.yaml` 里明确：

- `held_out_from_kb: true`
- `status: accepted`

在正式报告前，还应该人工检查 `data/historical_cases.json`，确认没有同一事件泄漏。

## 如何定义 clean t=0

`t=0` 是事件第一次可被市场系统性反映的交易日。好的 `t=0` 应该满足：

- 事件时间清楚，例如公告、袭击、制裁、政策发布有明确日期。
- 如果事件发生在周末或假日，CAR calculator 会对齐到下一个可用交易日。
- 不要选择已经被市场提前充分预期的日期，除非你的 validation design 明确就是验证预期阶段。

在 `validation_events.yaml` 中设置：

- `event_date`
- `clear_t0: true`

## 什么是 confounding events

`confounding events` 是在 estimation window 或 event window 附近发生、可能主导资产价格变化的其他重大事件。例如：

- 同一资产发生 earnings surprise、并购、破产、监管处罚。
- 同一行业发生另一个更大的政策冲击。
- 市场出现极端宏观事件，使单一 geopolitical event 难以分离。

如果 confounding 太强，应设置：

- `low_confounding: false`
- `status: draft` 或 `rejected`

只有通过 hard filters 的事件才会进入 validation。

## validation_events.yaml 必填字段

每个事件建议至少填写：

```yaml
validation_events:
  - event_id: placeholder_event_001
    event_date: "YYYY-MM-DD"
    event_description: "Fake placeholder event description."
    event_type: placeholder_event_type
    notes: "Explain why this event is held out and how t=0 was chosen."
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
    predicted_exposures:
      - event_id: placeholder_event_001
        symbol: FAKE
        node: placeholder_node
        asset_type: placeholder_asset
        confidence: 0.0
        evidence_label: placeholder_only
        expected_direction: positive
        source: manual_placeholder
```

字段说明：

- `event_id`: 稳定、唯一的事件 ID。
- `event_date`: 事件日期，格式为 `YYYY-MM-DD`。
- `event_description`: 事件描述。
- `event_type`: 可选，但建议填写，便于后续按事件类型汇总。
- `held_out_from_kb`: 必须为 `true` 才能通过 screening。
- `clear_t0`: 必须为 `true`。
- `clean_estimation_window`: 必须为 `true`。
- `low_confounding`: 必须为 `true`。
- `status`: 必须是 `accepted`。

## 如何定义 predicted_exposures

`predicted_exposures` 是在观察 post-event returns 之前冻结的 GeoRisk 输出。它可以先手工填写，也可以未来从 analyzer 导出。

每个 exposure 建议填写：

- `event_id`
- `symbol`
- `node`
- `asset_type`
- `confidence`
- `evidence_label`
- `expected_direction`
- `source`

`expected_direction` 仅作为诊断字段保留，不参与 hit-rate calculation。GeoRisk 验证的是 exposure，不是 price direction：

- hit 使用 `abs(standardized_car) >= 1.96`
- positive 和 negative abnormal movement 都可以算 hit
- signed `car` 和 `direction` 只用于解释结果

## 如何定义 baseline_assets

`baseline_assets` 是可选字段，用于和 GeoRisk flagged exposures 对比。它可以放在同一个 event 下：

```yaml
baseline_assets:
  - symbol: SPY
    node: broad_market
    asset_type: equity_etf
    baseline_type: broad_market_baseline
  - symbol: QQQ
    node: broad_market
    asset_type: equity_etf
    baseline_type: broad_market_baseline
```

当前 audit utility 会读取 `baseline_assets` 中的 `symbol`，用于检查价格 CSV 是否存在。

## 需要哪些 price CSV

每个 `predicted_exposures.symbol`、每个 `baseline_assets.symbol`，以及 benchmark symbol `SPY` 默认都需要一个本地 CSV：

```text
data/prices/{symbol}.csv
```

例如：

```text
data/prices/FAKE.csv
data/prices/SPY.csv
```

CSV 格式必须包含：

```csv
Date,Adj Close
2024-01-02,100.00
2024-01-03,101.25
```

也支持：

```csv
Date,Close
2024-01-02,100.00
2024-01-03,101.25
```

日期应覆盖 estimation window 和 event window。默认窗口是：

- estimation window: `[-130, -10]`
- event window: `[-1, +1]`

## 为什么当前 placeholder run 不是模型结果

当前 manifest 使用 fake placeholder event 和 symbol，例如 `FAKE`。如果没有 `data/prices/FAKE.csv`，runner 会输出：

```text
evaluated_pairs: 0
skipped_pairs: 1
skipped_reasons: {'missing_asset_prices': 1}
```

这只说明 pipeline 可以运行，并发现缺少价格文件。它不是 GeoRisk 的 validation performance。

## 如何解读 evaluated_pairs, skipped_pairs, hit_rate

- `evaluated_pairs`: 成功计算 CAR 并进入 hit-rate evaluation 的 event-symbol pairs 数量。
- `skipped_pairs`: 因缺价格、缺 benchmark、数据窗口不足、或无法计算 standardized CAR 等原因跳过的 pairs 数量。
- `hit_rate`: 在 evaluated pairs 中，magnitude-based hit 的比例。

如果 `evaluated_pairs` 是 0，任何 `hit_rate` 都没有意义。应先查看：

- `data/car_results/skipped_pairs.json`
- `data/car_results/missing_price_files.json`
- `data/car_results/input_audit.json`

## 输入审计命令

在运行 CAR 之前，先检查数据是否齐备：

```bash
PYTHONPATH=. python -m src.validation.audit_validation_inputs
```

它会生成：

```text
data/car_results/input_audit.json
```

并打印：

- accepted events count
- required symbols
- existing price files
- missing price files
- ready_to_run

只有 `ready_to_run: true` 时，才说明输入文件层面已经可以尝试运行：

```bash
PYTHONPATH=. python -m src.validation.run_car_validation
```
