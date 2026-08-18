"""Evaluate additional baselines for the frozen V3 CAR experiment.

The baseline construction code is intentionally separated from GeoRisk model
logic. Random-matched sampling uses only frozen snapshot composition and
``data/asset_mapping.csv`` metadata. Node-only uses Event Analyst plus direct
node lookup through Market Mapper, and does not call retrieval, Transmission
Builder, or Evidence Agent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

import pandas as pd

from src.agents.event_analyst import analyze_event
from src.agents.market_mapper import map_assets
from src.schemas import TransmissionChain
from src.validation.car_calculator import (
    MarketModelConfig,
    calculate_market_model_car_from_prices,
    load_price_series,
)
from src.validation.exposure_evaluator import split_evaluated_and_skipped
from src.validation.price_preparation import prepare_price_csvs
from scripts.run_car_validation_v3 import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_PRICE_DIR,
    DEFAULT_RESULT_DIR as DEFAULT_CAR_RESULT_DIR,
    DEFAULT_SNAPSHOT_DIR,
    EXPECTED_MANIFEST_HASH,
    abs_scar_values,
    format_number,
    hit_rate_difference,
    load_v3_manifest,
    load_v3_snapshots,
    metric_row,
    overall_metrics,
    sha256_file,
    v3_integrity,
    write_csv,
    write_json,
)


DEFAULT_OUTPUT_DIR = Path("data/baseline_v3")
DEFAULT_ASSET_MAPPING = Path("data/asset_mapping.csv")
DEFAULT_RANDOM_RUNS = 1000
DEFAULT_RANDOM_SEED = 20260805


def evaluate_v3_additional_baselines(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    car_result_dir: str | Path = DEFAULT_CAR_RESULT_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    asset_mapping_path: str | Path = DEFAULT_ASSET_MAPPING,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    benchmark_symbol: str = "SPY",
    random_runs: int = DEFAULT_RANDOM_RUNS,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    """Run random-matched and node-only baseline evaluation."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = MarketModelConfig()
    manifest = load_v3_manifest(manifest_path)
    manifest_hash_before = sha256_file(manifest_path)
    snapshots = load_v3_snapshots(manifest, snapshot_dir)
    snapshot_hashes_before = {snapshot["_path"]: sha256_file(snapshot["_path"]) for snapshot in snapshots}
    integrity_before = v3_integrity(manifest, snapshots, manifest_hash_before)
    if integrity_before["errors"]:
        raise RuntimeError(f"V3 integrity failed before baseline evaluation: {integrity_before['errors']}")

    asset_universe = load_asset_universe(asset_mapping_path)
    event_dates = [str(snapshot["event_date"]) for snapshot in snapshots]
    price_preparation = prepare_price_csvs(
        symbols=[
            *[row["ticker"] for row in asset_universe],
            benchmark_symbol,
        ],
        event_dates=event_dates,
        price_dir=price_dir,
        config=config,
    )
    price_cache = load_price_cache(asset_universe, snapshots, price_dir, benchmark_symbol)
    car_lookup = precompute_event_symbol_car_lookup(
        snapshots,
        asset_universe,
        price_cache,
        benchmark_symbol,
        config,
    )
    full_georisk_rows, fixed_baseline_rows = load_existing_v3_car_rows(car_result_dir)

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
    node_only_result = evaluate_node_only_baseline(
        snapshots=snapshots,
        price_cache=price_cache,
        car_lookup=car_lookup,
        benchmark_symbol=benchmark_symbol,
        config=config,
    )
    incremental = incremental_value_rows(full_georisk_rows, node_only_result["evaluated_rows"])
    comparison = comparison_rows(
        full_georisk_rows,
        node_only_result["evaluated_rows"],
        fixed_baseline_rows,
        random_result["run_rows"],
    )
    event_comparison = event_level_comparison(
        snapshots,
        full_georisk_rows,
        node_only_result["evaluated_rows"],
        random_result["event_run_rows"],
    )

    write_json(
        output / "random_matched_config.json",
        {
            "runs": random_runs,
            "random_seed": random_seed,
            "candidate_asset_universe_rows": len(asset_universe),
            "candidate_asset_universe_unique_symbols": len({row["ticker"] for row in asset_universe}),
            "matching_constraints": [
                "same per-event exposure count as frozen GeoRisk scope when feasible",
                "match asset_type distribution as closely as feasible",
                "exclude event-specific GeoRisk symbols",
                "exclude benchmark SPY",
                "deduplicate symbols within each draw",
            ],
            "forbidden_sampling_inputs": [
                "CAR",
                "standardized_car",
                "returns",
                "future prices",
                "hit outcomes",
                "linkage_tier",
                "evidence_label",
            ],
            "price_preparation": price_preparation,
        },
    )
    write_csv(output / "random_matched_runs.csv", random_result["run_rows"])
    write_json(output / "random_matched_summary.json", random_result["summary"])
    write_csv(output / "random_matched_event_summary.csv", random_result["event_summary_rows"])
    write_csv(output / "node_only_predictions.csv", node_only_result["prediction_rows"])
    write_csv(output / "node_only_car_results.csv", node_only_result["evaluated_rows"] + node_only_result["skipped_rows"])
    write_json(output / "node_only_summary.json", node_only_result["summary"])
    write_csv(output / "baseline_comparison.csv", comparison)
    write_csv(output / "incremental_value_analysis.csv", incremental)
    write_csv(output / "event_level_baseline_comparison.csv", event_comparison["rows"])

    integrity_after = {
        "manifest_hash_after": sha256_file(manifest_path),
        "snapshot_hashes_after": {snapshot["_path"]: sha256_file(snapshot["_path"]) for snapshot in snapshots},
    }
    integrity_report = {
        **integrity_before,
        **integrity_after,
        "manifest_unchanged": integrity_after["manifest_hash_after"] == manifest_hash_before,
        "snapshots_unchanged": integrity_after["snapshot_hashes_after"] == snapshot_hashes_before,
        "expected_manifest_hash": EXPECTED_MANIFEST_HASH,
        "random_seed": random_seed,
        "random_baseline_excludes_event_georisk_symbols": True,
        "random_baseline_uses_car_for_sampling": False,
        "node_only_calls_historical_retrieval": False,
        "node_only_calls_transmission_builder": False,
        "node_only_calls_evidence_agent": False,
        "node_only_allowed_components": [
            "Event Analyst",
            "direct first-order supply_chain_nodes",
            "Market Mapper asset_mapping.csv lookup",
        ],
    }
    write_json(output / "integrity_report.json", integrity_report)

    return {
        "random": random_result["summary"],
        "node_only": node_only_result["summary"],
        "comparison": comparison,
        "incremental": incremental,
        "event_comparison": event_comparison["summary"],
        "integrity": integrity_report,
        "output_dir": str(output),
    }


def load_asset_universe(path: str | Path) -> list[dict[str, Any]]:
    """Load the asset-mapping rows used as random-sampling universe."""

    with Path(path).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if row.get("ticker") and row["ticker"].upper() != "SPY"]


def load_price_cache(
    asset_universe: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    price_dir: str | Path,
    benchmark_symbol: str,
) -> dict[str, pd.DataFrame | None]:
    """Load local price CSVs once for all baseline calculations."""

    symbols = {benchmark_symbol}
    symbols.update(row["ticker"].upper() for row in asset_universe)
    for snapshot in snapshots:
        symbols.update(e["symbol"].upper() for e in snapshot.get("predicted_exposures", []))
        symbols.update(b["symbol"].upper() for b in snapshot.get("baseline_exposures", []))
    cache: dict[str, pd.DataFrame | None] = {}
    for symbol in sorted(symbols):
        prices, _ = load_price_series(symbol, price_dir=price_dir)
        cache[symbol] = prices
    return cache


def load_existing_v3_car_rows(car_result_dir: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load evaluated full GeoRisk and fixed ETF control rows from V3 CAR output."""

    rows = list(csv.DictReader((Path(car_result_dir) / "car_pair_results.csv").open(encoding="utf-8")))
    evaluated = [coerce_car_row(row) for row in rows if not row.get("missing_data_reason")]
    return (
        [row for row in evaluated if row.get("source") == "georisk"],
        [row for row in evaluated if row.get("source") == "baseline"],
    )


def evaluate_random_matched_baseline(
    snapshots: list[dict[str, Any]],
    asset_universe: list[dict[str, Any]],
    price_cache: dict[str, pd.DataFrame | None],
    car_lookup: dict[tuple[str, str], dict[str, Any]],
    benchmark_symbol: str,
    config: MarketModelConfig,
    runs: int,
    seed: int,
) -> dict[str, Any]:
    """Run deterministic Monte Carlo random-matched baseline evaluation."""

    rng = random.Random(seed)
    universe_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in asset_universe:
        universe_by_type[row["asset_type"]].append(row)
    for rows in universe_by_type.values():
        rows.sort(key=lambda item: (item["ticker"], item["supply_chain_node"]))

    run_rows: list[dict[str, Any]] = []
    event_run_rows: list[dict[str, Any]] = []
    mismatch_rows: list[dict[str, Any]] = []
    scopes = ["all", "first_order", "second_order"]
    for run_id in range(runs):
        run_scope_results: dict[str, list[dict[str, Any]]] = {scope: [] for scope in scopes}
        event_scope_results: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for snapshot in snapshots:
            for scope in scopes:
                georisk = scoped_georisk_exposures(snapshot, scope)
                sampled, mismatches = random_matched_draw(
                    georisk,
                    universe_by_type,
                    rng,
                    benchmark_symbol,
                    run_id,
                    snapshot["event_id"],
                    scope,
                )
                if mismatches:
                    mismatch_rows.extend(mismatches)
                rows = calculate_exposure_rows(
                    sampled,
                    event_id=snapshot["event_id"],
                    event_date=snapshot["event_date"],
                    event_headline=snapshot.get("headline", ""),
                    event_type=snapshot.get("event_type", ""),
                    source="random_matched",
                    price_cache=price_cache,
                    car_lookup=car_lookup,
                    benchmark_symbol=benchmark_symbol,
                    config=config,
                )
                evaluated, skipped = split_evaluated_and_skipped(rows)
                run_scope_results[scope].extend(evaluated)
                event_scope_results[(snapshot["event_id"], scope)].extend(evaluated)
                event_scope_results[(snapshot["event_id"], f"{scope}__skipped")].extend(skipped)
        for scope in scopes:
            metric = metric_row(run_scope_results[scope])
            skipped_count = sum(
                len(rows)
                for (event_id, key_scope), rows in event_scope_results.items()
                if key_scope == f"{scope}__skipped"
            )
            run_rows.append({"run_id": run_id, "scope": scope, "skipped": skipped_count, **metric})
        for (event_id, scope), rows in event_scope_results.items():
            if scope.endswith("__skipped"):
                continue
            metric = metric_row(rows)
            event_run_rows.append({"run_id": run_id, "event_id": event_id, "scope": scope, **metric})

    summary = random_summary(run_rows, event_run_rows, mismatch_rows)
    return {
        "run_rows": run_rows,
        "event_run_rows": event_run_rows,
        "event_summary_rows": random_event_summary(event_run_rows),
        "summary": summary,
    }


def random_matched_draw(
    georisk_exposures: list[dict[str, Any]],
    universe_by_type: dict[str, list[dict[str, Any]]],
    rng: random.Random,
    benchmark_symbol: str,
    run_id: int,
    event_id: str,
    scope: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Draw a same-size random baseline with closest feasible asset-type match."""

    excluded_symbols = {e["symbol"].upper() for e in georisk_exposures}
    excluded_symbols.add(benchmark_symbol.upper())
    target_by_type = Counter(e.get("asset_type") or "unknown" for e in georisk_exposures)
    selected: list[dict[str, Any]] = []
    selected_symbols: set[str] = set()
    mismatches: list[dict[str, Any]] = []
    for asset_type, target in sorted(target_by_type.items()):
        candidates = [
            row for row in universe_by_type.get(asset_type, [])
            if row["ticker"].upper() not in excluded_symbols
            and row["ticker"].upper() not in selected_symbols
        ]
        take = min(target, len(candidates))
        if take < target:
            mismatches.append(
                {
                    "run_id": run_id,
                    "event_id": event_id,
                    "scope": scope,
                    "asset_type": asset_type,
                    "target": target,
                    "selected": take,
                    "reason": "insufficient_non_georisk_universe_for_asset_type",
                }
            )
        for row in rng.sample(candidates, take) if take else []:
            selected_symbols.add(row["ticker"].upper())
            selected.append(random_exposure_from_mapping(row, scope))
    deficit = len(georisk_exposures) - len(selected)
    if deficit > 0:
        fallback = [
            row for rows in universe_by_type.values() for row in rows
            if row["ticker"].upper() not in excluded_symbols
            and row["ticker"].upper() not in selected_symbols
        ]
        take = min(deficit, len(fallback))
        for row in rng.sample(fallback, take) if take else []:
            selected_symbols.add(row["ticker"].upper())
            selected.append(random_exposure_from_mapping(row, scope))
        if take < deficit:
            mismatches.append(
                {
                    "run_id": run_id,
                    "event_id": event_id,
                    "scope": scope,
                    "asset_type": "ANY",
                    "target": deficit,
                    "selected": take,
                    "reason": "insufficient_total_non_georisk_universe",
                }
            )
    return selected, mismatches


def random_exposure_from_mapping(row: dict[str, Any], scope: str) -> dict[str, Any]:
    """Convert an asset-mapping row into a random baseline exposure."""

    return {
        "symbol": row["ticker"].upper(),
        "node": row["supply_chain_node"],
        "asset_type": row["asset_type"],
        "linkage_tier": row.get("linkage_tier"),
        "linkage_rationale": row.get("linkage_rationale"),
        "transmission_order": scope if scope in {"first_order", "second_order"} else None,
        "baseline_type": f"random_matched_{scope}",
        "selection_rationale": "deterministic_seeded_asset_type_matched_random_draw",
    }


def evaluate_node_only_baseline(
    snapshots: list[dict[str, Any]],
    price_cache: dict[str, pd.DataFrame | None],
    car_lookup: dict[tuple[str, str], dict[str, Any]],
    benchmark_symbol: str,
    config: MarketModelConfig,
) -> dict[str, Any]:
    """Evaluate direct Event Analyst node lookup without RAG/transmission/evidence."""

    prediction_rows: list[dict[str, Any]] = []
    car_rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        event = analyze_event(snapshot["event_description"])
        direct_chain = TransmissionChain(
            affected_nodes=list(event.supply_chain_nodes),
            rationale="Node-only ablation: direct Event Analyst nodes only.",
        )
        assets = map_assets(event, direct_chain)
        seen: set[str] = set()
        exposures: list[dict[str, Any]] = []
        for asset in assets:
            symbol = (asset.ticker or asset.asset_id).upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            exposure = {
                "event_id": snapshot["event_id"],
                "event_date": snapshot["event_date"],
                "event_headline": snapshot.get("headline", ""),
                "symbol": symbol,
                "node": asset.supply_chain_node,
                "asset_type": asset.asset_type,
                "linkage_tier": asset.linkage_tier,
                "linkage_rationale": asset.linkage_rationale,
                "baseline_type": "node_only_direct_mapping",
                "selection_rationale": "node_only_direct_mapping",
                "source": "node_only",
                "direct_first_order_nodes": ";".join(event.supply_chain_nodes),
            }
            exposures.append(exposure)
            prediction_rows.append(exposure)
        car_rows.extend(
            calculate_exposure_rows(
                exposures,
                event_id=snapshot["event_id"],
                event_date=snapshot["event_date"],
                event_headline=snapshot.get("headline", ""),
                event_type=snapshot.get("event_type", ""),
                source="node_only",
                price_cache=price_cache,
                car_lookup=car_lookup,
                benchmark_symbol=benchmark_symbol,
                config=config,
            )
        )
    evaluated, skipped = split_evaluated_and_skipped(car_rows)
    return {
        "prediction_rows": prediction_rows,
        "evaluated_rows": evaluated,
        "skipped_rows": skipped,
        "summary": {
            "total_predictions": len(prediction_rows),
            "evaluated_pairs": len(evaluated),
            "skipped_pairs": len(skipped),
            **metric_row(evaluated),
        },
    }


def calculate_exposure_rows(
    exposures: list[dict[str, Any]],
    event_id: str,
    event_date: str,
    event_headline: str,
    event_type: str,
    source: str,
    price_cache: dict[str, pd.DataFrame | None],
    car_lookup: dict[tuple[str, str], dict[str, Any]] | None,
    benchmark_symbol: str,
    config: MarketModelConfig,
) -> list[dict[str, Any]]:
    """Calculate CAR rows for baseline exposures using cached local prices."""

    benchmark_prices = price_cache.get(benchmark_symbol.upper())
    rows: list[dict[str, Any]] = []
    for exposure in exposures:
        symbol = exposure["symbol"].upper()
        if car_lookup is not None and (event_id, symbol) in car_lookup:
            result = dict(car_lookup[(event_id, symbol)])
        elif symbol == benchmark_symbol.upper():
            result = {
                "event_id": event_id,
                "symbol": symbol,
                "car": None,
                "standardized_car": None,
                "hit": False,
                "direction": None,
                "missing_data_reason": "asset_equals_benchmark",
                "benchmark": benchmark_symbol,
            }
        elif price_cache.get(symbol) is None:
            result = {
                "event_id": event_id,
                "symbol": symbol,
                "car": None,
                "standardized_car": None,
                "hit": False,
                "direction": None,
                "missing_data_reason": "missing_asset_prices",
            }
        elif benchmark_prices is None:
            result = {
                "event_id": event_id,
                "symbol": symbol,
                "car": None,
                "standardized_car": None,
                "hit": False,
                "direction": None,
                "missing_data_reason": "missing_benchmark_prices",
            }
        else:
            result = calculate_market_model_car_from_prices(
                event_id=event_id,
                symbol=symbol,
                event_date=event_date,
                asset_prices=price_cache[symbol],
                benchmark_prices=benchmark_prices,
                config=config,
            )
        rows.append(
            {
                **result,
                "event_date": event_date,
                "event_headline": event_headline,
                "event_type": event_type,
                "node": exposure.get("node"),
                "asset_type": exposure.get("asset_type"),
                "linkage_tier": exposure.get("linkage_tier"),
                "linkage_rationale": exposure.get("linkage_rationale"),
                "source": source,
                "transmission_order": exposure.get("transmission_order"),
                "baseline_type": exposure.get("baseline_type"),
                "selection_rationale": exposure.get("selection_rationale"),
            }
        )
    return rows


def precompute_event_symbol_car_lookup(
    snapshots: list[dict[str, Any]],
    asset_universe: list[dict[str, Any]],
    price_cache: dict[str, pd.DataFrame | None],
    benchmark_symbol: str,
    config: MarketModelConfig,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Precompute CAR once for every V3 event and asset-universe symbol."""

    symbols = {row["ticker"].upper() for row in asset_universe}
    for snapshot in snapshots:
        symbols.update(e["symbol"].upper() for e in snapshot.get("predicted_exposures", []))
        symbols.update(b["symbol"].upper() for b in snapshot.get("baseline_exposures", []))
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    benchmark_prices = price_cache.get(benchmark_symbol.upper())
    for snapshot in snapshots:
        for symbol in sorted(symbols):
            if symbol == benchmark_symbol.upper():
                lookup[(snapshot["event_id"], symbol)] = {
                    "event_id": snapshot["event_id"],
                    "symbol": symbol,
                    "car": None,
                    "standardized_car": None,
                    "hit": False,
                    "direction": None,
                    "missing_data_reason": "asset_equals_benchmark",
                    "benchmark": benchmark_symbol,
                }
            elif price_cache.get(symbol) is None:
                lookup[(snapshot["event_id"], symbol)] = {
                    "event_id": snapshot["event_id"],
                    "symbol": symbol,
                    "car": None,
                    "standardized_car": None,
                    "hit": False,
                    "direction": None,
                    "missing_data_reason": "missing_asset_prices",
                }
            elif benchmark_prices is None:
                lookup[(snapshot["event_id"], symbol)] = {
                    "event_id": snapshot["event_id"],
                    "symbol": symbol,
                    "car": None,
                    "standardized_car": None,
                    "hit": False,
                    "direction": None,
                    "missing_data_reason": "missing_benchmark_prices",
                }
            else:
                lookup[(snapshot["event_id"], symbol)] = calculate_market_model_car_from_prices(
                    event_id=snapshot["event_id"],
                    symbol=symbol,
                    event_date=snapshot["event_date"],
                    asset_prices=price_cache[symbol],
                    benchmark_prices=benchmark_prices,
                    config=config,
                )
    return lookup


def scoped_georisk_exposures(snapshot: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    """Return frozen GeoRisk exposures for one comparison scope."""

    exposures = list(snapshot.get("predicted_exposures", []))
    if scope == "first_order":
        return [e for e in exposures if e.get("transmission_order") == "first_order"]
    if scope == "second_order":
        return [e for e in exposures if e.get("transmission_order") == "second_order"]
    return exposures


def random_summary(
    run_rows: list[dict[str, Any]],
    event_run_rows: list[dict[str, Any]],
    mismatch_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize Monte Carlo distributions by scope."""

    summary: dict[str, Any] = {"scopes": {}, "matching_mismatches": mismatch_rows[:200], "matching_mismatch_count": len(mismatch_rows)}
    actual = existing_georisk_scope_metrics()
    for scope in ["all", "first_order", "second_order"]:
        scope_rows = [row for row in run_rows if row["scope"] == scope]
        summary["scopes"][scope] = {
            "hit_rate": distribution_summary([float(row["hit_rate"]) for row in scope_rows]),
            "mean_abs_SCAR": distribution_summary([float(row["mean_abs_SCAR"]) for row in scope_rows]),
            "median_abs_SCAR": distribution_summary([float(row["median_abs_SCAR"]) for row in scope_rows]),
            "actual_georisk": actual[scope],
            "actual_georisk_percentile_rank_hit_rate": percentile_rank(
                [float(row["hit_rate"]) for row in scope_rows],
                actual[scope]["hit_rate"],
            ),
            "actual_georisk_percentile_rank_mean_abs_SCAR": percentile_rank(
                [float(row["mean_abs_SCAR"]) for row in scope_rows],
                actual[scope]["mean_abs_SCAR"],
            ),
            "actual_georisk_percentile_rank_median_abs_SCAR": percentile_rank(
                [float(row["median_abs_SCAR"]) for row in scope_rows],
                actual[scope]["median_abs_SCAR"],
            ),
        }
    return summary


def random_event_summary(event_run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate Monte Carlo event-level rows for all-exposure scope."""

    rows = [row for row in event_run_rows if row["scope"] == "all"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row)
    output = []
    geo = existing_georisk_event_metrics()
    for event_id in sorted(grouped):
        hit_rates = [
            float(row["hit_rate"])
            for row in grouped[event_id]
            if row.get("hit_rate") is not None
        ]
        mean_abs = [
            float(row["mean_abs_SCAR"])
            for row in grouped[event_id]
            if row.get("mean_abs_SCAR") is not None
        ]
        output.append(
            {
                "event_id": event_id,
                "georisk_exposure_count": geo[event_id]["evaluated"],
                "georisk_hit_rate": geo[event_id]["hit_rate"],
                "random_baseline_mean_hit_rate": mean(hit_rates) if hit_rates else None,
                "random_baseline_median_hit_rate": median(hit_rates) if hit_rates else None,
                "georisk_mean_abs_SCAR": geo[event_id]["mean_abs_SCAR"],
                "random_baseline_mean_abs_SCAR": mean(mean_abs) if mean_abs else None,
            }
        )
    return output


def existing_georisk_scope_metrics() -> dict[str, dict[str, Any]]:
    """Read current V3 GeoRisk metrics for random-baseline percentile comparison."""

    rows, _ = load_existing_v3_car_rows(DEFAULT_CAR_RESULT_DIR)
    return {
        "all": metric_row(rows),
        "first_order": metric_row([row for row in rows if row.get("transmission_order") == "first_order"]),
        "second_order": metric_row([row for row in rows if row.get("transmission_order") == "second_order"]),
    }


def existing_georisk_event_metrics() -> dict[str, dict[str, Any]]:
    rows, _ = load_existing_v3_car_rows(DEFAULT_CAR_RESULT_DIR)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row)
    return {event_id: metric_row(event_rows) for event_id, event_rows in grouped.items()}


def comparison_rows(
    georisk: list[dict[str, Any]],
    node_only: list[dict[str, Any]],
    fixed_baseline: list[dict[str, Any]],
    random_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build system-level comparison table."""

    random_all = [row for row in random_runs if row["scope"] == "all"]
    random_mean = {
        "evaluated": mean(float(row["evaluated"]) for row in random_all),
        "hits": mean(float(row["hits"]) for row in random_all),
        "hit_rate": mean(float(row["hit_rate"]) for row in random_all),
        "mean_abs_SCAR": mean(float(row["mean_abs_SCAR"]) for row in random_all),
        "median_abs_SCAR": mean(float(row["median_abs_SCAR"]) for row in random_all),
    }
    rows = [
        {"system": "Full GeoRisk", **metric_row(georisk)},
        {"system": "Node-Only Baseline", **metric_row(node_only)},
        {"system": "Fixed ETF Control", **metric_row(fixed_baseline)},
        {"system": "Random-Matched Baseline mean over 1000 runs", **random_mean},
    ]
    for row in rows:
        row["georisk_minus_system_hit_rate"] = (
            metric_row(georisk)["hit_rate"] - row["hit_rate"]
            if row["hit_rate"] is not None
            else None
        )
    return rows


def incremental_value_rows(
    georisk_rows: list[dict[str, Any]],
    node_only_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare Full GeoRisk rows that overlap node-only vs incremental rows."""

    node_keys = {(row["event_id"], row["symbol"]) for row in node_only_rows}
    overlap = [row for row in georisk_rows if (row["event_id"], row["symbol"]) in node_keys]
    incremental = [row for row in georisk_rows if (row["event_id"], row["symbol"]) not in node_keys]
    incremental_second = [row for row in incremental if row.get("transmission_order") == "second_order"]
    return [
        {"group": "node_only_overlap", **metric_row(overlap)},
        {"group": "georisk_incremental_exposures", **metric_row(incremental)},
        {"group": "georisk_incremental_second_order", **metric_row(incremental_second)},
    ]


def event_level_comparison(
    snapshots: list[dict[str, Any]],
    georisk_rows: list[dict[str, Any]],
    node_only_rows: list[dict[str, Any]],
    random_event_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare event-level hit presence across systems."""

    random_all = [row for row in random_event_runs if row["scope"] == "all"]
    random_hits_by_event: dict[str, list[float]] = defaultdict(list)
    for row in random_all:
        random_hits_by_event[row["event_id"]].append(float(row["hits"]))
    rows = []
    categories = Counter()
    for snapshot in snapshots:
        event_id = snapshot["event_id"]
        geo = [row for row in georisk_rows if row["event_id"] == event_id]
        node = [row for row in node_only_rows if row["event_id"] == event_id]
        geo_hit = any(row.get("hit") for row in geo)
        node_hit = any(row.get("hit") for row in node)
        if geo_hit and not node_hit:
            categories["georisk_hit_node_only_no_hit"] += 1
        elif node_hit and not geo_hit:
            categories["node_only_hit_georisk_no_hit"] += 1
        elif geo_hit and node_hit:
            categories["both_hit"] += 1
        else:
            categories["neither_hit"] += 1
        rows.append(
            {
                "event_id": event_id,
                "georisk_evaluated": len(geo),
                "georisk_hits": sum(1 for row in geo if row.get("hit")),
                "node_only_evaluated": len(node),
                "node_only_hits": sum(1 for row in node if row.get("hit")),
                "random_baseline_mean_hits": mean(random_hits_by_event[event_id]) if random_hits_by_event[event_id] else None,
                "georisk_had_at_least_one_hit": geo_hit,
                "node_only_had_at_least_one_hit": node_hit,
            }
        )
    return {"rows": rows, "summary": dict(categories)}


def distribution_summary(values: list[float]) -> dict[str, float]:
    """Return mean, median, std, and quantiles for Monte Carlo values."""

    ordered = sorted(values)
    return {
        "mean": mean(ordered),
        "median": median(ordered),
        "std": pstdev(ordered),
        "p05": quantile(ordered, 0.05),
        "p25": quantile(ordered, 0.25),
        "p75": quantile(ordered, 0.75),
        "p95": quantile(ordered, 0.95),
        "min": min(ordered),
        "max": max(ordered),
    }


def quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated quantile for sorted values."""

    if not sorted_values:
        return float("nan")
    pos = (len(sorted_values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = pos - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def percentile_rank(values: list[float], actual: float | None) -> float | None:
    """Return percentage of Monte Carlo values less than or equal to actual."""

    if actual is None or not values:
        return None
    return sum(1 for value in values if value <= actual) / len(values)


def coerce_car_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert CSV strings to useful scalar types for metric aggregation."""

    converted = dict(row)
    for field in ["car", "standardized_car", "confidence", "alpha", "beta"]:
        if converted.get(field) in {"", None}:
            converted[field] = None
        else:
            converted[field] = float(converted[field])
    converted["hit"] = str(converted.get("hit")).lower() == "true"
    return converted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate V3 random and node-only baselines.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR))
    parser.add_argument("--car-result-dir", default=str(DEFAULT_CAR_RESULT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--asset-mapping", default=str(DEFAULT_ASSET_MAPPING))
    parser.add_argument("--price-dir", default=str(DEFAULT_PRICE_DIR))
    parser.add_argument("--benchmark-symbol", default="SPY")
    parser.add_argument("--random-runs", type=int, default=DEFAULT_RANDOM_RUNS)
    parser.add_argument("--random-seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = evaluate_v3_additional_baselines(
        manifest_path=args.manifest,
        snapshot_dir=args.snapshot_dir,
        car_result_dir=args.car_result_dir,
        output_dir=args.output_dir,
        asset_mapping_path=args.asset_mapping,
        price_dir=args.price_dir,
        benchmark_symbol=args.benchmark_symbol,
        random_runs=args.random_runs,
        random_seed=args.random_seed,
    )
    random_all = result["random"]["scopes"]["all"]
    node = result["node_only"]
    print("V3 additional baseline evaluation complete.")
    print(f"random_runs: {args.random_runs}")
    print(f"random_seed: {args.random_seed}")
    print(f"random_mean_hit_rate: {format_number(random_all['hit_rate']['mean'])}")
    print(f"random_p05_p95_hit_rate: {format_number(random_all['hit_rate']['p05'])} - {format_number(random_all['hit_rate']['p95'])}")
    print(f"node_only_predictions: {node['total_predictions']}")
    print(f"node_only_hit_rate: {format_number(node['hit_rate'])}")
    print(f"output_dir: {result['output_dir']}")


if __name__ == "__main__":
    main()
