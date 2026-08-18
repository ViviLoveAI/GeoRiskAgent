"""End-to-end orchestration for CAR exposure validation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.validation.car_calculator import MarketModelConfig
from src.validation.car_report import build_validation_report, terminal_summary
from src.validation.prediction_snapshot import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SNAPSHOT_DIR,
    SNAPSHOT_VERSION_V2,
    create_full_pipeline_prediction_snapshot,
    load_accepted_validation_events,
    save_prediction_snapshot,
    snapshot_file_path,
)
from src.validation.price_preparation import (
    baseline_exposures_by_event_id,
    collect_required_symbols_from_snapshots,
    prepare_price_csvs,
)
from src.validation.run_car_validation import DEFAULT_RESULT_DIR, run_car_validation


DEFAULT_PRICE_DIR = Path("data/prices")


def run_full_car_validation(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    result_dir: str | Path = DEFAULT_RESULT_DIR,
    benchmark_symbol: str = "SPY",
    config: MarketModelConfig | None = None,
) -> dict[str, Any]:
    """Run snapshot freeze, price preparation, CAR validation, and reporting."""

    config = config or MarketModelConfig()
    result_path = Path(result_dir)
    result_path.mkdir(parents=True, exist_ok=True)
    run_timestamp = datetime.now(timezone.utc).isoformat()

    snapshots = load_or_create_frozen_snapshots(manifest_path, snapshot_dir)
    baselines_by_event = baseline_exposures_by_event_id(manifest_path)
    symbols = collect_required_symbols_from_snapshots(
        snapshots=snapshots,
        baseline_exposures_by_event_id=baselines_by_event,
        benchmark_symbol=benchmark_symbol,
    )
    event_dates = [str(snapshot.get("event_date")) for snapshot in snapshots]
    price_report = prepare_price_csvs(
        symbols=symbols,
        event_dates=event_dates,
        price_dir=price_dir,
        config=config,
    )

    summary = run_car_validation(
        manifest_path=manifest_path,
        snapshot_dir=snapshot_dir,
        result_dir=result_dir,
        price_dir=price_dir,
        benchmark_symbol=benchmark_symbol,
        config=config,
    )

    config_payload = {
        "benchmark_symbol": benchmark_symbol,
        "estimation_window": [
            config.estimation_window_start,
            config.estimation_window_end,
        ],
        "event_window": [
            config.event_window_start,
            config.event_window_end,
        ],
        "significance_threshold": config.significance_threshold,
        "run_timestamp": run_timestamp,
        "event_ids": [str(snapshot.get("event_id")) for snapshot in snapshots],
        "manifest_path": str(manifest_path),
        "snapshot_dir": str(snapshot_dir),
        "price_dir": str(price_dir),
        "result_dir": str(result_dir),
        "formal_evaluation_mode": "csv_first_offline_after_price_preparation",
    }
    _write_json(result_path / "car_run_config.json", config_payload)
    _write_json(result_path / "price_preparation_report.json", price_report)
    report_path = build_validation_report(
        result_path,
        config=config_payload,
        price_preparation=price_report,
    )
    return {
        "summary": summary,
        "price_preparation": price_report,
        "config": config_payload,
        "report_path": str(report_path),
        "terminal_summary": terminal_summary(result_path),
    }


def load_or_create_frozen_snapshots(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
) -> list[dict[str, Any]]:
    """Load existing accepted-event snapshots, creating only missing snapshots."""

    snapshots: list[dict[str, Any]] = []
    snapshot_path = Path(snapshot_dir)
    for event in load_accepted_validation_events(manifest_path):
        path = snapshot_file_path(snapshot_path, event.event_id, SNAPSHOT_VERSION_V2)
        if path.exists():
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
            continue
        snapshot = create_full_pipeline_prediction_snapshot(event)
        save_prediction_snapshot(snapshot, snapshot_dir)
        snapshots.append(snapshot)
    return snapshots


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for full CAR validation."""

    parser = argparse.ArgumentParser(
        description="Run full CSV-first CAR exposure validation with price preparation.",
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR))
    parser.add_argument("--price-dir", default=str(DEFAULT_PRICE_DIR))
    parser.add_argument("--result-dir", default=str(DEFAULT_RESULT_DIR))
    parser.add_argument("--benchmark-symbol", default="SPY")
    parser.add_argument("--estimation-window-start", type=int, default=-130)
    parser.add_argument("--estimation-window-end", type=int, default=-10)
    parser.add_argument("--event-window-start", type=int, default=-1)
    parser.add_argument("--event-window-end", type=int, default=1)
    parser.add_argument("--significance-threshold", type=float, default=1.96)
    return parser.parse_args()


def main() -> None:
    """Run the full CAR validation workflow and print a concise summary."""

    args = parse_args()
    config = MarketModelConfig(
        estimation_window_start=args.estimation_window_start,
        estimation_window_end=args.estimation_window_end,
        event_window_start=args.event_window_start,
        event_window_end=args.event_window_end,
        significance_threshold=args.significance_threshold,
    )
    result = run_full_car_validation(
        manifest_path=args.manifest,
        snapshot_dir=args.snapshot_dir,
        price_dir=args.price_dir,
        result_dir=args.result_dir,
        benchmark_symbol=args.benchmark_symbol,
        config=config,
    )
    print(result["terminal_summary"])


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
