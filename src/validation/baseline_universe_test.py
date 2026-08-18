"""Baseline-universe contamination diagnostics for frozen CAR outputs.

This module does not rerun GeoRisk, download prices, or change the CAR/SCAR
methodology. It re-labels the existing asset-mapping random baseline as a
Curated-Pool Random Baseline and audits whether the frozen local price data can
support a genuinely broad random baseline.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any


DEFAULT_OUTPUT_DIR = Path("data/market_validation/baseline_universe_test")
DEFAULT_ASSET_MAPPING_PATH = Path("data/asset_mapping.csv")
DEFAULT_PRICE_DIR = Path("data/prices")
DEFAULT_CAR_RESULT_DIR = Path("data/car_results_v3")
DEFAULT_CURATED_BASELINE_DIR = Path("data/baseline_v3")
DEFAULT_BENCHMARK_SYMBOL = "SPY"
MINIMUM_BROAD_EXCLUDING_CURATED_SIZE = 30
PRIMARY_SCOPE = "all"


def run_baseline_universe_contamination_test(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    asset_mapping_path: str | Path = DEFAULT_ASSET_MAPPING_PATH,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    car_result_dir: str | Path = DEFAULT_CAR_RESULT_DIR,
    curated_baseline_dir: str | Path = DEFAULT_CURATED_BASELINE_DIR,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
) -> dict[str, Any]:
    """Generate contamination-test artifacts from frozen CAR inputs."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    curated_universe = load_curated_universe(asset_mapping_path, benchmark_symbol)
    price_universe = load_price_universe(price_dir, benchmark_symbol)
    overlap = sorted(set(curated_universe) & set(price_universe))
    broad_excluding_curated = sorted(set(price_universe) - set(curated_universe))
    georisk_rows = load_georisk_car_rows(car_result_dir)
    curated_summary = json.loads((Path(curated_baseline_dir) / "random_matched_summary.json").read_text())
    curated_config = json.loads((Path(curated_baseline_dir) / "random_matched_config.json").read_text())

    georisk_metrics = metric_row(georisk_rows)
    event_georisk = event_metrics(georisk_rows)
    curated_event = load_curated_event_summary(Path(curated_baseline_dir) / "random_matched_event_summary.csv")
    broad_audit = broad_universe_audit(
        curated_universe=curated_universe,
        price_universe=price_universe,
        georisk_rows=georisk_rows,
        benchmark_symbol=benchmark_symbol,
    )
    broad_runnable = broad_audit["broad_random_runnable"]

    curated_results = curated_pool_results(curated_summary, curated_config, georisk_metrics)
    broad_results = broad_random_results_placeholder(broad_audit, georisk_metrics)
    event_rows = event_level_comparison_rows(event_georisk, curated_event, broad_runnable)

    manifest = {
        "experiment_name": "Baseline Universe Contamination Test",
        "only_experimental_variable_changed": "random baseline sampling universe",
        "georisk_predictions_unchanged": True,
        "events_unchanged": True,
        "CAR_SCAR_implementation_unchanged": True,
        "event_windows_unchanged": True,
        "hit_threshold_unchanged": True,
        "hit_rule": "abs(standardized_car) >= 1.96",
        "benchmark_symbol": benchmark_symbol,
        "curated_pool_random_baseline": {
            "renamed_from": "random_matched",
            "definition": "Random selection from asset_mapping.csv, the curated GeoRisk asset universe.",
            "source_artifacts_preserved": [
                str(Path(curated_baseline_dir) / "random_matched_runs.csv"),
                str(Path(curated_baseline_dir) / "random_matched_summary.json"),
                str(Path(curated_baseline_dir) / "random_matched_event_summary.csv"),
            ],
        },
        "broad_random_baseline": {
            "definition": "Random selection from a broad non-geopolitically curated asset universe.",
            "status": "not_runnable_with_current_frozen_local_price_data"
            if not broad_runnable
            else "runnable",
            "reason": broad_audit["blocking_reason"],
        },
        "random_seed": curated_config.get("random_seed"),
        "monte_carlo_draws": curated_config.get("runs"),
        "forbidden_changes": [
            "GeoRisk predictions",
            "watchlist generation",
            "asset ranking",
            "event set",
            "CAR/SCAR formula",
            "hit threshold",
            "price source/data",
        ],
        "input_hashes": {
            "asset_mapping": sha256_file(asset_mapping_path),
            "car_pair_results_v3": sha256_file(Path(car_result_dir) / "car_pair_results.csv"),
            "curated_random_summary": sha256_file(Path(curated_baseline_dir) / "random_matched_summary.json"),
            "curated_random_runs": sha256_file(Path(curated_baseline_dir) / "random_matched_runs.csv"),
        },
    }
    summary = {
        "curated_pool_universe_size": len(curated_universe),
        "frozen_price_universe_size": len(price_universe),
        "broad_universe_size": len(price_universe),
        "overlap_between_broad_and_asset_mapping": len(overlap),
        "overlap_ratio_of_frozen_price_universe": round(len(overlap) / len(price_universe), 6)
        if price_universe
        else None,
        "broad_excluding_asset_mapping_size": len(broad_excluding_curated),
        "broad_random_runnable": broad_runnable,
        "broad_random_blocking_reason": broad_audit["blocking_reason"],
        "georisk": georisk_metrics,
        "curated_random": curated_results["summary"],
        "broad_random": broad_results["summary"],
        "event_level_counts": event_level_counts(event_rows),
        "core_conclusion": conclusion(georisk_metrics, curated_results["summary"], broad_audit),
        "integrity": {
            "georisk_predictions_unchanged": True,
            "events_unchanged": True,
            "CAR_SCAR_implementation_unchanged": True,
            "event_windows_unchanged": True,
            "hit_threshold_unchanged": True,
            "prices_downloaded": False,
            "price_files_modified": False,
        },
    }

    write_json(output / "baseline_universe_manifest.json", manifest)
    write_csv(output / "curated_random_results.csv", curated_results["rows"])
    write_csv(output / "broad_random_results.csv", broad_results["rows"])
    write_csv(output / "event_level_comparison.csv", event_rows)
    write_json(output / "baseline_universe_summary.json", summary)
    return summary


def load_curated_universe(path: str | Path, benchmark_symbol: str) -> list[str]:
    """Return unique curated tickers from asset_mapping.csv excluding benchmark."""

    with Path(path).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    symbols = {
        row["ticker"].upper()
        for row in rows
        if row.get("ticker") and row["ticker"].upper() != benchmark_symbol.upper()
    }
    return sorted(symbols)


def load_price_universe(price_dir: str | Path, benchmark_symbol: str) -> list[str]:
    """Return symbols with local frozen price CSVs excluding benchmark."""

    symbols = []
    for path in Path(price_dir).glob("*.csv"):
        symbol = path.stem.upper()
        if symbol != benchmark_symbol.upper():
            symbols.append(symbol)
    return sorted(set(symbols))


def load_georisk_car_rows(car_result_dir: str | Path) -> list[dict[str, Any]]:
    """Load evaluated frozen GeoRisk CAR rows."""

    path = Path(car_result_dir) / "car_pair_results.csv"
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [coerce_car_row(row) for row in rows if row.get("source") == "georisk" and not row.get("missing_data_reason")]


def load_curated_event_summary(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load per-event means for the existing curated-pool random baseline."""

    with Path(path).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {row["event_id"]: row for row in rows}


def curated_pool_results(
    random_summary: dict[str, Any],
    random_config: dict[str, Any],
    georisk_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Convert existing random_matched summary into curated-pool artifact rows."""

    scope = random_summary["scopes"][PRIMARY_SCOPE]
    hit_rate = scope["hit_rate"]
    summary = {
        "baseline_name": "Curated-Pool Random Baseline",
        "sampling_universe": "asset_mapping.csv",
        "monte_carlo_draws": random_config.get("runs"),
        "random_seed": random_config.get("random_seed"),
        "mean_hit_rate": hit_rate["mean"],
        "median_hit_rate": hit_rate["median"],
        "p05_hit_rate": hit_rate["p05"],
        "p95_hit_rate": hit_rate["p95"],
        "georisk_percentile_hit_rate": scope["actual_georisk_percentile_rank_hit_rate"],
        "georisk_observed_hit_rate": georisk_metrics["hit_rate"],
    }
    rows = [
        {
            "baseline_name": summary["baseline_name"],
            "scope": PRIMARY_SCOPE,
            "metric": key,
            "value": value,
        }
        for key, value in summary.items()
        if key not in {"baseline_name"}
    ]
    return {"summary": summary, "rows": rows}


def broad_random_results_placeholder(
    audit: dict[str, Any],
    georisk_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Return broad-random result rows when the local frozen universe is invalid."""

    summary = {
        "baseline_name": "Broad Random Baseline",
        "sampling_universe": "broad non-curated equity universe",
        "status": "not_run",
        "reason": audit["blocking_reason"],
        "mean_hit_rate": None,
        "median_hit_rate": None,
        "p05_hit_rate": None,
        "p95_hit_rate": None,
        "georisk_percentile_hit_rate": None,
        "georisk_observed_hit_rate": georisk_metrics["hit_rate"],
    }
    rows = [
        {
            "baseline_name": summary["baseline_name"],
            "scope": PRIMARY_SCOPE,
            "metric": key,
            "value": value,
        }
        for key, value in summary.items()
        if key not in {"baseline_name"}
    ]
    rows.extend(audit["rows"])
    return {"summary": summary, "rows": rows}


def broad_universe_audit(
    curated_universe: list[str],
    price_universe: list[str],
    georisk_rows: list[dict[str, Any]],
    benchmark_symbol: str,
) -> dict[str, Any]:
    """Audit whether frozen local prices can support a true broad baseline."""

    curated = set(curated_universe)
    prices = set(price_universe)
    overlap = curated & prices
    non_curated = prices - curated
    max_event_n = max(Counter(row["event_id"] for row in georisk_rows).values()) if georisk_rows else 0
    reason_parts: list[str] = []
    if len(non_curated) < MINIMUM_BROAD_EXCLUDING_CURATED_SIZE:
        reason_parts.append(
            f"only_{len(non_curated)}_non_curated_symbols_with_frozen_local_prices"
        )
    if len(non_curated) < max_event_n:
        reason_parts.append(
            f"non_curated_price_universe_smaller_than_max_event_sample_size_{max_event_n}"
        )
    if price_universe and len(overlap) / len(price_universe) > 0.5:
        reason_parts.append(
            f"frozen_price_universe_{len(overlap)}_of_{len(price_universe)}_overlaps_asset_mapping"
        )
    runnable = not reason_parts
    return {
        "broad_random_runnable": runnable,
        "blocking_reason": "none" if runnable else ";".join(reason_parts),
        "rows": [
            {
                "baseline_name": "Broad Random Baseline",
                "scope": PRIMARY_SCOPE,
                "metric": "frozen_price_universe_size",
                "value": len(price_universe),
            },
            {
                "baseline_name": "Broad Random Baseline",
                "scope": PRIMARY_SCOPE,
                "metric": "curated_overlap_count",
                "value": len(overlap),
            },
            {
                "baseline_name": "Broad Random Baseline",
                "scope": PRIMARY_SCOPE,
                "metric": "non_curated_frozen_price_symbols",
                "value": ";".join(sorted(non_curated)),
            },
            {
                "baseline_name": "Broad Random Baseline",
                "scope": PRIMARY_SCOPE,
                "metric": "benchmark_symbol_excluded",
                "value": benchmark_symbol,
            },
        ],
    }


def event_level_comparison_rows(
    georisk_by_event: dict[str, dict[str, Any]],
    curated_by_event: dict[str, dict[str, Any]],
    broad_runnable: bool,
) -> list[dict[str, Any]]:
    """Build per-event GeoRisk vs baseline comparison rows."""

    rows: list[dict[str, Any]] = []
    for event_id in sorted(georisk_by_event):
        geo = georisk_by_event[event_id]
        curated = curated_by_event.get(event_id, {})
        curated_mean = parse_float(curated.get("random_baseline_mean_hit_rate"))
        broad_mean = None
        rows.append(
            {
                "event_id": event_id,
                "georisk_evaluable_assets": geo["evaluated"],
                "georisk_hits": geo["hits"],
                "georisk_hit_rate": geo["hit_rate"],
                "curated_random_mean_hit_rate": curated_mean,
                "broad_random_mean_hit_rate": broad_mean,
                "georisk_minus_curated_delta": geo["hit_rate"] - curated_mean
                if curated_mean is not None
                else None,
                "georisk_minus_broad_delta": None,
                "curated_comparison": compare_rates(geo["hit_rate"], curated_mean),
                "broad_comparison": "not_computed_invalid_broad_universe"
                if not broad_runnable
                else compare_rates(geo["hit_rate"], broad_mean),
            }
        )
    return rows


def event_level_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count event-level comparison directions."""

    return {
        "curated": dict(Counter(row["curated_comparison"] for row in rows)),
        "broad": dict(Counter(row["broad_comparison"] for row in rows)),
    }


def conclusion(
    georisk: dict[str, Any],
    curated: dict[str, Any],
    broad_audit: dict[str, Any],
) -> dict[str, Any]:
    """Return the narrow conclusion supported by available frozen data."""

    curated_delta = georisk["hit_rate"] - curated["mean_hit_rate"]
    if not broad_audit["broad_random_runnable"]:
        return {
            "answer": "INCONCLUSIVE_FOR_BROAD_RANDOM",
            "curated_pool_inflation_test_possible": False,
            "reason": (
                "The frozen local price universe is itself almost entirely the "
                "GeoRisk curated asset universe, so it cannot identify a true "
                "broad-random distribution without changing price data."
            ),
            "georisk_minus_curated_pool_random_hit_rate": curated_delta,
        }
    return {
        "answer": "READY",
        "curated_pool_inflation_test_possible": True,
        "georisk_minus_curated_pool_random_hit_rate": curated_delta,
    }


def metric_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute evaluated count, hit count, hit rate, and |SCAR| summaries."""

    values = [abs(float(row["standardized_car"])) for row in rows if row.get("standardized_car") not in {None, ""}]
    hits = sum(1 for row in rows if bool(row.get("hit")))
    return {
        "evaluated": len(rows),
        "hits": hits,
        "hit_rate": hits / len(rows) if rows else None,
        "mean_abs_SCAR": mean(values) if values else None,
        "median_abs_SCAR": median(values) if values else None,
        "max_abs_SCAR": max(values) if values else None,
    }


def event_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return metric rows grouped by event_id."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row)
    return {event_id: metric_row(event_rows) for event_id, event_rows in grouped.items()}


def coerce_car_row(row: dict[str, str]) -> dict[str, Any]:
    """Coerce CSV CAR fields used by this diagnostic."""

    result: dict[str, Any] = dict(row)
    result["hit"] = str(row.get("hit", "")).lower() == "true"
    for key in ["standardized_car", "car"]:
        result[key] = parse_float(row.get(key))
    return result


def parse_float(value: Any) -> float | None:
    """Parse a float-like value, preserving missing values as None."""

    if value in {None, ""}:
        return None
    return float(value)


def compare_rates(actual: float | None, baseline: float | None) -> str:
    """Compare event-level hit rates without statistical inference."""

    if actual is None or baseline is None:
        return "not_computed"
    if actual > baseline:
        return "georisk_gt_baseline"
    if actual < baseline:
        return "georisk_lt_baseline"
    return "georisk_eq_baseline"


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 checksum for a file."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Write deterministic JSON."""

    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write CSV rows with stable headers."""

    path = Path(path)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
