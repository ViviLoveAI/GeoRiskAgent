"""Run formal CAR validation for the frozen V3 experiment.

This script is execution-only for the already frozen V3 design. It does not
modify events, snapshots, GeoRisk pipeline logic, linkage labels, evidence
labels, confidence scores, or CAR methodology.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd

from src.validation.car_calculator import (
    MarketModelConfig,
    align_asset_and_benchmark_returns,
    align_event_date_to_next_trading_day,
    calculate_market_model_car,
    load_price_series,
)
from src.validation.exposure_evaluator import evaluate_exposure_results, split_evaluated_and_skipped
from src.validation.price_preparation import collect_required_symbols_from_snapshots, prepare_price_csvs
from src.validation.run_car_validation import PAIR_RESULT_COLUMNS, build_missing_price_files_report


DEFAULT_V3_DIR = Path("data/validation_v3")
DEFAULT_MANIFEST_PATH = DEFAULT_V3_DIR / "v3_manifest.json"
DEFAULT_SNAPSHOT_DIR = DEFAULT_V3_DIR / "prediction_snapshots"
DEFAULT_RESULT_DIR = Path("data/car_results_v3")
DEFAULT_PRICE_DIR = Path("data/prices")
EXPECTED_MANIFEST_HASH = "d67ae3db74eb150acf94d41985f28a04f4bd97a5837597a3800384110ebf2010"


def run_v3_car_validation(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    result_dir: str | Path = DEFAULT_RESULT_DIR,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    benchmark_symbol: str = "SPY",
    config: MarketModelConfig | None = None,
) -> dict[str, Any]:
    """Prepare prices and run CAR for frozen V3 snapshots."""

    config = config or MarketModelConfig()
    result_path = Path(result_dir)
    result_path.mkdir(parents=True, exist_ok=True)
    run_timestamp = datetime.now(timezone.utc).isoformat()

    manifest = load_v3_manifest(manifest_path)
    manifest_hash_before = sha256_file(manifest_path)
    snapshots = load_v3_snapshots(manifest, snapshot_dir)
    snapshot_hashes_before = {snapshot["_path"]: sha256_file(snapshot["_path"]) for snapshot in snapshots}
    integrity_before = v3_integrity(manifest, snapshots, manifest_hash_before)
    if integrity_before["errors"]:
        raise RuntimeError(f"V3 integrity failed before CAR: {integrity_before['errors']}")

    symbols = collect_required_symbols_from_snapshots(
        snapshots=snapshots,
        baseline_exposures_by_event_id={},
        benchmark_symbol=benchmark_symbol,
    )
    event_dates = [str(snapshot["event_date"]) for snapshot in snapshots]
    price_report = prepare_price_csvs(
        symbols=symbols,
        event_dates=event_dates,
        price_dir=price_dir,
        config=config,
    )
    coverage_rows = build_price_coverage_rows(
        symbols=symbols,
        snapshots=snapshots,
        price_dir=price_dir,
        benchmark_symbol=benchmark_symbol,
        config=config,
        price_report=price_report,
    )

    pair_results = calculate_v3_pair_results(snapshots, price_dir, benchmark_symbol, config)
    evaluated_rows, skipped_rows = split_evaluated_and_skipped(pair_results)
    summary = evaluate_exposure_results(pair_results)
    summary["events_evaluated"] = len(snapshots)
    summary["total_pairs"] = len(pair_results)
    summary["total_evaluated_pairs"] = len(evaluated_rows)
    summary["accounting_valid"] = len(pair_results) == len(evaluated_rows) + len(skipped_rows)
    summary["missing_price_files"] = build_missing_price_files_report(skipped_rows)
    summary["overall_metrics"] = overall_metrics(evaluated_rows)
    summary["georisk_minus_baseline_hit_rate"] = hit_rate_difference(evaluated_rows)
    summary["v3_integrity"] = {
        **integrity_before,
        "manifest_hash_after": sha256_file(manifest_path),
        "snapshot_hashes_after": {snapshot["_path"]: sha256_file(snapshot["_path"]) for snapshot in snapshots},
    }
    summary["v3_integrity"]["manifest_unchanged"] = (
        summary["v3_integrity"]["manifest_hash_after"] == manifest_hash_before
    )
    summary["v3_integrity"]["snapshots_unchanged"] = (
        summary["v3_integrity"]["snapshot_hashes_after"] == snapshot_hashes_before
    )
    summary["run_config"] = {
        "run_timestamp": run_timestamp,
        "benchmark_symbol": benchmark_symbol,
        "estimation_window": [config.estimation_window_start, config.estimation_window_end],
        "event_window": [config.event_window_start, config.event_window_end],
        "significance_threshold": config.significance_threshold,
        "significance_rule": "abs(standardized_car) >= 1.96",
        "market_model": "asset_return = alpha + beta * benchmark_return",
        "manifest_path": str(manifest_path),
        "snapshot_dir": str(snapshot_dir),
        "price_dir": str(price_dir),
        "result_dir": str(result_dir),
    }

    write_pair_results(result_path / "car_pair_results.csv", evaluated_rows + skipped_rows)
    write_json(result_path / "car_summary.json", summary)
    write_json(result_path / "skipped_pairs.json", skipped_rows)
    write_json(result_path / "missing_price_files.json", summary["missing_price_files"])
    write_csv(result_path / "price_coverage_report.csv", coverage_rows)

    write_csv(result_path / "linkage_analysis.csv", grouped_metric_rows(evaluated_rows, {"source": "georisk", "transmission_order": "second_order"}, ["linkage_tier"]))
    write_csv(result_path / "linkage_sector_proxy_analysis.csv", grouped_metric_rows(evaluated_rows, {"source": "georisk", "transmission_order": "second_order", "evidence_label": "sector_proxy"}, ["linkage_tier"]))
    write_csv(result_path / "evidence_analysis.csv", grouped_metric_rows(evaluated_rows, {"source": "georisk", "transmission_order": "second_order"}, ["evidence_label"]))
    write_csv(result_path / "linkage_evidence_crosstab.csv", grouped_metric_rows(evaluated_rows, {"source": "georisk", "transmission_order": "second_order"}, ["linkage_tier", "evidence_label"]))
    write_csv(result_path / "transmission_order_analysis.csv", grouped_metric_rows(evaluated_rows, {"source": "georisk"}, ["transmission_order"]))
    write_csv(result_path / "event_level_analysis.csv", event_level_rows(evaluated_rows, snapshots))
    write_json(result_path / "price_preparation_report.json", price_report)
    write_markdown_report(result_path / "v3_car_report.md", summary)
    return summary


def load_v3_manifest(path: str | Path) -> dict[str, Any]:
    """Load V3 manifest JSON."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_v3_snapshots(manifest: dict[str, Any], snapshot_dir: str | Path) -> list[dict[str, Any]]:
    """Load the frozen V3 snapshots listed by the V3 manifest."""

    snapshots: list[dict[str, Any]] = []
    for event_id in manifest.get("event_ids", []):
        path = Path(snapshot_dir) / f"{event_id}_snapshot_v3.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["_path"] = str(path)
        snapshots.append(payload)
    return snapshots


def calculate_v3_pair_results(
    snapshots: list[dict[str, Any]],
    price_dir: str | Path,
    benchmark_symbol: str,
    config: MarketModelConfig,
) -> list[dict[str, Any]]:
    """Calculate CAR rows from frozen V3 snapshots."""

    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        exposures = list(snapshot.get("predicted_exposures", []))
        exposures.extend(
            {
                **baseline,
                "event_id": snapshot["event_id"],
                "source": "baseline",
                "confidence": None,
                "evidence_label": None,
                "linkage_tier": None,
                "linkage_rationale": None,
                "transmission_order": None,
            }
            for baseline in snapshot.get("baseline_exposures", [])
        )
        for exposure in exposures:
            car = calculate_market_model_car(
                event_id=snapshot["event_id"],
                symbol=exposure["symbol"],
                benchmark_symbol=benchmark_symbol,
                event_date=snapshot["event_date"],
                price_dir=price_dir,
                config=config,
            )
            rows.append(
                {
                    **car,
                    "event_date": snapshot["event_date"],
                    "event_headline": snapshot.get("headline"),
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
    return rows


def build_price_coverage_rows(
    symbols: list[str],
    snapshots: list[dict[str, Any]],
    price_dir: str | Path,
    benchmark_symbol: str,
    config: MarketModelConfig,
    price_report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Summarize local CSV coverage for each required V3 symbol."""

    events_by_symbol: dict[str, set[str]] = defaultdict(set)
    event_dates_by_symbol: dict[str, list[str]] = defaultdict(list)
    for snapshot in snapshots:
        event_symbols = {e.get("symbol") for e in snapshot.get("predicted_exposures", [])}
        event_symbols.update(b.get("symbol") for b in snapshot.get("baseline_exposures", []))
        event_symbols.add(benchmark_symbol)
        for symbol in event_symbols:
            if symbol:
                normalized = str(symbol).upper()
                events_by_symbol[normalized].add(snapshot["event_id"])
                event_dates_by_symbol[normalized].append(snapshot["event_date"])

    downloaded = set(price_report.get("downloaded_symbols", []))
    reused = set(price_report.get("reused_symbols", []))
    failures = {item.get("symbol"): item.get("reason") for item in price_report.get("failed_symbols", [])}
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        prices, error = load_price_series(symbol, price_dir=price_dir)
        if prices is None or prices.empty:
            rows.append(
                {
                    "symbol": symbol,
                    "earliest_date": "",
                    "latest_date": "",
                    "row_count": 0,
                    "price_source": "yfinance_csv" if symbol in downloaded else "local_csv",
                    "download_status": failures.get(symbol) or error or "missing",
                    "all_event_windows_covered": False,
                    "all_estimation_windows_sufficient": False,
                    "event_ids": ";".join(sorted(events_by_symbol[symbol])),
                }
            )
            continue
        coverage = [
            coverage_for_event(symbol, event_date, prices, price_dir, benchmark_symbol, config)
            for event_date in event_dates_by_symbol[symbol]
        ]
        rows.append(
            {
                "symbol": symbol,
                "earliest_date": prices["date"].min().date().isoformat(),
                "latest_date": prices["date"].max().date().isoformat(),
                "row_count": len(prices),
                "price_source": "yfinance_csv" if symbol in downloaded else "local_csv",
                "download_status": "downloaded" if symbol in downloaded else "reused" if symbol in reused else failures.get(symbol, "available"),
                "all_event_windows_covered": all(item["event_window_covered"] for item in coverage),
                "all_estimation_windows_sufficient": all(item["estimation_window_sufficient"] for item in coverage),
                "event_ids": ";".join(sorted(events_by_symbol[symbol])),
            }
        )
    return rows


def coverage_for_event(
    symbol: str,
    event_date: str,
    asset_prices: pd.DataFrame,
    price_dir: str | Path,
    benchmark_symbol: str,
    config: MarketModelConfig,
) -> dict[str, bool]:
    """Check estimation and event-window availability without using CAR output."""

    benchmark_prices, _ = load_price_series(benchmark_symbol, price_dir=price_dir)
    if benchmark_prices is None or benchmark_prices.empty:
        return {"event_window_covered": False, "estimation_window_sufficient": False}
    returns = align_asset_and_benchmark_returns(asset_prices, benchmark_prices)
    if returns.empty:
        return {"event_window_covered": False, "estimation_window_sufficient": False}
    event_timestamp = pd.to_datetime(event_date, errors="coerce")
    if pd.isna(event_timestamp):
        return {"event_window_covered": False, "estimation_window_sufficient": False}
    t0 = align_event_date_to_next_trading_day(returns["date"], pd.Timestamp(event_timestamp))
    if t0 is None:
        return {"event_window_covered": False, "estimation_window_sufficient": False}
    matches = returns.index[returns["date"] == t0].tolist()
    if not matches:
        return {"event_window_covered": False, "estimation_window_sufficient": False}
    idx = matches[0]
    return {
        "estimation_window_sufficient": idx + config.estimation_window_start >= 0
        and idx + config.estimation_window_end < len(returns),
        "event_window_covered": idx + config.event_window_start >= 0
        and idx + config.event_window_end < len(returns),
    }


def v3_integrity(manifest: dict[str, Any], snapshots: list[dict[str, Any]], manifest_hash: str) -> dict[str, Any]:
    """Run frozen V3 integrity checks."""

    errors: list[str] = []
    embedded_manifest_hash = manifest.get("manifest_hash")
    if embedded_manifest_hash != EXPECTED_MANIFEST_HASH:
        errors.append(f"manifest_hash_changed:{embedded_manifest_hash}")
    manifest_ids = list(manifest.get("event_ids", []))
    snapshot_ids = [snapshot.get("event_id") for snapshot in snapshots]
    if manifest_ids != snapshot_ids:
        errors.append("snapshot_event_ids_do_not_match_manifest_order")
    if len(snapshot_ids) != 12:
        errors.append(f"unexpected_event_count:{len(snapshot_ids)}")
    exposures = [e for snapshot in snapshots for e in snapshot.get("predicted_exposures", [])]
    keys = Counter((e.get("event_id"), e.get("symbol"), e.get("node")) for e in exposures)
    duplicates = [key for key, count in keys.items() if count > 1]
    if duplicates:
        errors.append(f"duplicate_event_symbol_node:{duplicates[:5]}")
    for snapshot in snapshots:
        if snapshot.get("snapshot_version") != "v3_full_pipeline_linkage_ontology":
            errors.append(f"non_v3_snapshot:{snapshot.get('event_id')}")
        if snapshot.get("pipeline_mode") != "full_georisk_pipeline":
            errors.append(f"non_full_pipeline_snapshot:{snapshot.get('event_id')}")
        for exposure in snapshot.get("predicted_exposures", []):
            if not exposure.get("linkage_tier"):
                errors.append(f"missing_linkage_tier:{snapshot.get('event_id')}:{exposure.get('symbol')}:{exposure.get('node')}")
            if not exposure.get("linkage_rationale"):
                errors.append(f"missing_linkage_rationale:{snapshot.get('event_id')}:{exposure.get('symbol')}:{exposure.get('node')}")
            if exposure.get("evidence_label") not in {"historical_supported", "sector_proxy", "inference_only"}:
                errors.append(f"invalid_evidence_label:{snapshot.get('event_id')}:{exposure.get('symbol')}")
    return {
        "errors": errors,
        "manifest_file_sha256_before": manifest_hash,
        "embedded_manifest_hash": embedded_manifest_hash,
        "event_ids": snapshot_ids,
        "total_georisk_exposures": len(exposures),
        "duplicate_event_symbol_node_count": len(duplicates),
    }


def overall_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return GeoRisk and baseline aggregate metrics."""

    return {
        "georisk": metric_row([r for r in rows if r.get("source") == "georisk"]),
        "baseline": metric_row([r for r in rows if r.get("source") == "baseline"]),
    }


def grouped_metric_rows(
    rows: list[dict[str, Any]],
    filters: dict[str, str],
    group_fields: list[str],
) -> list[dict[str, Any]]:
    """Aggregate evaluated rows after exact metadata filters."""

    filtered = [
        row for row in rows
        if all(str(row.get(field) or "") == value for field, value in filters.items())
    ]
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in filtered:
        grouped[tuple(str(row.get(field) or "unknown") for field in group_fields)].append(row)
    output: list[dict[str, Any]] = []
    for key in sorted(grouped):
        values = dict(zip(group_fields, key, strict=True))
        output.append({**values, **metric_row(grouped[key])})
    return output


def event_level_rows(rows: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate first/second-order results at event level."""

    headline_by_event = {snapshot["event_id"]: snapshot.get("headline", "") for snapshot in snapshots}
    date_by_event = {snapshot["event_id"]: snapshot.get("event_date", "") for snapshot in snapshots}
    output: list[dict[str, Any]] = []
    for event_id in sorted(headline_by_event):
        event_rows = [r for r in rows if r.get("source") == "georisk" and r.get("event_id") == event_id]
        first = [r for r in event_rows if r.get("transmission_order") == "first_order"]
        second = [r for r in event_rows if r.get("transmission_order") == "second_order"]
        output.append(
            {
                "event_id": event_id,
                "event_date": date_by_event[event_id],
                "event_headline": headline_by_event[event_id],
                "first_order_evaluated": len(first),
                "first_order_hits": sum(1 for r in first if r.get("hit")),
                "second_order_evaluated": len(second),
                "second_order_hits": sum(1 for r in second if r.get("hit")),
                "second_order_mean_abs_scar": format_number(abs_scar_mean(second)),
                "second_order_median_abs_scar": format_number(abs_scar_median(second)),
            }
        )
    return output


def metric_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute evaluated count, hits, hit rate, and abs-SCAR stats."""

    values = abs_scar_values(rows)
    hits = sum(1 for row in rows if row.get("hit"))
    return {
        "evaluated": len(rows),
        "hits": hits,
        "hit_rate": hits / len(rows) if rows else None,
        "mean_abs_SCAR": mean(values) if values else None,
        "median_abs_SCAR": median(values) if values else None,
        "max_abs_SCAR": max(values) if values else None,
    }


def hit_rate_difference(rows: list[dict[str, Any]]) -> float | None:
    """Return GeoRisk minus baseline hit-rate difference."""

    georisk = metric_row([r for r in rows if r.get("source") == "georisk"])["hit_rate"]
    baseline = metric_row([r for r in rows if r.get("source") == "baseline"])["hit_rate"]
    if georisk is None or baseline is None:
        return None
    return georisk - baseline


def abs_scar_values(rows: list[dict[str, Any]]) -> list[float]:
    """Return absolute standardized CAR values from evaluated rows."""

    return [abs(float(row["standardized_car"])) for row in rows if row.get("standardized_car") is not None]


def abs_scar_mean(rows: list[dict[str, Any]]) -> float | None:
    values = abs_scar_values(rows)
    return mean(values) if values else None


def abs_scar_median(rows: list[dict[str, Any]]) -> float | None:
    values = abs_scar_values(rows)
    return median(values) if values else None


def write_pair_results(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write CAR pair rows with V3 headline retained."""

    columns = [*PAIR_RESULT_COLUMNS]
    if "event_headline" not in columns:
        columns.insert(3, "event_headline")
    write_csv(path, rows, columns)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    """Write dictionaries to CSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{key: format_csv_value(row.get(key)) for key in columns} for row in rows])


def write_json(path: Path, payload: Any) -> None:
    """Write JSON with stable formatting."""

    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown_report(path: Path, summary: dict[str, Any]) -> None:
    """Write a compact V3 CAR report."""

    overall = summary["overall_metrics"]
    lines = [
        "# V3 CAR Validation Report",
        "",
        "This is ex-post exposure validation, not price prediction or investment advice. Rows are clustered within 12 events, so row-level hit rates are descriptive.",
        "",
        "## Overall",
        "",
        "| Metric | GeoRisk | Baseline |",
        "| --- | ---: | ---: |",
    ]
    for metric in ["evaluated", "hits", "hit_rate", "mean_abs_SCAR", "median_abs_SCAR"]:
        lines.append(f"| {metric} | {format_number(overall['georisk'].get(metric))} | {format_number(overall['baseline'].get(metric))} |")
    lines.extend(
        [
            f"| GeoRisk-minus-baseline hit-rate difference | {format_number(summary['georisk_minus_baseline_hit_rate'])} |  |",
            "",
            f"- Total pairs: {summary['total_pairs']}",
            f"- Evaluated pairs: {summary['total_evaluated_pairs']}",
            f"- Skipped pairs: {summary['skipped_pairs']}",
            f"- Accounting valid: {summary['accounting_valid']}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_csv_value(value: Any) -> Any:
    if isinstance(value, list):
        return ";".join(map(str, value))
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return value


def format_number(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        return str(value)
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return str(value)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return str(value)
    return value


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen V3 CAR validation.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR))
    parser.add_argument("--result-dir", default=str(DEFAULT_RESULT_DIR))
    parser.add_argument("--price-dir", default=str(DEFAULT_PRICE_DIR))
    parser.add_argument("--benchmark-symbol", default="SPY")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_v3_car_validation(
        manifest_path=args.manifest,
        snapshot_dir=args.snapshot_dir,
        result_dir=args.result_dir,
        price_dir=args.price_dir,
        benchmark_symbol=args.benchmark_symbol,
    )
    print("V3 CAR Validation Complete")
    print(f"Events: {summary['events_evaluated']}")
    print(f"Total pairs: {summary['total_pairs']}")
    print(f"Evaluated pairs: {summary['total_evaluated_pairs']}")
    print(f"Skipped pairs: {summary['skipped_pairs']}")
    print(f"Accounting valid: {summary['accounting_valid']}")
    print(f"GeoRisk hit rate: {format_number(summary['overall_metrics']['georisk']['hit_rate'])}")
    print(f"Baseline hit rate: {format_number(summary['overall_metrics']['baseline']['hit_rate'])}")
    print(f"Result dir: {args.result_dir}")


if __name__ == "__main__":
    main()
