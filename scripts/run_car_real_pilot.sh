#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=. python -m src.eval.car.yfinance_fetcher \
  --events data/eval/heldout_events_real.csv \
  --predicted-assets data/eval/predicted_assets_real.csv \
  --baseline-assets data/eval/baseline_assets_real.csv \
  --benchmark-symbol SPY \
  --prices-output data/eval/prices_real.csv \
  --benchmark-output data/eval/benchmark_prices_real.csv \
  --lookback-calendar-days 260 \
  --lookforward-calendar-days 10

PYTHONPATH=. python -m src.eval.car.car_evaluator \
  --events data/eval/heldout_events_real.csv \
  --predicted-assets data/eval/predicted_assets_real.csv \
  --prices data/eval/prices_real.csv \
  --benchmark-prices data/eval/benchmark_prices_real.csv \
  --baseline-assets data/eval/baseline_assets_real.csv \
  --benchmark-symbol SPY \
  --output data/eval/car_validation_report_real.csv
