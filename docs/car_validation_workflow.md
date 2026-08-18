# CAR Validation Workflow

This workflow describes the CSV-first cumulative abnormal return (CAR)
validation layer for GeoRisk. It is an ex-post evaluation process for exposure
predictions on held-out geopolitical events.

The module checks whether assets flagged by GeoRisk showed abnormal movement in
an event window. It does not predict prices, does not provide investment
advice, does not prove causality, and does not turn GeoRisk into a trading
system.

## What The Module Does

- Uses held-out geopolitical events.
- Evaluates GeoRisk-flagged event-symbol pairs.
- Optionally evaluates baseline event-symbol pairs.
- Computes market-adjusted abnormal returns from adjusted-close CSV files.
- Reports CAR, standardized CAR, hit/miss, direction, and missing-data reasons.

The useful validation question is whether GeoRisk-flagged assets show a higher
abnormal-movement hit rate than baseline assets.

## Build Held-Out Validation Set

First collect a larger candidate pool from public historical news records:

```bash
PYTHONPATH=. python scripts/collect_validation_candidates.py --target-candidates 30
```

The collector uses GDELT DOC records, writes raw cached retrieval payloads under
`data/validation_candidates/raw/`, deduplicates article coverage into
incident-level candidates, flags possible KB overlap, and writes
`data/validation_event_candidates.json`. It does not inspect prices, returns,
CAR, hit labels, or baseline performance.

Start from a structured candidate pool and screen it before any CAR outcome is
observed:

```bash
PYTHONPATH=. python scripts/build_validation_set.py --max-events 10
```

The builder reads `data/validation_event_candidates.json`, screens candidates
against `data/historical_cases.json` for incident-level KB overlap, generates
pre-outcome GeoRisk exposure predictions for eligible events, and writes
`data/validation_events.yaml`. If the manifest already contains accepted frozen
events, they are preserved unless `--rebuild` is passed.

Audit artifacts are written to `data/validation_selection/`:

- `candidate_screening.csv`
- `accepted_events.json`
- `rejected_events.json`
- `kb_overlap_report.json`
- `selection_metadata.json`

The selection stage does not inspect CAR, standardized CAR, returns, hit labels,
or GeoRisk-vs-baseline performance.

## Why Held-Out Events Matter

Validation events should not be part of `data/historical_cases.json`. If a
validation event is already in the retrieval knowledge base, the CAR validation
can leak information from the retrieval set into the evaluation set. The pilot
CSV notes include reminders to verify this before final reporting.

## Pilot CSVs

The repository includes initial real-data pilot scaffolding:

```text
data/eval/heldout_events_real.csv
data/eval/predicted_assets_real.csv
data/eval/baseline_assets_real.csv
```

`predicted_assets_real.csv` is a pilot placeholder using liquid ETFs and
large-cap names. It should eventually be replaced by actual GeoRisk output
exported from the analyzer for each held-out event.

Templates are available in:

```text
data/eval/templates/
```

## CSV Contracts

Held-out events:

```text
event_id,event_date,event_description,notes
```

GeoRisk predictions:

```text
event_id,symbol,node,asset_type,confidence,evidence_label
```

Baseline assets:

```text
event_id,symbol,node,asset_type,baseline_type
```

Asset prices:

```text
date,symbol,adj_close
```

Benchmark prices:

```text
date,symbol,adj_close
```

`prices_real.csv` should include all GeoRisk and baseline symbols.
`benchmark_prices_real.csv` should include the benchmark symbol, usually `SPY`.

## Run GeoRisk On Held-Out Events

For each event in `heldout_events_real.csv`, run the GeoRisk analyzer and export
the secondary watchlist rows into `predicted_assets_real.csv`.

Example:

```bash
PYTHONPATH=. python -m src.pipeline \
  --news "Russia launches a full-scale invasion of Ukraine, raising concerns about energy supply, grain exports, sanctions, and defense spending." \
  --format json \
  --event-analyzer rule
```

For the initial pilot, `predicted_assets_real.csv` is manually seeded. Treat it
as a placeholder, not as final validation evidence.

## Prepare Price Data

The CAR evaluator is CSV-first. You can either manually provide:

```text
data/eval/prices_real.csv
data/eval/benchmark_prices_real.csv
```

or optionally use the yfinance helper below.

Manual files must use long format:

```text
date,symbol,adj_close
2022-02-23,XLE,68.12
2022-02-24,XLE,70.45
```

If the event date is not a trading day, the evaluator uses the next available
trading date as `t=0`.

## Optional yfinance Fetcher

The yfinance adapter is optional. The CAR evaluator still works without it when
you provide CSV price files manually.

Install only if you want to fetch pilot prices:

```bash
pip install yfinance
```

Fetch adjusted-close CSVs:

```bash
PYTHONPATH=. python -m src.eval.car.yfinance_fetcher \
  --events data/eval/heldout_events_real.csv \
  --predicted-assets data/eval/predicted_assets_real.csv \
  --baseline-assets data/eval/baseline_assets_real.csv \
  --benchmark-symbol SPY \
  --prices-output data/eval/prices_real.csv \
  --benchmark-output data/eval/benchmark_prices_real.csv \
  --lookback-calendar-days 260 \
  --lookforward-calendar-days 10
```

If yfinance is not installed, the fetcher prints:

```text
yfinance is not installed. Install it with: pip install yfinance
```

If internet access or vendor data fails, manually provide the two price CSVs in
the required long format.

## Run CAR Evaluator

For the snapshot-based validation workflow, use the one-command runner:

```bash
PYTHONPATH=. python scripts/run_full_car_validation.py
```

This command freezes missing snapshots, prepares local `data/prices/{symbol}.csv`
files with yfinance when needed, runs the CSV-first market-model CAR validator,
and writes `data/car_results/` artifacts. Existing frozen snapshots are reused
and are not silently regenerated.

```bash
PYTHONPATH=. python -m src.eval.car.car_evaluator \
  --events data/eval/heldout_events_real.csv \
  --predicted-assets data/eval/predicted_assets_real.csv \
  --prices data/eval/prices_real.csv \
  --benchmark-prices data/eval/benchmark_prices_real.csv \
  --baseline-assets data/eval/baseline_assets_real.csv \
  --benchmark-symbol SPY \
  --output data/eval/car_validation_report_real.csv
```

## CAR Logic

The evaluator uses simple daily returns:

```text
asset_return_t = adj_close_t / adj_close_t-1 - 1
benchmark_return_t = benchmark_adj_close_t / benchmark_adj_close_t-1 - 1
abnormal_return_t = asset_return_t - benchmark_return_t
CAR = sum abnormal_return_t over the event window
standardized_car = CAR / (estimation_window_abnormal_return_std * sqrt(N))
hit = abs(standardized_car) >= threshold
```

Default windows:

- Event window: `[-1, +1]` trading days around `t=0`
- Estimation window: `[-130, -10]` trading days before `t=0`
- Hit threshold: `abs(standardized_car) >= 1.96`

Because GeoRisk predicts exposure rather than direction, hit detection uses
absolute abnormal movement. Direction is reported for context only.

## Interpret The Report

The report includes:

```text
event_id,event_date,t0_date,group,symbol,node,asset_type,confidence,evidence_label,baseline_type,car,estimation_std_abnormal_return,standardized_car,hit,direction,missing_data_reason
```

Key fields:

- `group`: `georisk_flagged` or `baseline`
- `car`: cumulative market-adjusted abnormal return
- `estimation_std_abnormal_return`: estimation-window abnormal-return standard
  deviation
- `standardized_car`: CAR divided by the event-window CAR standard deviation,
  estimated as abnormal-return standard deviation times `sqrt(N)`
- `hit`: true when absolute standardized CAR meets the threshold
- `direction`: positive, negative, or neutral; not used for hit detection
- `missing_data_reason`: explains skipped pairs

Example interpretation:

> GeoRisk-flagged assets showed a higher abnormal-movement hit rate than
> baseline assets in the held-out pilot. This suggests the analyzer may identify
> assets with meaningful exposure to geopolitical shocks, but the result is
> preliminary and not causal.

## Compare GeoRisk Against Baseline

Use the console summary and report CSV to compare:

- `georisk_flagged_hit_rate`
- `baseline_hit_rate`
- hit rate by GeoRisk `evidence_label`
- hit rate by GeoRisk node
- hit rate by baseline node
- hit rate by `baseline_type`

## Limitations

- The pilot sample is small.
- Market moves can be confounded by unrelated macro, earnings, rates, or sector
  news.
- ETF composition changes can affect interpretation.
- Different data vendors may produce different adjusted-close histories.
- Event-date choice can be ambiguous, especially for weekend or multi-day
  geopolitical events.
- yfinance reliability varies and should not be treated as a production data
  platform.
- Abnormal movement does not imply the geopolitical event caused the move.

CAR validation is one diagnostic. It should be combined with qualitative case
review, baseline design checks, and sensitivity analysis over event windows and
benchmark choices.
