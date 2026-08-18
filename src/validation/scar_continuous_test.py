"""Continuous |SCAR| diagnostics for the curated-pool random baseline.

The experiment keeps the frozen V3 CAR validation setup unchanged and changes
only the evaluation metric from binary ``|SCAR| >= 1.96`` to continuous
``|SCAR|`` summaries. It does not rerun GeoRisk predictions, change event
windows, download prices, or alter the random sampling universe.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd
from scipy.stats import mannwhitneyu

from scripts.evaluate_v3_additional_baselines import (
    DEFAULT_ASSET_MAPPING,
    DEFAULT_CAR_RESULT_DIR,
    DEFAULT_OUTPUT_DIR as DEFAULT_CURATED_BASELINE_DIR,
    DEFAULT_PRICE_DIR,
    DEFAULT_RANDOM_RUNS,
    DEFAULT_RANDOM_SEED,
    DEFAULT_SNAPSHOT_DIR,
    calculate_exposure_rows,
    evaluate_random_matched_baseline,
    load_asset_universe,
    load_existing_v3_car_rows,
    load_price_cache,
    load_v3_manifest,
    load_v3_snapshots,
    precompute_event_symbol_car_lookup,
    random_matched_draw,
    scoped_georisk_exposures,
)
from scripts.run_car_validation_v3 import DEFAULT_MANIFEST_PATH, metric_row, sha256_file
from src.validation.car_calculator import MarketModelConfig
from src.validation.exposure_evaluator import split_evaluated_and_skipped


DEFAULT_OUTPUT_DIR = Path("data/market_validation/scar_continuous_test")
DEFAULT_BENCHMARK_SYMBOL = "SPY"
PRIMARY_SCOPE = "all"


def run_continuous_scar_compression_test(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    car_result_dir: str | Path = DEFAULT_CAR_RESULT_DIR,
    curated_baseline_dir: str | Path = DEFAULT_CURATED_BASELINE_DIR,
    asset_mapping_path: str | Path = DEFAULT_ASSET_MAPPING,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    random_runs: int = DEFAULT_RANDOM_RUNS,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    """Run the continuous |SCAR| compression diagnostic."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = MarketModelConfig()

    manifest = load_v3_manifest(manifest_path)
    snapshots = load_v3_snapshots(manifest, snapshot_dir)
    asset_universe = load_asset_universe(asset_mapping_path)
    price_cache = load_price_cache(asset_universe, snapshots, price_dir, benchmark_symbol)
    car_lookup = precompute_event_symbol_car_lookup(
        snapshots=snapshots,
        asset_universe=asset_universe,
        price_cache=price_cache,
        benchmark_symbol=benchmark_symbol,
        config=config,
    )
    georisk_rows, _ = load_existing_v3_car_rows(car_result_dir)

    random_result = evaluate_random_matched_baseline(
        snapshots=snapshots,
        asset_universe=asset_universe,
        price_cache=price_cache,
        car_lookup=car_lookup,
        benchmark_symbol=benchmark_symbol,
        config=config,
        runs=random_runs,
        seed=random_seed,
    )
    run_rows = [row for row in random_result["run_rows"] if row["scope"] == PRIMARY_SCOPE]
    event_run_rows = [row for row in random_result["event_run_rows"] if row["scope"] == PRIMARY_SCOPE]

    georisk_event_rows = georisk_event_continuous_rows(georisk_rows)
    random_event_by_run = event_rows_by_run(event_run_rows)
    mc_rows = curated_random_mc_rows(run_rows, random_event_by_run)
    observed_aggregate = median(row["georisk_event_median_abs_scar"] for row in georisk_event_rows)

    random_aggregate_values = [row["aggregate_event_median_abs_scar"] for row in mc_rows]
    event_comparison = event_level_comparison_rows(georisk_event_rows, random_event_by_run)
    random_asset_values = collect_random_all_scope_abs_scar_values(
        snapshots=snapshots,
        asset_universe=asset_universe,
        price_cache=price_cache,
        car_lookup=car_lookup,
        benchmark_symbol=benchmark_symbol,
        config=config,
        runs=random_runs,
        seed=random_seed,
    )
    asset_comparison = asset_level_comparison_rows(georisk_rows, run_rows, random_asset_values)
    mw = mann_whitney_secondary(georisk_rows, random_asset_values)
    binary_reference = binary_reference_summary(curated_baseline_dir, georisk_rows)

    summary = {
        "experiment_name": "Binary SCAR Threshold Compression Test",
        "primary_metric": "median event-level median absolute_scar",
        "absolute_scar_definition": "abs(standardized_car)",
        "binary_reference": binary_reference,
        "continuous_asset_level": {
            "georisk_median_abs_scar": median(abs_scar_values(georisk_rows)),
            "curated_random_median_abs_scar": median(float(row["median_abs_SCAR"]) for row in run_rows),
            "curated_random_pooled_asset_median_abs_scar": median(random_asset_values),
            "difference": median(abs_scar_values(georisk_rows))
            - median(float(row["median_abs_SCAR"]) for row in run_rows),
            "pooled_asset_difference": median(abs_scar_values(georisk_rows)) - median(random_asset_values),
            "relative_difference": (
                median(abs_scar_values(georisk_rows)) / median(float(row["median_abs_SCAR"]) for row in run_rows) - 1
            ),
            "pooled_asset_relative_difference": median(abs_scar_values(georisk_rows)) / median(random_asset_values) - 1,
            "georisk_mean_abs_scar": mean(abs_scar_values(georisk_rows)),
            "curated_random_mean_abs_scar": mean(float(row["mean_abs_SCAR"]) for row in run_rows),
            "georisk_p25_abs_scar": percentile(abs_scar_values(georisk_rows), 0.25),
            "georisk_p75_abs_scar": percentile(abs_scar_values(georisk_rows), 0.75),
            "georisk_p90_abs_scar": percentile(abs_scar_values(georisk_rows), 0.90),
            "curated_random_p25_of_run_medians": percentile(
                [float(row["median_abs_SCAR"]) for row in run_rows], 0.25
            ),
            "curated_random_p75_of_run_medians": percentile(
                [float(row["median_abs_SCAR"]) for row in run_rows], 0.75
            ),
            "curated_random_p90_of_run_medians": percentile(
                [float(row["median_abs_SCAR"]) for row in run_rows], 0.90
            ),
            "mann_whitney_secondary": mw,
            "clustering_limitation": (
                "Asset-level rows are clustered within events and MC draws; "
                "Mann-Whitney is descriptive, not the primary inference."
            ),
        },
        "event_level_primary": {
            "events": len(georisk_event_rows),
            "events_with_positive_median_delta": sum(
                1 for row in event_comparison if row["delta_vs_random_mean_event_median_abs_scar"] > 0
            ),
            "events_with_negative_median_delta": sum(
                1 for row in event_comparison if row["delta_vs_random_mean_event_median_abs_scar"] < 0
            ),
            "events_with_zero_median_delta": sum(
                1 for row in event_comparison if row["delta_vs_random_mean_event_median_abs_scar"] == 0
            ),
            "median_event_level_delta": median(
                row["delta_vs_random_mean_event_median_abs_scar"] for row in event_comparison
            ),
            "mean_event_level_delta": mean(
                row["delta_vs_random_mean_event_median_abs_scar"] for row in event_comparison
            ),
            "georisk_observed_aggregate_median_abs_scar": observed_aggregate,
            "curated_random_aggregate": distribution_summary(random_aggregate_values),
            "georisk_mc_percentile": percentile_rank(random_aggregate_values, observed_aggregate),
            "empirical_one_sided_p_value": empirical_one_sided_p_value(
                random_aggregate_values, observed_aggregate
            ),
        },
        "pattern": classify_pattern(binary_reference, observed_aggregate, random_aggregate_values, event_comparison),
        "integrity": {
            "same_events": True,
            "same_georisk_predictions": True,
            "same_curated_baseline": True,
            "same_prices": True,
            "same_CAR_SCAR_calculation": True,
            "same_random_seed": random_seed,
            "same_monte_carlo_draws": random_runs,
            "broad_random_baseline_built": False,
            "threshold_tuning": False,
            "power_analysis": False,
            "sector_matched_baseline": False,
        },
        "input_hashes": {
            "car_pair_results_v3": sha256_file(Path(car_result_dir) / "car_pair_results.csv"),
            "random_matched_summary": sha256_file(Path(curated_baseline_dir) / "random_matched_summary.json"),
            "random_matched_runs": sha256_file(Path(curated_baseline_dir) / "random_matched_runs.csv"),
            "asset_mapping": sha256_file(asset_mapping_path),
        },
    }

    write_json(output / "continuous_scar_manifest.json", continuous_manifest(summary, manifest_path))
    write_csv(output / "event_level_continuous_comparison.csv", event_comparison)
    write_csv(output / "asset_level_continuous_comparison.csv", asset_comparison)
    write_csv(output / "curated_random_continuous_mc.csv", mc_rows)
    write_json(output / "continuous_scar_summary.json", summary)
    return summary


def georisk_event_continuous_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize GeoRisk continuous |SCAR| by event."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row)
    output = []
    for event_id, event_rows in sorted(grouped.items()):
        values = abs_scar_values(event_rows)
        metric = metric_row(event_rows)
        output.append(
            {
                "event_id": event_id,
                "georisk_evaluable_assets": metric["evaluated"],
                "georisk_hits": metric["hits"],
                "georisk_hit_rate": metric["hit_rate"],
                "georisk_event_median_abs_scar": median(values),
                "georisk_event_mean_abs_scar": mean(values),
                "georisk_event_p25_abs_scar": percentile(values, 0.25),
                "georisk_event_p75_abs_scar": percentile(values, 0.75),
                "georisk_event_p90_abs_scar": percentile(values, 0.90),
            }
        )
    return output


def event_rows_by_run(event_run_rows: list[dict[str, Any]]) -> dict[int, dict[str, dict[str, Any]]]:
    """Index random event-level rows by run id and event id."""

    grouped: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in event_run_rows:
        grouped[int(row["run_id"])][row["event_id"]] = row
    return grouped


def curated_random_mc_rows(
    run_rows: list[dict[str, Any]],
    event_by_run: dict[int, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Create one continuous Monte Carlo aggregate row per random draw."""

    rows = []
    for row in sorted(run_rows, key=lambda item: int(item["run_id"])):
        run_id = int(row["run_id"])
        event_medians = [
            float(event_row["median_abs_SCAR"])
            for event_row in event_by_run.get(run_id, {}).values()
            if event_row.get("median_abs_SCAR") not in {None, ""}
        ]
        rows.append(
            {
                "run_id": run_id,
                "scope": PRIMARY_SCOPE,
                "evaluated": int(row["evaluated"]),
                "hits": int(row["hits"]),
                "hit_rate": float(row["hit_rate"]),
                "pooled_mean_abs_scar": float(row["mean_abs_SCAR"]),
                "pooled_median_abs_scar": float(row["median_abs_SCAR"]),
                "aggregate_event_median_abs_scar": median(event_medians) if event_medians else None,
                "event_count": len(event_medians),
            }
        )
    return rows


def event_level_comparison_rows(
    georisk_rows: list[dict[str, Any]],
    random_event_by_run: dict[int, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Compare each event's GeoRisk median |SCAR| with random draw distribution."""

    output = []
    for geo in georisk_rows:
        event_id = geo["event_id"]
        random_medians = [
            float(event_rows[event_id]["median_abs_SCAR"])
            for event_rows in random_event_by_run.values()
            if event_id in event_rows and event_rows[event_id].get("median_abs_SCAR") not in {None, ""}
        ]
        random_mean = mean(random_medians)
        output.append(
            {
                **geo,
                "curated_random_mean_event_median_abs_scar": random_mean,
                "curated_random_median_event_median_abs_scar": median(random_medians),
                "curated_random_p05_event_median_abs_scar": percentile(random_medians, 0.05),
                "curated_random_p95_event_median_abs_scar": percentile(random_medians, 0.95),
                "delta_vs_random_mean_event_median_abs_scar": geo["georisk_event_median_abs_scar"]
                - random_mean,
                "georisk_event_percentile": percentile_rank(random_medians, geo["georisk_event_median_abs_scar"]),
            }
        )
    return output


def asset_level_comparison_rows(
    georisk_rows: list[dict[str, Any]],
    random_run_rows: list[dict[str, Any]],
    random_asset_values: list[float],
) -> list[dict[str, Any]]:
    """Write secondary pooled asset-level continuous summaries."""

    georisk_values = abs_scar_values(georisk_rows)
    random_medians = [float(row["median_abs_SCAR"]) for row in random_run_rows]
    random_means = [float(row["mean_abs_SCAR"]) for row in random_run_rows]
    return [
        {
            "source": "GeoRisk",
            "scope": PRIMARY_SCOPE,
            "rows": len(georisk_values),
            "median_abs_scar": median(georisk_values),
            "mean_abs_scar": mean(georisk_values),
            "p25_abs_scar": percentile(georisk_values, 0.25),
            "p75_abs_scar": percentile(georisk_values, 0.75),
            "p90_abs_scar": percentile(georisk_values, 0.90),
        },
        {
            "source": "Curated-Pool Random Baseline",
            "scope": PRIMARY_SCOPE,
            "rows": len(random_asset_values),
            "median_abs_scar": median(random_asset_values),
            "mean_abs_scar": mean(random_asset_values),
            "p25_abs_scar": percentile(random_asset_values, 0.25),
            "p75_abs_scar": percentile(random_asset_values, 0.75),
            "p90_abs_scar": percentile(random_asset_values, 0.90),
            "note": "pooled evaluated random asset rows across all MC draws",
        },
        {
            "source": "Curated-Pool Random Baseline per-draw summary",
            "scope": PRIMARY_SCOPE,
            "rows": len(random_medians),
            "median_abs_scar": median(random_medians),
            "mean_abs_scar": mean(random_means),
            "p25_abs_scar": percentile(random_medians, 0.25),
            "p75_abs_scar": percentile(random_medians, 0.75),
            "p90_abs_scar": percentile(random_medians, 0.90),
            "note": "random rows summarize per-draw pooled distributions",
        },
    ]


def binary_reference_summary(curated_baseline_dir: str | Path, georisk_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Load the frozen binary-hit reference for side-by-side comparison."""

    payload = json.loads((Path(curated_baseline_dir) / "random_matched_summary.json").read_text())
    scope = payload["scopes"][PRIMARY_SCOPE]
    geo = metric_row(georisk_rows)
    curated_mean = scope["hit_rate"]["mean"]
    return {
        "hit_rule": "abs(standardized_car) >= 1.96",
        "georisk_hit_rate": geo["hit_rate"],
        "georisk_hits": geo["hits"],
        "georisk_evaluated": geo["evaluated"],
        "curated_random_mean_hit_rate": curated_mean,
        "curated_random_median_hit_rate": scope["hit_rate"]["median"],
        "curated_random_p05_hit_rate": scope["hit_rate"]["p05"],
        "curated_random_p95_hit_rate": scope["hit_rate"]["p95"],
        "delta_georisk_minus_curated_mean": geo["hit_rate"] - curated_mean,
        "georisk_percentile": scope["actual_georisk_percentile_rank_hit_rate"],
    }


def mann_whitney_secondary(
    georisk_rows: list[dict[str, Any]],
    random_asset_values: list[float],
) -> dict[str, Any]:
    """Run a descriptive asset-level Mann-Whitney diagnostic."""

    georisk_values = abs_scar_values(georisk_rows)
    statistic, p_value = mannwhitneyu(georisk_values, random_asset_values, alternative="greater")
    n1 = len(georisk_values)
    n2 = len(random_asset_values)
    rank_biserial = (2 * float(statistic) / (n1 * n2)) - 1
    return {
        "test": "Mann-Whitney U",
        "alternative": "GeoRisk |SCAR| greater than pooled curated-random asset draws",
        "u_statistic": float(statistic),
        "p_value": float(p_value),
        "rank_biserial_correlation": rank_biserial,
        "descriptive_secondary_only": True,
    }


def collect_random_all_scope_abs_scar_values(
    snapshots: list[dict[str, Any]],
    asset_universe: list[dict[str, Any]],
    price_cache: dict[str, pd.DataFrame | None],
    car_lookup: dict[tuple[str, str], dict[str, Any]],
    benchmark_symbol: str,
    config: MarketModelConfig,
    runs: int,
    seed: int,
) -> list[float]:
    """Collect pooled all-scope random asset |SCAR| values with original RNG order."""

    rng = random.Random(seed)
    universe_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in asset_universe:
        universe_by_type[row["asset_type"]].append(row)
    for rows in universe_by_type.values():
        rows.sort(key=lambda item: (item["ticker"], item["supply_chain_node"]))

    values: list[float] = []
    for run_id in range(runs):
        for snapshot in snapshots:
            for scope in ["all", "first_order", "second_order"]:
                georisk = scoped_georisk_exposures(snapshot, scope)
                sampled, _ = random_matched_draw(
                    georisk,
                    universe_by_type,
                    rng,
                    benchmark_symbol,
                    run_id,
                    snapshot["event_id"],
                    scope,
                )
                rows = calculate_exposure_rows(
                    sampled,
                    event_id=snapshot["event_id"],
                    event_date=snapshot["event_date"],
                    event_headline=snapshot.get("headline", ""),
                    event_type=snapshot.get("event_type", ""),
                    source="curated_pool_random",
                    price_cache=price_cache,
                    car_lookup=car_lookup,
                    benchmark_symbol=benchmark_symbol,
                    config=config,
                )
                if scope == PRIMARY_SCOPE:
                    evaluated, _ = split_evaluated_and_skipped(rows)
                    values.extend(abs_scar_values(evaluated))
    return values


def classify_pattern(
    binary: dict[str, Any],
    observed_aggregate: float,
    random_aggregate_values: list[float],
    event_comparison: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify whether binary threshold compression is supported."""

    continuous_percentile = percentile_rank(random_aggregate_values, observed_aggregate)
    positive_events = sum(1 for row in event_comparison if row["delta_vs_random_mean_event_median_abs_scar"] > 0)
    binary_delta_pp = binary["delta_georisk_minus_curated_mean"] * 100
    if continuous_percentile >= 0.9 and positive_events >= 8 and binary_delta_pp < 3:
        return {
            "label": "Pattern A",
            "conclusion": "YES",
            "rationale": "binary difference is small while event-level continuous |SCAR| is strongly positive",
        }
    if continuous_percentile >= 0.75 and positive_events >= 7:
        return {
            "label": "Pattern C",
            "conclusion": "PARTIALLY",
            "rationale": "continuous advantage exists but is not uniformly strong across events",
        }
    return {
        "label": "Pattern B",
        "conclusion": "NO",
        "rationale": "continuous |SCAR| does not materially separate GeoRisk from Curated-Pool Random",
    }


def continuous_manifest(summary: dict[str, Any], manifest_path: str | Path) -> dict[str, Any]:
    """Build the experiment manifest."""

    return {
        "experiment_name": summary["experiment_name"],
        "frozen_v3_manifest": str(manifest_path),
        "primary_metric": summary["primary_metric"],
        "binary_metric_retained_as_secondary": True,
        "empirical_one_sided_p_value_definition": "(random_draws >= observed_georisk + 1) / (draws + 1)",
        "integrity": summary["integrity"],
        "input_hashes": summary["input_hashes"],
    }


def abs_scar_values(rows: list[dict[str, Any]]) -> list[float]:
    """Return absolute SCAR values from evaluated rows."""

    return [abs(float(row["standardized_car"])) for row in rows if row.get("standardized_car") not in {None, ""}]


def distribution_summary(values: list[float]) -> dict[str, float | None]:
    """Return basic distribution summary."""

    if not values:
        return {"mean": None, "median": None, "p05": None, "p25": None, "p75": None, "p90": None, "p95": None}
    return {
        "mean": mean(values),
        "median": median(values),
        "p05": percentile(values, 0.05),
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
    }


def percentile(values: list[float], q: float) -> float:
    """Return a deterministic nearest-rank-style interpolated percentile."""

    if not values:
        raise ValueError("Cannot calculate percentile of empty values.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def percentile_rank(values: list[float], observed: float) -> float:
    """Return empirical percentile rank of observed among random values."""

    if not values:
        return 0.0
    return sum(1 for value in values if value <= observed) / len(values)


def empirical_one_sided_p_value(values: list[float], observed: float) -> float:
    """Return pre-registered one-sided empirical p-value."""

    return (sum(1 for value in values if value >= observed) + 1) / (len(values) + 1)


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Write deterministic JSON."""

    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write CSV rows with stable union headers."""

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
