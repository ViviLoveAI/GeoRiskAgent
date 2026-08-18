"""CLI runner for ex-post CAR exposure validation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.validation.car_calculator import MarketModelConfig, calculate_market_model_car
from src.validation.exposure_evaluator import (
    evaluate_exposure_results,
    split_evaluated_and_skipped,
)
from src.validation.prediction_snapshot import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SNAPSHOT_DIR,
    SNAPSHOT_VERSION_V2,
    create_full_pipeline_prediction_snapshot,
    load_accepted_validation_events,
    save_prediction_snapshot,
    snapshot_file_path,
)


DEFAULT_RESULT_DIR = Path("data/car_results")
PAIR_RESULT_COLUMNS = [
    "event_id",
    "event_date",
    "event_type",
    "symbol",
    "node",
    "asset_type",
    "linkage_tier",
    "linkage_rationale",
    "source",
    "transmission_order",
    "confidence",
    "evidence_label",
    "supporting_case_ids",
    "supporting_case_details",
    "evidence_reason",
    "relevance_score",
    "priority_tier",
    "rank_within_order",
    "ranking_version",
    "ranking_scope",
    "ranking_key",
    "supporting_case_count",
    "ranking_components",
    "ranking_rationale",
    "baseline_type",
    "expected_direction",
    "car",
    "standardized_car",
    "direction",
    "hit",
    "missing_data_reason",
    "t0_date",
    "alpha",
    "beta",
]


def run_car_validation(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    result_dir: str | Path = DEFAULT_RESULT_DIR,
    price_dir: str | Path = "data/prices",
    benchmark_symbol: str = "SPY",
    config: MarketModelConfig | None = None,
) -> dict[str, Any]:
    """Run snapshot-based CAR validation and save result artifacts."""

    config = config or MarketModelConfig()
    result_path = Path(result_dir)
    result_path.mkdir(parents=True, exist_ok=True)

    snapshots = _load_or_create_snapshots(manifest_path, snapshot_dir)
    baseline_exposures_by_event_id = _baseline_exposures_by_event_id(manifest_path)
    pair_results = _calculate_pair_results(
        snapshots=snapshots,
        price_dir=price_dir,
        benchmark_symbol=benchmark_symbol,
        config=config,
        baseline_exposures_by_event_id=baseline_exposures_by_event_id,
    )
    evaluated_rows, skipped_rows = split_evaluated_and_skipped(pair_results)
    summary = evaluate_exposure_results(pair_results)
    summary["events_evaluated"] = len(snapshots)
    summary["total_evaluated_pairs"] = summary["evaluated_pairs"]
    missing_price_files = build_missing_price_files_report(skipped_rows)

    _write_pair_results(result_path / "car_pair_results.csv", evaluated_rows + skipped_rows)
    _write_json(result_path / "car_summary.json", summary)
    _write_json(result_path / "skipped_pairs.json", skipped_rows)
    _write_json(result_path / "missing_price_files.json", missing_price_files)
    return summary


def main() -> None:
    """Command-line entry point."""

    parser = argparse.ArgumentParser(
        description="Run ex-post CAR exposure validation from frozen snapshots."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR))
    parser.add_argument("--result-dir", default=str(DEFAULT_RESULT_DIR))
    parser.add_argument("--price-dir", default="data/prices")
    parser.add_argument("--benchmark-symbol", default="SPY")
    parser.add_argument("--estimation-window-start", type=int, default=-130)
    parser.add_argument("--estimation-window-end", type=int, default=-10)
    parser.add_argument("--event-window-start", type=int, default=-1)
    parser.add_argument("--event-window-end", type=int, default=1)
    parser.add_argument("--significance-threshold", type=float, default=1.96)
    args = parser.parse_args()

    config = MarketModelConfig(
        estimation_window_start=args.estimation_window_start,
        estimation_window_end=args.estimation_window_end,
        event_window_start=args.event_window_start,
        event_window_end=args.event_window_end,
        significance_threshold=args.significance_threshold,
    )
    summary = run_car_validation(
        manifest_path=args.manifest,
        snapshot_dir=args.snapshot_dir,
        result_dir=args.result_dir,
        price_dir=args.price_dir,
        benchmark_symbol=args.benchmark_symbol,
        config=config,
    )

    print("CAR validation complete.")
    print("Scope: ex-post exposure validation only; no price prediction or investment advice.")
    print(f"events_evaluated: {summary['events_evaluated']}")
    print(f"total_evaluated_pairs: {summary['total_evaluated_pairs']}")
    print(f"skipped_pairs: {summary['skipped_pairs']}")
    print(f"skipped_reasons: {summary['skipped_reasons']}")
    print(f"overall_hit_rate: {_format_rate(summary['overall_hit_rate'])}")
    print(f"georisk_flagged_hit_rate: {_format_rate(summary['georisk_flagged_hit_rate'])}")
    if summary["baseline_hit_rate"] is not None:
        print(f"baseline_hit_rate: {_format_rate(summary['baseline_hit_rate'])}")
    missing_price_files = build_missing_price_files_report(
        _read_json_list(Path(args.result_dir) / "skipped_pairs.json")
    )
    if missing_price_files["unique_missing_files"]:
        print("Missing price files:")
        for path in missing_price_files["unique_missing_files"]:
            print(f"- {path}")
    print(f"result_dir: {args.result_dir}")


def build_missing_price_files_report(skipped_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize missing asset and benchmark price CSVs from skipped pairs."""

    asset_files = [
        row["expected_csv_path"]
        for row in skipped_rows
        if row.get("missing_data_reason") == "missing_asset_prices"
        and row.get("expected_csv_path")
    ]
    benchmark_files = [
        row["expected_benchmark_csv_path"]
        for row in skipped_rows
        if row.get("missing_data_reason") == "missing_benchmark_prices"
        and row.get("expected_benchmark_csv_path")
    ]
    return {
        "missing_asset_price_files": sorted(set(asset_files)),
        "missing_benchmark_price_files": sorted(set(benchmark_files)),
        "unique_missing_files": sorted(set(asset_files + benchmark_files)),
    }


def _load_or_create_snapshots(
    manifest_path: str | Path,
    snapshot_dir: str | Path,
) -> list[dict[str, Any]]:
    """Load existing snapshots, creating them for accepted events when needed."""

    snapshots: list[dict[str, Any]] = []
    for event in load_accepted_validation_events(manifest_path):
        snapshot_path = snapshot_file_path(
            snapshot_dir,
            event.event_id,
            SNAPSHOT_VERSION_V2,
        )
        if snapshot_path.exists():
            snapshots.append(json.loads(snapshot_path.read_text(encoding="utf-8")))
            continue

        snapshot = create_full_pipeline_prediction_snapshot(event)
        save_prediction_snapshot(snapshot, snapshot_dir)
        snapshots.append(snapshot)
    return snapshots


def _calculate_pair_results(
    snapshots: list[dict[str, Any]],
    price_dir: str | Path,
    benchmark_symbol: str,
    config: MarketModelConfig,
    baseline_exposures_by_event_id: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Calculate CAR for every exposure in every snapshot."""

    baseline_exposures_by_event_id = baseline_exposures_by_event_id or {}
    pair_results: list[dict[str, Any]] = []
    for snapshot in snapshots:
        exposures = list(snapshot.get("predicted_exposures", []))
        baseline_exposures = snapshot.get("baseline_exposures")
        if baseline_exposures is None:
            baseline_exposures = baseline_exposures_by_event_id.get(
                snapshot["event_id"],
                [],
            )
        exposures.extend(
            {
                **baseline,
                "event_id": snapshot["event_id"],
                "source": "baseline",
                "confidence": None,
                "evidence_label": None,
            }
            for baseline in baseline_exposures
        )
        for exposure in exposures:
            result = calculate_market_model_car(
                event_id=snapshot["event_id"],
                symbol=exposure["symbol"],
                benchmark_symbol=benchmark_symbol,
                event_date=snapshot["event_date"],
                price_dir=price_dir,
                config=config,
            )
            pair_results.append(
                {
                    **result,
                    "event_date": snapshot["event_date"],
                    "event_type": snapshot.get("event_type"),
                    "node": exposure.get("node"),
                    "asset_type": exposure.get("asset_type"),
                    "linkage_tier": exposure.get("linkage_tier"),
                    "linkage_rationale": exposure.get("linkage_rationale"),
                    "source": exposure.get("source", "georisk"),
                    "transmission_order": exposure.get("transmission_order"),
                    "confidence": exposure.get("confidence"),
                    "evidence_label": exposure.get("evidence_label"),
                    "supporting_case_ids": ";".join(exposure.get("supporting_case_ids", [])),
                    "supporting_case_details": json.dumps(
                        exposure.get("supporting_case_details", []),
                        sort_keys=True,
                    ),
                    "evidence_reason": exposure.get("evidence_reason"),
                    "relevance_score": exposure.get("relevance_score"),
                    "priority_tier": exposure.get("priority_tier"),
                    "rank_within_order": exposure.get("rank_within_order"),
                    "ranking_version": exposure.get("ranking_version"),
                    "ranking_scope": exposure.get("ranking_scope"),
                    "ranking_key": json.dumps(
                        exposure.get("ranking_key"),
                        sort_keys=True,
                    ),
                    "supporting_case_count": exposure.get("supporting_case_count"),
                    "ranking_components": json.dumps(
                        exposure.get("ranking_components", {}),
                        sort_keys=True,
                    ),
                    "ranking_rationale": exposure.get("ranking_rationale"),
                    "baseline_type": exposure.get("baseline_type"),
                    "expected_direction": exposure.get("expected_direction"),
                }
            )
    return pair_results


def _baseline_exposures_by_event_id(
    manifest_path: str | Path,
) -> dict[str, list[dict[str, Any]]]:
    """Return accepted-event baselines from the manifest keyed by event ID."""

    baselines: dict[str, list[dict[str, Any]]] = {}
    for event in load_accepted_validation_events(manifest_path):
        baselines[event.event_id] = [
            baseline.model_dump(mode="json")
            for baseline in event.baseline_assets
        ]
    return baselines


def _write_pair_results(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write pair-level CAR and magnitude-based hit results."""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_RESULT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON output with stable formatting."""

    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    """Read a JSON list from disk, returning an empty list when unavailable."""

    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy-like values into JSON-safe Python objects."""

    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return str(value)
    return value


def _format_rate(value: float | None) -> str:
    """Format optional hit-rate values for terminal output."""

    if value is None:
        return "n/a"
    return f"{value:.2f}"


if __name__ == "__main__":
    main()
