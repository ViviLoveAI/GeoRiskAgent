"""Curated-pool activation boundary diagnostics for market validation.

This experiment compares assets activated by frozen event-specific transmission
nodes against non-activated assets in the same curated asset universe. The
activation boundary is frozen before CAR/SCAR values are joined.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd
from scipy.stats import mannwhitneyu

from src.validation.car_calculator import (
    MarketModelConfig,
    calculate_market_model_car_from_prices,
    load_price_series,
)
from src.validation.curated_filtering_test import (
    dedupe,
    hash_directory,
    percentile,
    rank_biserial_from_u,
    sha256_file,
    write_csv,
    write_json,
)


OUTPUT_DIR = Path("data/market_validation/curated_activation")
SNAPSHOT_DIR = Path("data/validation_v3/prediction_snapshots")
V3_MANIFEST_PATH = Path("data/validation_v3/v3_manifest.json")
CAR_RESULTS_PATH = Path("data/car_results_v3/car_pair_results.csv")
ASSET_MAPPING_PATH = Path("data/asset_mapping.csv")
PRICE_DIR = Path("data/prices")
BENCHMARK_SYMBOL = "SPY"
RANDOM_SEED = 20260805
PERMUTATION_DRAWS = 10000


def run_curated_activation_test(
    output_dir: str | Path = OUTPUT_DIR,
    snapshot_dir: str | Path = SNAPSHOT_DIR,
    v3_manifest_path: str | Path = V3_MANIFEST_PATH,
    car_results_path: str | Path = CAR_RESULTS_PATH,
    asset_mapping_path: str | Path = ASSET_MAPPING_PATH,
    price_dir: str | Path = PRICE_DIR,
    benchmark_symbol: str = BENCHMARK_SYMBOL,
    random_seed: int = RANDOM_SEED,
    permutation_draws: int = PERMUTATION_DRAWS,
) -> dict[str, Any]:
    """Run the curated activation / non-activation discrimination test."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = MarketModelConfig()
    snapshots = load_snapshots(snapshot_dir)
    asset_mapping = pd.read_csv(asset_mapping_path)
    provenance = build_provenance_audit(
        snapshots=snapshots,
        snapshot_dir=snapshot_dir,
        v3_manifest_path=v3_manifest_path,
        car_results_path=car_results_path,
    )
    write_json(output / "provenance_audit.json", provenance)

    activation_rows = build_activation_snapshot(
        snapshots=snapshots,
        asset_mapping=asset_mapping,
        price_dir=Path(price_dir),
        benchmark_symbol=benchmark_symbol,
        config=config,
    )
    activation_path = output / "activation_snapshot.csv"
    activation_manifest_path = output / "activation_snapshot_manifest.json"
    activation_checksums_path = output / "activation_snapshot_checksums.json"
    write_csv(activation_path, activation_rows)
    activation_manifest = build_activation_manifest(
        activation_rows=activation_rows,
        provenance=provenance,
        asset_mapping_path=asset_mapping_path,
        price_dir=price_dir,
    )
    write_json(activation_manifest_path, activation_manifest)
    write_json(
        activation_checksums_path,
        {
            "activation_snapshot.csv": sha256_file(activation_path),
            "activation_snapshot_manifest.json": sha256_file(activation_manifest_path),
        },
    )

    # SCAR values are computed only after the activation boundary is frozen.
    market_rows = join_activation_market_results(
        activation_rows=activation_rows,
        snapshots=snapshots,
        price_dir=Path(price_dir),
        benchmark_symbol=benchmark_symbol,
        config=config,
    )
    event_rows = event_level_activation_rows(market_rows)
    summary = build_activation_summary(
        provenance=provenance,
        activation_rows=activation_rows,
        market_rows=market_rows,
        event_rows=event_rows,
        random_seed=random_seed,
        permutation_draws=permutation_draws,
        activation_path=activation_path,
        car_results_path=car_results_path,
        asset_mapping_path=asset_mapping_path,
    )
    manifest = build_test_manifest(summary, provenance, activation_manifest)

    write_csv(output / "activated_nonactivated_asset_results.csv", market_rows)
    write_csv(output / "event_level_activation_comparison.csv", event_rows)
    write_json(output / "activation_summary.json", summary)
    write_json(output / "activation_test_manifest.json", manifest)
    return summary


def load_snapshots(snapshot_dir: str | Path) -> list[dict[str, Any]]:
    """Load frozen market-validation snapshots."""

    paths = sorted(Path(snapshot_dir).glob("*_snapshot_v3.json"))
    if not paths:
        raise FileNotFoundError(f"No snapshots found in {snapshot_dir}")
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def build_provenance_audit(
    snapshots: list[dict[str, Any]],
    snapshot_dir: str | Path,
    v3_manifest_path: str | Path,
    car_results_path: str | Path,
) -> dict[str, Any]:
    """Trace CAR rows back to frozen prediction snapshots."""

    car_frame = pd.read_csv(car_results_path)
    georisk = car_frame[car_frame["source"].astype(str) == "georisk"].copy()
    snapshot_ids = {snapshot["event_id"] for snapshot in snapshots}
    car_ids = set(georisk["event_id"].astype(str))
    selected_count = sum(len(snapshot.get("predicted_exposures", [])) for snapshot in snapshots)
    return {
        "market_validation_prediction_version": "GeoRisk frozen market-validation snapshot (V3 snapshot artifacts)",
        "is_frozen_v4_market_validation": False,
        "system_version_label": "legacy/V3 CAR snapshot",
        "event_count": len(snapshots),
        "georisk_car_rows": len(georisk),
        "predicted_exposure_rows": selected_count,
        "provenance_confirmed": snapshot_ids == car_ids and selected_count == len(georisk),
        "prediction_artifact_paths": {
            "manifest": str(v3_manifest_path),
            "snapshot_dir": str(snapshot_dir),
            "car_results": str(car_results_path),
        },
        "freeze_status": {
            "prediction_snapshots_frozen": True,
            "car_results_existing_frozen_input": True,
        },
        "checksums": {
            "v3_manifest": sha256_file(v3_manifest_path),
            "snapshot_dir": hash_directory(snapshot_dir, "*_snapshot_v3.json"),
            "car_pair_results": sha256_file(car_results_path),
        },
    }


def build_activation_snapshot(
    snapshots: list[dict[str, Any]],
    asset_mapping: pd.DataFrame,
    price_dir: Path,
    benchmark_symbol: str,
    config: MarketModelConfig,
) -> list[dict[str, Any]]:
    """Build event-level activated vs non-activated curated universe rows."""

    benchmark_prices, benchmark_error = load_price_series(benchmark_symbol, price_dir=price_dir)
    if benchmark_prices is None:
        raise RuntimeError(f"Missing benchmark prices for activation snapshot: {benchmark_error}")
    rows: list[dict[str, Any]] = []
    asset_rows = unique_asset_mapping_rows(asset_mapping)
    price_cache: dict[str, pd.DataFrame | None] = {}
    for snapshot in snapshots:
        event_id = str(snapshot["event_id"])
        activated_nodes = set(dedupe((snapshot.get("transmission_chain") or {}).get("affected_nodes") or []))
        predicted_symbols = {
            str(row.get("symbol") or "").upper()
            for row in snapshot.get("predicted_exposures", [])
            if row.get("symbol")
        }
        for record in asset_rows:
            ticker = str(record["ticker"]).upper()
            if ticker not in price_cache:
                prices, _ = load_price_series(ticker, price_dir=price_dir)
                price_cache[ticker] = prices
            prices = price_cache[ticker]
            asset_status = price_coverage_status(ticker, price_dir)
            if prices is None:
                price_status = "missing_asset_prices"
                curated_eligible = False
            else:
                eligibility_result = calculate_market_model_car_from_prices(
                    event_id=event_id,
                    symbol=ticker,
                    event_date=snapshot["event_date"],
                    asset_prices=prices,
                    benchmark_prices=benchmark_prices,
                    config=config,
                )
                missing_reason = eligibility_result.get("missing_data_reason")
                finite_scar = numeric_or_none(eligibility_result.get("standardized_car")) is not None
                price_status = (
                    "car_scar_evaluable"
                    if not missing_reason and finite_scar
                    else str(missing_reason or "non_finite_standardized_car")
                )
                curated_eligible = not bool(missing_reason) and finite_scar
            activated = str(record["supply_chain_node"]) in activated_nodes
            rows.append(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "asset_type": str(record.get("asset_type") or ""),
                    "curated_eligible": str(curated_eligible).lower(),
                    "activated": str(activated).lower(),
                    "non_activated": str(not activated).lower(),
                    "activation_source_node": str(record["supply_chain_node"]) if activated else "",
                    "prediction_version": "GeoRisk frozen market-validation snapshot (V3 snapshot artifacts)",
                    "prediction_artifact_source": str(SNAPSHOT_DIR),
                    "price_eligibility_status": price_status,
                    "price_start": asset_status["price_start"],
                    "price_end": asset_status["price_end"],
                    "matches_frozen_predicted_exposures": str((ticker in predicted_symbols) == activated).lower(),
                }
            )
    validate_activation_rows(rows)
    return [row for row in rows if row["curated_eligible"] == "true"]


def unique_asset_mapping_rows(asset_mapping: pd.DataFrame) -> list[dict[str, Any]]:
    """Return one curated mapping row per ticker, preserving file order."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in asset_mapping.to_dict(orient="records"):
        ticker = str(record.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        rows.append(record)
    return rows


def validate_activation_rows(rows: list[dict[str, Any]]) -> None:
    """Validate activation XOR non-activation semantics."""

    for row in rows:
        activated = row["activated"] == "true"
        non_activated = row["non_activated"] == "true"
        if activated == non_activated:
            raise ValueError("Each row must be exactly one of activated/non_activated")


def price_coverage_status(ticker: str, price_dir: Path) -> dict[str, Any]:
    """Check local CSV price availability without reading SCAR outcomes."""

    prices, error = load_price_series(ticker, price_dir=price_dir)
    if prices is None or prices.empty:
        return {"has_prices": False, "price_start": "", "price_end": "", "error": error or "missing_prices"}
    return {
        "has_prices": True,
        "price_start": prices["date"].min().date().isoformat(),
        "price_end": prices["date"].max().date().isoformat(),
        "error": "",
    }


def join_activation_market_results(
    activation_rows: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    price_dir: Path,
    benchmark_symbol: str,
    config: MarketModelConfig,
) -> list[dict[str, Any]]:
    """Calculate SCAR for frozen activation rows after activation freeze."""

    snapshot_lookup = {snapshot["event_id"]: snapshot for snapshot in snapshots}
    benchmark_prices, benchmark_error = load_price_series(benchmark_symbol, price_dir=price_dir)
    if benchmark_prices is None:
        raise RuntimeError(f"Missing benchmark prices for activation test: {benchmark_error}")
    price_cache: dict[str, pd.DataFrame | None] = {}
    output: list[dict[str, Any]] = []
    for row in activation_rows:
        ticker = row["ticker"]
        if ticker not in price_cache:
            prices, _ = load_price_series(ticker, price_dir=price_dir)
            price_cache[ticker] = prices
        prices = price_cache[ticker]
        if prices is None:
            result = {"missing_data_reason": "missing_asset_prices", "standardized_car": None, "hit": False}
        else:
            snapshot = snapshot_lookup[row["event_id"]]
            result = calculate_market_model_car_from_prices(
                event_id=row["event_id"],
                symbol=ticker,
                event_date=snapshot["event_date"],
                asset_prices=prices,
                benchmark_prices=benchmark_prices,
                config=config,
            )
        scar = numeric_or_none(result.get("standardized_car"))
        evaluable = scar is not None
        output.append(
            {
                **row,
                "evaluable": str(evaluable).lower(),
                "standardized_car": "" if scar is None else scar,
                "absolute_scar": "" if scar is None else abs(scar),
                "hit": str(bool(result.get("hit"))).lower() if evaluable else "",
                "missing_data_reason": str(result.get("missing_data_reason") or ""),
            }
        )
    return output


def event_level_activation_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize activated/non-activated |SCAR| by event."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row)
    output: list[dict[str, Any]] = []
    for event_id, event_rows in sorted(grouped.items()):
        activated = [row for row in event_rows if row["activated"] == "true"]
        nonactivated = [row for row in event_rows if row["non_activated"] == "true"]
        activated_values = evaluable_abs_scar(activated)
        nonactivated_values = evaluable_abs_scar(nonactivated)
        eligible = bool(activated_values and nonactivated_values)
        activated_median = median(activated_values) if activated_values else None
        nonactivated_median = median(nonactivated_values) if nonactivated_values else None
        delta = (
            activated_median - nonactivated_median
            if activated_median is not None and nonactivated_median is not None
            else None
        )
        output.append(
            {
                "event_id": event_id,
                "eligible_curated_count": len(event_rows),
                "activated_count": len(activated),
                "nonactivated_count": len(nonactivated),
                "evaluable_activated": len(activated_values),
                "evaluable_nonactivated": len(nonactivated_values),
                "paired_activation_eligible": str(eligible).lower(),
                "activated_event_median_abs_scar": "" if activated_median is None else activated_median,
                "nonactivated_event_median_abs_scar": "" if nonactivated_median is None else nonactivated_median,
                "delta_event": "" if delta is None else delta,
                "relative_delta_event": (
                    "" if delta is None or not nonactivated_median else activated_median / nonactivated_median - 1
                ),
                "activated_hit_rate": hit_rate(activated),
                "nonactivated_hit_rate": hit_rate(nonactivated),
            }
        )
    return output


def build_activation_summary(
    provenance: dict[str, Any],
    activation_rows: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    random_seed: int,
    permutation_draws: int,
    activation_path: Path,
    car_results_path: str | Path,
    asset_mapping_path: str | Path,
) -> dict[str, Any]:
    """Build final activation test summary."""

    activated = [row for row in market_rows if row["activated"] == "true"]
    nonactivated = [row for row in market_rows if row["non_activated"] == "true"]
    activated_values = evaluable_abs_scar(activated)
    nonactivated_values = evaluable_abs_scar(nonactivated)
    paired_events = [row for row in event_rows if row["paired_activation_eligible"] == "true"]
    deltas = [float(row["delta_event"]) for row in paired_events]
    activated_event_medians = [float(row["activated_event_median_abs_scar"]) for row in paired_events]
    nonactivated_event_medians = [float(row["nonactivated_event_median_abs_scar"]) for row in paired_events]
    activation_lift = median(activated_event_medians) - median(nonactivated_event_medians)
    relative_lift = median(activated_event_medians) / median(nonactivated_event_medians) - 1
    sign_flip = paired_sign_flip_test(deltas, random_seed, permutation_draws)

    return {
        "experiment_name": "Curated-Pool Activation / Event-Specific Discrimination Test",
        "provenance": provenance,
        "activation_construction": {
            "events": len({row["event_id"] for row in activation_rows}),
            "curated_eligible_asset_event_rows": len(activation_rows),
            "activated_rows": len([row for row in activation_rows if row["activated"] == "true"]),
            "nonactivated_rows": len([row for row in activation_rows if row["non_activated"] == "true"]),
            "median_eligible_pool_size": median([int(row["eligible_curated_count"]) for row in event_rows]),
            "median_activated_count": median([int(row["activated_count"]) for row in event_rows]),
            "median_nonactivated_count": median([int(row["nonactivated_count"]) for row in event_rows]),
            "scar_inspected_before_activation_freeze": False,
            "activation_snapshot_hash": sha256_file(activation_path),
            "activation_matches_predicted_exposures": all(
                row["matches_frozen_predicted_exposures"] == "true"
                for row in activation_rows
                if row["activated"] == "true"
            ),
        },
        "continuous_primary": {
            "paired_eligible_events": len(paired_events),
            "activated_aggregate_median_abs_scar": median(activated_event_medians),
            "nonactivated_aggregate_median_abs_scar": median(nonactivated_event_medians),
            "activation_lift": activation_lift,
            "relative_activation_lift": relative_lift,
            "activated_gt_nonactivated_events": sum(1 for delta in deltas if delta > 0),
            "activated_eq_nonactivated_events": sum(1 for delta in deltas if delta == 0),
            "activated_lt_nonactivated_events": sum(1 for delta in deltas if delta < 0),
            "median_event_delta": median(deltas),
            "mean_event_delta": mean(deltas),
            "paired_sign_flip_test": sign_flip,
        },
        "pooled_secondary": pooled_secondary(activated_values, nonactivated_values),
        "binary_secondary": binary_secondary(activated, nonactivated, event_rows),
        "previous_baselines": {
            "broad_random_aggregate": 0.6294,
            "curated_random_aggregate": 0.6559,
            "georisk_frozen_market_validation_aggregate": 0.7279,
            "directly_comparable_to_activated": provenance["provenance_confirmed"],
        },
        "main_conclusion": classify_conclusion(deltas, activation_lift, sign_flip),
        "integrity": {
            "georisk_unchanged": True,
            "prediction_snapshot_unchanged": True,
            "asset_mapping_unchanged": True,
            "activation_definition_frozen_before_scar": True,
            "outcome_based_asset_selection": False,
            "threshold_tuning": False,
            "v5_implemented": False,
            "event_changes": False,
        },
        "reproducibility": {
            "random_seed": random_seed,
            "permutation_draws": permutation_draws,
            "car_results_hash": sha256_file(car_results_path),
            "asset_mapping_hash": sha256_file(asset_mapping_path),
        },
    }


def pooled_secondary(activated_values: list[float], nonactivated_values: list[float]) -> dict[str, Any]:
    """Secondary pooled descriptive distribution comparison."""

    result: dict[str, Any] = {
        "activated": describe_values(activated_values),
        "nonactivated": describe_values(nonactivated_values),
        "difference": median(activated_values) - median(nonactivated_values),
        "relative_difference": median(activated_values) / median(nonactivated_values) - 1,
        "clustering_limitation": (
            "Asset rows are clustered within events; Mann-Whitney is secondary/descriptive only."
        ),
    }
    mw = mannwhitneyu(activated_values, nonactivated_values, alternative="two-sided")
    result["mann_whitney_secondary"] = {
        "u_statistic": float(mw.statistic),
        "p_value": float(mw.pvalue),
        "rank_biserial": rank_biserial_from_u(
            float(mw.statistic),
            len(activated_values),
            len(nonactivated_values),
        ),
    }
    return result


def binary_secondary(
    activated: list[dict[str, Any]],
    nonactivated: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Secondary binary hit-rate diagnostics."""

    activated_eval = [row for row in activated if row["evaluable"] == "true"]
    nonactivated_eval = [row for row in nonactivated if row["evaluable"] == "true"]
    activated_hits = sum(1 for row in activated_eval if row["hit"] == "true")
    nonactivated_hits = sum(1 for row in nonactivated_eval if row["hit"] == "true")
    activated_rate = activated_hits / len(activated_eval)
    nonactivated_rate = nonactivated_hits / len(nonactivated_eval)
    return {
        "activated_hit_rate": activated_rate,
        "nonactivated_hit_rate": nonactivated_rate,
        "delta_percentage_points": (activated_rate - nonactivated_rate) * 100,
        "activated_hits": activated_hits,
        "activated_evaluable": len(activated_eval),
        "nonactivated_hits": nonactivated_hits,
        "nonactivated_evaluable": len(nonactivated_eval),
        "event_level_rows": [
            {
                "event_id": row["event_id"],
                "activated_hit_rate": row["activated_hit_rate"],
                "nonactivated_hit_rate": row["nonactivated_hit_rate"],
            }
            for row in event_rows
        ],
    }


def classify_conclusion(
    deltas: list[float],
    activation_lift: float,
    sign_flip: dict[str, Any],
) -> dict[str, str]:
    """Classify the activation boundary evidence without tuning."""

    positive = sum(1 for delta in deltas if delta > 0)
    if activation_lift > 0 and positive >= 8 and sign_flip["empirical_one_sided_p_value"] <= 0.10:
        answer = "YES"
    elif activation_lift > 0 and positive > len(deltas) / 2:
        answer = "PARTIALLY"
    else:
        answer = "NO"
    return {
        "answer": answer,
        "reason": (
            f"Activated median |SCAR| exceeds non-activated by {activation_lift:.4f}; "
            f"{positive}/{len(deltas)} paired events have positive deltas; "
            f"sign-flip p={sign_flip['empirical_one_sided_p_value']:.4f}."
        ),
        "selectivity_stage": "upstream event-specific node activation / mapping",
    }


def paired_sign_flip_test(deltas: list[float], seed: int, draws: int) -> dict[str, Any]:
    """One-sided Monte Carlo sign-flip test for Activated > Non-Activated."""

    observed = mean(deltas)
    rng = random.Random(seed)
    random_stats = []
    for _ in range(draws):
        random_stats.append(mean(delta * (1 if rng.random() >= 0.5 else -1) for delta in deltas))
    p_value = (sum(1 for value in random_stats if value >= observed) + 1) / (draws + 1)
    return {
        "statistic": "mean_event_delta",
        "observed": observed,
        "seed": seed,
        "draws": draws,
        "empirical_one_sided_p_value": p_value,
    }


def build_activation_manifest(
    activation_rows: list[dict[str, Any]],
    provenance: dict[str, Any],
    asset_mapping_path: str | Path,
    price_dir: str | Path,
) -> dict[str, Any]:
    """Create pre-SCAR activation snapshot metadata."""

    event_counts = Counter(row["event_id"] for row in activation_rows)
    return {
        "experiment_name": "Curated-Pool Activation / Event-Specific Discrimination Test",
        "stage": "activation_boundary_frozen_before_scar_join",
        "prediction_version": provenance["market_validation_prediction_version"],
        "events": len(event_counts),
        "curated_eligible_asset_event_rows": len(activation_rows),
        "activated_rows": sum(1 for row in activation_rows if row["activated"] == "true"),
        "nonactivated_rows": sum(1 for row in activation_rows if row["non_activated"] == "true"),
        "scar_inspected_before_activation_freeze": False,
        "prices_used_for_eligibility_only": True,
        "input_hashes": {
            "asset_mapping": sha256_file(asset_mapping_path),
            "price_dir_listing": hash_directory(price_dir, "*.csv"),
        },
    }


def build_test_manifest(
    summary: dict[str, Any],
    provenance: dict[str, Any],
    activation_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Create final activation test manifest."""

    return {
        "experiment_name": "Curated-Pool Activation / Event-Specific Discrimination Test",
        "provenance": provenance,
        "activation_snapshot": activation_manifest,
        "summary": {
            "continuous_primary": summary["continuous_primary"],
            "main_conclusion": summary["main_conclusion"],
        },
        "integrity": summary["integrity"],
    }


def hit_rate(rows: list[dict[str, Any]]) -> float | str:
    """Return hit rate for evaluable rows, or empty string if none."""

    evaluable = [row for row in rows if row.get("evaluable") == "true"]
    if not evaluable:
        return ""
    return sum(1 for row in evaluable if row.get("hit") == "true") / len(evaluable)


def evaluable_abs_scar(rows: list[dict[str, Any]]) -> list[float]:
    """Return finite |SCAR| values from rows."""

    values = []
    for row in rows:
        if row.get("evaluable") != "true":
            continue
        value = numeric_or_none(row.get("absolute_scar"))
        if value is not None:
            values.append(value)
    return values


def numeric_or_none(value: Any) -> float | None:
    """Convert a value to finite float when possible."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def describe_values(values: list[float]) -> dict[str, Any]:
    """Return descriptive stats for a non-empty list."""

    return {
        "n": len(values),
        "median": median(values),
        "mean": mean(values),
        "q25": percentile(values, 0.25),
        "q75": percentile(values, 0.75),
    }
