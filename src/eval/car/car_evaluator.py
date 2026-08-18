"""CLI and orchestration for CSV-first CAR validation."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from src.eval.car.car_calculator import (
    calculate_car_for_event,
    compute_abnormal_returns,
    compute_daily_returns,
)
from src.eval.car.price_loader import load_csv, load_price_csv
from src.eval.car.report import print_summary
from src.eval.car.schemas import (
    BASELINE_ASSET_COLUMNS,
    HELDOUT_EVENT_COLUMNS,
    PREDICTED_ASSET_COLUMNS,
    PRICE_COLUMNS,
    REPORT_COLUMNS,
    CarWindowConfig,
)


def evaluate_car(
    events: pd.DataFrame,
    predicted_assets: pd.DataFrame,
    prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    benchmark_symbol: str,
    config: CarWindowConfig,
    baseline_assets: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Evaluate CAR for each held-out event and asset pair.

    This is an ex-post validation routine. It uses manually supplied CSV data
    and does not fetch prices, call APIs, or change the GeoRisk pipeline.
    Optional baseline assets are evaluated with the same CAR methodology for
    comparison against GeoRisk-flagged assets.
    """

    events_by_id = _events_by_id(events)
    benchmark_symbol = str(benchmark_symbol)
    benchmark_frame = benchmark_prices[benchmark_prices["symbol"] == benchmark_symbol]

    rows: list[dict[str, object]] = []
    asset_records = [
        *_georisk_records(predicted_assets),
        *_baseline_records(baseline_assets),
    ]
    for prediction in asset_records:
        event_id = str(prediction["event_id"])
        event = events_by_id.get(event_id)
        base_row = _base_report_row(event, prediction)

        if event is None:
            rows.append({**base_row, **_missing_fields("event_id_not_found")})
            continue
        if benchmark_frame.empty:
            rows.append({**base_row, **_missing_fields("missing_benchmark_prices")})
            continue

        symbol = str(prediction["symbol"])
        asset_frame = prices[prices["symbol"] == symbol]
        if asset_frame.empty:
            rows.append({**base_row, **_missing_fields("missing_asset_prices")})
            continue

        asset_returns = compute_daily_returns(asset_frame)
        benchmark_returns = compute_daily_returns(benchmark_frame)
        if benchmark_returns.empty:
            rows.append({**base_row, **_missing_fields("missing_benchmark_prices")})
            continue
        if asset_returns.empty:
            rows.append({**base_row, **_missing_fields("missing_asset_prices")})
            continue

        abnormal_returns = compute_abnormal_returns(asset_returns, benchmark_returns)
        if abnormal_returns.empty:
            rows.append({**base_row, **_missing_fields("no_overlapping_return_dates")})
            continue

        result = calculate_car_for_event(
            abnormal_returns,
            pd.Timestamp(event["event_date"]),
            config,
        )
        rows.append({**base_row, **result})

    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def run_from_csv(
    events_path: str | Path,
    predicted_assets_path: str | Path,
    prices_path: str | Path,
    benchmark_prices_path: str | Path,
    benchmark_symbol: str,
    output_path: str | Path,
    config: CarWindowConfig,
    baseline_assets_path: str | Path | None = None,
) -> pd.DataFrame:
    """Load CSV inputs, write CAR validation report, and print a summary."""

    events = load_csv(events_path, HELDOUT_EVENT_COLUMNS)
    predicted_assets = load_csv(predicted_assets_path, PREDICTED_ASSET_COLUMNS)
    prices = load_price_csv(prices_path, PRICE_COLUMNS)
    benchmark_prices = load_price_csv(benchmark_prices_path, PRICE_COLUMNS)
    events = events.copy()
    events["event_date"] = pd.to_datetime(events["event_date"])
    predicted_assets = predicted_assets.copy()
    predicted_assets["confidence"] = pd.to_numeric(
        predicted_assets["confidence"], errors="coerce"
    )
    baseline_assets = None
    if baseline_assets_path:
        baseline_assets = load_csv(baseline_assets_path, BASELINE_ASSET_COLUMNS)

    report = evaluate_car(
        events,
        predicted_assets,
        prices,
        benchmark_prices,
        benchmark_symbol,
        config,
        baseline_assets=baseline_assets,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False)
    print_summary(report)
    print(f"report_path: {output_path}")
    return report


def main() -> None:
    """Command-line entry point for CAR validation."""

    parser = argparse.ArgumentParser(
        description="Run CSV-first CAR validation for held-out GeoRisk events."
    )
    parser.add_argument("--events", default="data/eval/heldout_events.csv")
    parser.add_argument("--predicted-assets", default="data/eval/predicted_assets.csv")
    parser.add_argument("--prices", default="data/eval/prices.csv")
    parser.add_argument("--benchmark-prices", default="data/eval/benchmark_prices.csv")
    parser.add_argument(
        "--baseline-assets",
        default=None,
        help="Optional CSV of baseline event-symbol pairs for comparison.",
    )
    parser.add_argument("--benchmark-symbol", default="SPY")
    parser.add_argument("--output", default="data/eval/car_validation_report.csv")
    parser.add_argument("--event-window-start", type=int, default=-1)
    parser.add_argument("--event-window-end", type=int, default=1)
    parser.add_argument("--estimation-window-start", type=int, default=-130)
    parser.add_argument("--estimation-window-end", type=int, default=-10)
    parser.add_argument("--hit-threshold", type=float, default=1.96)
    args = parser.parse_args()

    config = CarWindowConfig(
        event_window_start=args.event_window_start,
        event_window_end=args.event_window_end,
        estimation_window_start=args.estimation_window_start,
        estimation_window_end=args.estimation_window_end,
        hit_threshold=args.hit_threshold,
    )
    run_from_csv(
        args.events,
        args.predicted_assets,
        args.prices,
        args.benchmark_prices,
        args.benchmark_symbol,
        args.output,
        config,
        baseline_assets_path=args.baseline_assets,
    )


def _georisk_records(predicted_assets: pd.DataFrame) -> list[dict[str, object]]:
    """Convert GeoRisk predictions into normalized evaluation records."""

    records: list[dict[str, object]] = []
    for row in predicted_assets.to_dict("records"):
        records.append(
            {
                "event_id": row.get("event_id", ""),
                "symbol": row.get("symbol", ""),
                "node": row.get("node", ""),
                "asset_type": row.get("asset_type", ""),
                "confidence": row.get("confidence", ""),
                "evidence_label": row.get("evidence_label", ""),
                "baseline_type": "",
                "group": "georisk_flagged",
            }
        )
    return records


def _baseline_records(baseline_assets: pd.DataFrame | None) -> list[dict[str, object]]:
    """Convert optional baseline assets into normalized evaluation records."""

    if baseline_assets is None:
        return []

    records: list[dict[str, object]] = []
    for row in baseline_assets.to_dict("records"):
        records.append(
            {
                "event_id": row.get("event_id", ""),
                "symbol": row.get("symbol", ""),
                "node": row.get("node", ""),
                "asset_type": row.get("asset_type", ""),
                "confidence": math.nan,
                "evidence_label": "",
                "baseline_type": row.get("baseline_type", ""),
                "group": "baseline",
            }
        )
    return records


def _events_by_id(events: pd.DataFrame) -> dict[str, dict[str, object]]:
    """Index event rows by event_id."""

    return {str(row["event_id"]): row for row in events.to_dict("records")}


def _base_report_row(
    event: dict[str, object] | None,
    prediction: dict[str, object],
) -> dict[str, object]:
    """Build report fields that do not depend on price data."""

    event_date = ""
    if event is not None:
        event_date = pd.Timestamp(event["event_date"]).date().isoformat()
    return {
        "event_id": prediction.get("event_id", ""),
        "event_date": event_date,
        "group": prediction.get("group", ""),
        "symbol": prediction.get("symbol", ""),
        "node": prediction.get("node", ""),
        "asset_type": prediction.get("asset_type", ""),
        "confidence": prediction.get("confidence", ""),
        "evidence_label": prediction.get("evidence_label", ""),
        "baseline_type": prediction.get("baseline_type", ""),
    }


def _missing_fields(reason: str) -> dict[str, object]:
    """Return empty report calculation fields with a missing-data reason."""

    return {
        "t0_date": "",
        "car": math.nan,
        "estimation_std_abnormal_return": math.nan,
        "standardized_car": math.nan,
        "hit": False,
        "direction": "",
        "missing_data_reason": reason,
    }


if __name__ == "__main__":
    main()
