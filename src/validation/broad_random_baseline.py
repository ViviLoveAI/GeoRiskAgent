"""Broad-market random baseline for frozen GeoRisk CAR validation.

The broad baseline samples from a pre-defined broad U.S. equity universe rather
than from GeoRisk's curated asset ontology. It keeps event inputs, GeoRisk
predictions, CAR/SCAR formulas, event windows, and hit threshold unchanged.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd

from scripts.run_car_validation_v3 import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_PRICE_DIR,
    DEFAULT_RESULT_DIR as DEFAULT_CAR_RESULT_DIR,
    load_v3_manifest,
    load_v3_snapshots,
    metric_row,
)
from src.validation.car_calculator import (
    MarketModelConfig,
    calculate_market_model_car_from_prices,
    load_price_series,
)
from src.validation.price_preparation import (
    calculate_required_price_range,
    has_sufficient_coverage,
    normalize_price_frame,
)


OUTPUT_DIR = Path("data/market_validation/broad_random")
UNIVERSE_PATH = OUTPUT_DIR / "broad_market_universe.csv"
UNIVERSE_MANIFEST_PATH = OUTPUT_DIR / "broad_market_universe_manifest.json"
UNIVERSE_CHECKSUMS_PATH = OUTPUT_DIR / "broad_market_universe_checksums.json"
PRICE_DIR = OUTPUT_DIR / "prices"
MANIFEST_PATH = OUTPUT_DIR / "broad_random_manifest.json"
FULL_RESULTS_PATH = OUTPUT_DIR / "broad_random_full_results.csv"
EX_CURATED_RESULTS_PATH = OUTPUT_DIR / "broad_random_ex_curated_results.csv"
EVENT_COMPARISON_PATH = OUTPUT_DIR / "event_level_comparison.csv"
SUMMARY_PATH = OUTPUT_DIR / "broad_random_summary.json"

ASSET_MAPPING_PATH = Path("data/asset_mapping.csv")
CURATED_CONTINUOUS_SUMMARY_PATH = Path("data/market_validation/scar_continuous_test/continuous_scar_summary.json")
CURATED_BINARY_SUMMARY_PATH = Path("data/baseline_v3/random_matched_summary.json")
SP500_SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
BENCHMARK_SYMBOL = "SPY"
RANDOM_SEED = 20260805
MC_DRAWS = 1000
MIN_ELIGIBLE_MULTIPLE = 5


def run_broad_market_random_baseline(
    output_dir: str | Path = OUTPUT_DIR,
    random_seed: int = RANDOM_SEED,
    draws: int = MC_DRAWS,
) -> dict[str, Any]:
    """Build broad universe, run full/ex-curated MC baselines, and write artifacts."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    price_dir = output / "prices"
    price_dir.mkdir(parents=True, exist_ok=True)

    config = MarketModelConfig()
    manifest = load_v3_manifest(DEFAULT_MANIFEST_PATH)
    snapshots = load_v3_snapshots(manifest, "data/validation_v3/prediction_snapshots")
    georisk_rows = load_georisk_rows(DEFAULT_CAR_RESULT_DIR)
    event_counts = Counter(row["event_id"] for row in georisk_rows)
    max_required_n = max(event_counts.values())
    event_dates = [snapshot["event_date"] for snapshot in snapshots]
    required_start, required_end, invalid_dates = calculate_required_price_range(event_dates, config)
    if invalid_dates or required_start is None or required_end is None:
        raise RuntimeError(f"Invalid event dates for broad baseline: {invalid_dates}")

    constituents = fetch_sp500_constituents()
    price_report = ensure_broad_price_csvs(
        constituents,
        price_dir=price_dir,
        start=required_start,
        end=required_end,
    )
    benchmark_prices, benchmark_error = load_price_series(BENCHMARK_SYMBOL, price_dir=DEFAULT_PRICE_DIR)
    if benchmark_prices is None:
        raise RuntimeError(f"Missing benchmark prices: {benchmark_error}")

    curated_symbols = load_asset_mapping_symbols(ASSET_MAPPING_PATH)
    georisk_symbols_by_event = symbols_by_event(georisk_rows)
    universe_rows = build_universe_rows(
        constituents=constituents,
        price_dir=price_dir,
        snapshots=snapshots,
        benchmark_prices=benchmark_prices,
        config=config,
        curated_symbols=curated_symbols,
    )
    write_csv(output / "broad_market_universe.csv", universe_rows)
    universe_checksums = {
        "broad_market_universe.csv": sha256_file(output / "broad_market_universe.csv"),
    }
    write_json(output / "broad_market_universe_checksums.json", universe_checksums)

    eligible_by_event = eligible_symbols_by_event(universe_rows)
    validate_event_eligibility(eligible_by_event, event_counts, max_required_n)
    broad_car_lookup = precompute_broad_car_lookup(
        snapshots=snapshots,
        symbols=sorted({symbol for symbols in eligible_by_event.values() for symbol in symbols}),
        price_dir=price_dir,
        benchmark_prices=benchmark_prices,
        config=config,
    )

    full = run_broad_mc(
        baseline_name="Broad Random Full",
        snapshots=snapshots,
        eligible_by_event=eligible_by_event,
        georisk_symbols_by_event=georisk_symbols_by_event,
        event_counts=event_counts,
        car_lookup=broad_car_lookup,
        random_seed=random_seed,
        draws=draws,
        exclude_curated=False,
        curated_symbols=curated_symbols,
    )
    ex_curated = run_broad_mc(
        baseline_name="Broad Random Ex-Curated",
        snapshots=snapshots,
        eligible_by_event=eligible_by_event,
        georisk_symbols_by_event=georisk_symbols_by_event,
        event_counts=event_counts,
        car_lookup=broad_car_lookup,
        random_seed=random_seed,
        draws=draws,
        exclude_curated=True,
        curated_symbols=curated_symbols,
    )

    georisk_event = georisk_event_rows(georisk_rows)
    curated_summary = json.loads(CURATED_CONTINUOUS_SUMMARY_PATH.read_text())
    curated_event = load_curated_event_continuous()
    event_comparison = event_comparison_rows(georisk_event, curated_event, full, ex_curated)
    summary = build_summary(
        universe_rows=universe_rows,
        curated_symbols=curated_symbols,
        georisk_rows=georisk_rows,
        full=full,
        ex_curated=ex_curated,
        curated_summary=curated_summary,
        event_comparison=event_comparison,
        random_seed=random_seed,
        draws=draws,
        price_report=price_report,
    )

    write_csv(output / "broad_random_full_results.csv", full["run_rows"])
    write_csv(output / "broad_random_ex_curated_results.csv", ex_curated["run_rows"])
    write_csv(output / "event_level_comparison.csv", event_comparison)
    write_json(output / "broad_random_summary.json", summary)
    write_json(output / "broad_market_universe_manifest.json", universe_manifest(summary, price_report))
    write_json(output / "broad_random_manifest.json", run_manifest(summary))
    write_json(
        output / "broad_market_universe_checksums.json",
        {
            "broad_market_universe.csv": sha256_file(output / "broad_market_universe.csv"),
            "broad_market_universe_manifest.json": sha256_file(output / "broad_market_universe_manifest.json"),
        },
    )
    return summary


def fetch_sp500_constituents() -> list[dict[str, str]]:
    """Fetch current S&P 500 constituents from a stable broad-index page."""

    request = urllib.request.Request(
        SP500_SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 GeoRisk validation research"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read()
    frame = pd.read_html(io.BytesIO(html))[0]
    rows = []
    for record in frame.to_dict(orient="records"):
        symbol = str(record["Symbol"]).strip().upper().replace(".", "-")
        rows.append(
            {
                "ticker": symbol,
                "company_name": str(record.get("Security", "")).strip(),
                "gics_sector": str(record.get("GICS Sector", "")).strip(),
                "gics_sub_industry": str(record.get("GICS Sub-Industry", "")).strip(),
                "universe_source": SP500_SOURCE_URL,
                "asset_class": "US equity",
            }
        )
    return rows


def ensure_broad_price_csvs(
    constituents: list[dict[str, str]],
    price_dir: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    """Download missing broad-universe prices into an isolated price directory."""

    import yfinance as yf

    report = {
        "price_dir": str(price_dir),
        "required_start": start.date().isoformat(),
        "required_end": end.date().isoformat(),
        "reused_symbols": [],
        "downloaded_symbols": [],
        "failed_symbols": [],
        "coverage_warnings": [],
    }
    missing: list[str] = []
    for row in constituents:
        ticker = row["ticker"]
        existing = load_existing_price_csv(price_dir / f"{ticker}.csv")
        if has_broad_required_coverage(existing, start, end):
            report["reused_symbols"].append(ticker)
        else:
            missing.append(ticker)

    for chunk in chunks(missing, 80):
        if not chunk:
            continue
        try:
            raw = yf.download(
                tickers=chunk,
                start=start.date().isoformat(),
                end=(end + pd.Timedelta(days=1)).date().isoformat(),
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        except Exception as exc:
            for ticker in chunk:
                report["failed_symbols"].append({"symbol": ticker, "reason": type(exc).__name__})
            continue
        for ticker in chunk:
            frame = extract_yfinance_symbol(raw, ticker, len(chunk))
            prepared = normalize_price_frame(frame)
            if prepared.empty:
                report["failed_symbols"].append({"symbol": ticker, "reason": "download_returned_no_valid_prices"})
                continue
            if not has_broad_required_coverage(prepared, start, end):
                report["coverage_warnings"].append({"symbol": ticker, "reason": "calendar_edge_coverage_warning"})
                write_price_csv(price_dir / f"{ticker}.csv", prepared)
                report["downloaded_symbols"].append(ticker)
                continue
            write_price_csv(price_dir / f"{ticker}.csv", prepared)
            report["downloaded_symbols"].append(ticker)
    return report


def has_broad_required_coverage(prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    """Return whether prices cover the broad baseline's required trading range."""

    if prices.empty or "Date" not in prices.columns:
        return False
    dates = pd.to_datetime(prices["Date"], errors="coerce").dropna()
    if dates.empty:
        return False
    start_slack = start + pd.Timedelta(days=3)
    return dates.min() <= start_slack and dates.max() >= end


def build_universe_rows(
    constituents: list[dict[str, str]],
    price_dir: Path,
    snapshots: list[dict[str, Any]],
    benchmark_prices: pd.DataFrame,
    config: MarketModelConfig,
    curated_symbols: set[str],
) -> list[dict[str, Any]]:
    """Build frozen broad universe rows with event-level price eligibility."""

    rows = []
    for item in constituents:
        ticker = item["ticker"]
        prices, error = load_price_series(ticker, price_dir=price_dir)
        if prices is None:
            rows.append(
                {
                    **item,
                    "price_start": None,
                    "price_end": None,
                    "eligible_event_count": 0,
                    "eligible_event_ids": "",
                    "in_asset_mapping": ticker in curated_symbols,
                    "price_status": "missing_or_invalid",
                    "price_error": error,
                }
            )
            continue
        eligible = []
        for snapshot in snapshots:
            result = calculate_market_model_car_from_prices(
                event_id=snapshot["event_id"],
                symbol=ticker,
                event_date=snapshot["event_date"],
                asset_prices=prices,
                benchmark_prices=benchmark_prices,
                config=config,
            )
            if not result.get("missing_data_reason"):
                eligible.append(snapshot["event_id"])
        rows.append(
            {
                **item,
                "price_start": prices["date"].min().date().isoformat(),
                "price_end": prices["date"].max().date().isoformat(),
                "eligible_event_count": len(eligible),
                "eligible_event_ids": ";".join(eligible),
                "in_asset_mapping": ticker in curated_symbols,
                "price_status": "valid" if eligible else "no_eligible_events",
                "price_error": "",
            }
        )
    return rows


def run_broad_mc(
    baseline_name: str,
    snapshots: list[dict[str, Any]],
    eligible_by_event: dict[str, list[str]],
    georisk_symbols_by_event: dict[str, set[str]],
    event_counts: Counter,
    car_lookup: dict[tuple[str, str], dict[str, Any]],
    random_seed: int,
    draws: int,
    exclude_curated: bool,
    curated_symbols: set[str],
) -> dict[str, Any]:
    """Run event-count matched broad-random Monte Carlo draws."""

    rng = random.Random(random_seed)
    run_rows = []
    event_rows = []
    for run_id in range(draws):
        pooled_rows: list[dict[str, Any]] = []
        event_medians: list[float] = []
        for snapshot in snapshots:
            event_id = snapshot["event_id"]
            required_n = event_counts[event_id]
            candidates = [
                symbol
                for symbol in eligible_by_event[event_id]
                if symbol not in georisk_symbols_by_event[event_id]
                and (not exclude_curated or symbol not in curated_symbols)
            ]
            if len(candidates) < required_n:
                raise RuntimeError(
                    f"{baseline_name} has insufficient candidates for {event_id}: "
                    f"{len(candidates)} < {required_n}"
                )
            sampled = rng.sample(sorted(candidates), required_n)
            car_rows = [dict(car_lookup[(event_id, symbol)]) for symbol in sampled]
            evaluated = [row for row in car_rows if not row.get("missing_data_reason")]
            values = abs_scar_values(evaluated)
            if len(evaluated) != required_n:
                raise RuntimeError(f"{baseline_name} produced unevaluable rows for {event_id}")
            pooled_rows.extend(evaluated)
            event_median = median(values)
            event_medians.append(event_median)
            event_rows.append(
                {
                    "baseline_name": baseline_name,
                    "run_id": run_id,
                    "event_id": event_id,
                    "sample_size": required_n,
                    "hit_rate": metric_row(evaluated)["hit_rate"],
                    "median_abs_scar": event_median,
                    "mean_abs_scar": mean(values),
                }
            )
        metric = metric_row(pooled_rows)
        run_rows.append(
            {
                "baseline_name": baseline_name,
                "run_id": run_id,
                "evaluated": metric["evaluated"],
                "hits": metric["hits"],
                "hit_rate": metric["hit_rate"],
                "pooled_median_abs_scar": metric["median_abs_SCAR"],
                "pooled_mean_abs_scar": metric["mean_abs_SCAR"],
                "aggregate_event_median_abs_scar": median(event_medians),
            }
        )
    return {"run_rows": run_rows, "event_rows": event_rows, "summary": summarize_mc(run_rows)}


def precompute_broad_car_lookup(
    snapshots: list[dict[str, Any]],
    symbols: list[str],
    price_dir: Path,
    benchmark_prices: pd.DataFrame,
    config: MarketModelConfig,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Precompute CAR/SCAR once per event-symbol for broad MC sampling."""

    price_cache: dict[str, pd.DataFrame] = {}
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for symbol in symbols:
        prices, error = load_price_series(symbol, price_dir=price_dir)
        if prices is None:
            for snapshot in snapshots:
                lookup[(snapshot["event_id"], symbol)] = {
                    "event_id": snapshot["event_id"],
                    "symbol": symbol,
                    "missing_data_reason": error or "missing_asset_prices",
                }
            continue
        price_cache[symbol] = prices
        for snapshot in snapshots:
            result = calculate_market_model_car_from_prices(
                event_id=snapshot["event_id"],
                symbol=symbol,
                event_date=snapshot["event_date"],
                asset_prices=prices,
                benchmark_prices=benchmark_prices,
                config=config,
            )
            result["event_date"] = snapshot["event_date"]
            result["source"] = "broad_random"
            lookup[(snapshot["event_id"], symbol)] = result
    return lookup


def calculate_symbol_car(
    snapshot: dict[str, Any],
    symbol: str,
    price_dir: Path,
    benchmark_prices: pd.DataFrame,
    config: MarketModelConfig,
    price_cache: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Calculate CAR for one broad-random sampled symbol using cached prices."""

    if symbol not in price_cache:
        prices, error = load_price_series(symbol, price_dir=price_dir)
        if prices is None:
            return {
                "event_id": snapshot["event_id"],
                "symbol": symbol,
                "missing_data_reason": error or "missing_asset_prices",
            }
        price_cache[symbol] = prices
    result = calculate_market_model_car_from_prices(
        event_id=snapshot["event_id"],
        symbol=symbol,
        event_date=snapshot["event_date"],
        asset_prices=price_cache[symbol],
        benchmark_prices=benchmark_prices,
        config=config,
    )
    result["event_date"] = snapshot["event_date"]
    result["source"] = "broad_random"
    return result


def build_summary(
    universe_rows: list[dict[str, Any]],
    curated_symbols: set[str],
    georisk_rows: list[dict[str, Any]],
    full: dict[str, Any],
    ex_curated: dict[str, Any],
    curated_summary: dict[str, Any],
    event_comparison: list[dict[str, Any]],
    random_seed: int,
    draws: int,
    price_report: dict[str, Any],
) -> dict[str, Any]:
    """Build three-way result summary."""

    georisk_metric = metric_row(georisk_rows)
    georisk_event_aggregate = median(row["georisk_median_abs_scar"] for row in georisk_event_rows(georisk_rows))
    curated_cont = curated_summary["event_level_primary"]
    curated_bin = curated_summary["binary_reference"]
    full_stats = full["summary"]
    ex_stats = ex_curated["summary"]
    return {
        "experiment_name": "Broad Market Random Baseline",
        "universe": {
            "source": SP500_SOURCE_URL,
            "fixed_universe_approximation": True,
            "survivorship_bias_limitation": True,
            "raw_tickers": len(universe_rows),
            "eligible_tickers": sum(1 for row in universe_rows if int(row["eligible_event_count"]) > 0),
            "eligible_all_12_events": sum(1 for row in universe_rows if int(row["eligible_event_count"]) == 12),
            "overlap_with_asset_mapping": sum(1 for row in universe_rows if bool(row["in_asset_mapping"])),
            "non_curated_tickers": sum(1 for row in universe_rows if not bool(row["in_asset_mapping"])),
        },
        "georisk": {
            "hit_rate": georisk_metric["hit_rate"],
            "hits": georisk_metric["hits"],
            "evaluated": georisk_metric["evaluated"],
            "aggregate_event_median_abs_scar": georisk_event_aggregate,
        },
        "curated_random": {
            "binary_mean_hit_rate": curated_bin["curated_random_mean_hit_rate"],
            "continuous_aggregate_median": curated_cont["curated_random_aggregate"]["median"],
            "continuous_aggregate_mean": curated_cont["curated_random_aggregate"]["mean"],
        },
        "broad_random_full": full_stats,
        "broad_random_ex_curated": ex_stats,
        "domain_prior_decomposition": {
            "binary_broad_full_to_curated_uplift": curated_bin["curated_random_mean_hit_rate"]
            - full_stats["hit_rate"]["mean"],
            "binary_broad_ex_curated_to_curated_uplift": curated_bin["curated_random_mean_hit_rate"]
            - ex_stats["hit_rate"]["mean"],
            "binary_curated_to_georisk_uplift": georisk_metric["hit_rate"]
            - curated_bin["curated_random_mean_hit_rate"],
            "continuous_broad_full_to_curated_uplift": curated_cont["curated_random_aggregate"]["median"]
            - full_stats["aggregate_event_median_abs_scar"]["median"],
            "continuous_broad_ex_curated_to_curated_uplift": curated_cont["curated_random_aggregate"]["median"]
            - ex_stats["aggregate_event_median_abs_scar"]["median"],
            "continuous_curated_to_georisk_uplift": georisk_event_aggregate
            - curated_cont["curated_random_aggregate"]["median"],
        },
        "event_level_counts": {
            "georisk_gt_curated": sum(1 for row in event_comparison if row["georisk_minus_curated_mean"] > 0),
            "georisk_gt_broad_full": sum(1 for row in event_comparison if row["georisk_minus_broad_full_mean"] > 0),
            "georisk_gt_broad_ex_curated": sum(
                1 for row in event_comparison if row["georisk_minus_broad_ex_curated_mean"] > 0
            ),
        },
        "random_seed": random_seed,
        "monte_carlo_draws": draws,
        "price_report": price_report,
        "integrity": {
            "georisk_unchanged": True,
            "events_unchanged": True,
            "SCAR_unchanged": True,
            "threshold_unchanged": True,
            "no_V5": True,
            "no_power_analysis": True,
            "no_sector_matching": True,
        },
        "conclusion": classify_conclusion(georisk_event_aggregate, curated_cont, full_stats, ex_stats),
    }


def summarize_mc(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize broad-random MC distributions."""

    aggregate_values = [row["aggregate_event_median_abs_scar"] for row in rows]
    hit_rates = [row["hit_rate"] for row in rows]
    georisk = json.loads(CURATED_CONTINUOUS_SUMMARY_PATH.read_text())["event_level_primary"][
        "georisk_observed_aggregate_median_abs_scar"
    ]
    georisk_hit = json.loads(CURATED_CONTINUOUS_SUMMARY_PATH.read_text())["binary_reference"]["georisk_hit_rate"]
    return {
        "aggregate_event_median_abs_scar": {
            **distribution_summary(aggregate_values),
            "georisk_percentile": percentile_rank(aggregate_values, georisk),
            "empirical_one_sided_p_value": empirical_one_sided_p_value(aggregate_values, georisk),
        },
        "hit_rate": {
            **distribution_summary(hit_rates),
            "georisk_percentile": percentile_rank(hit_rates, georisk_hit),
        },
    }


def universe_manifest(summary: dict[str, Any], price_report: dict[str, Any]) -> dict[str, Any]:
    """Return broad universe manifest."""

    return {
        "universe_name": "Broad Market Random Baseline Universe",
        "universe_source": SP500_SOURCE_URL,
        "constituent_date_version": "current_page_fetch_at_runtime",
        "selection_rule": "Current S&P 500 constituents; U.S. equity asset class; filtered only for price coverage.",
        "fixed_universe_approximation": True,
        "survivorship_bias_limitation": True,
        "raw_universe_size": summary["universe"]["raw_tickers"],
        "final_eligible_universe_size": summary["universe"]["eligible_tickers"],
        "overlap_with_asset_mapping": summary["universe"]["overlap_with_asset_mapping"],
        "non_curated_ticker_count": summary["universe"]["non_curated_tickers"],
        "price_report": price_report,
    }


def run_manifest(summary: dict[str, Any]) -> dict[str, Any]:
    """Return run manifest."""

    return {
        "experiment_name": summary["experiment_name"],
        "same_12_CAR_events": True,
        "same_frozen_GeoRisk_asset_predictions": True,
        "same_event_windows": True,
        "same_CAR_SCAR_implementation": True,
        "same_hit_threshold": True,
        "random_seed": summary["random_seed"],
        "monte_carlo_draws": summary["monte_carlo_draws"],
        "broad_full": "entire broad universe",
        "broad_ex_curated": "broad universe excluding asset_mapping.csv tickers",
    }


def event_comparison_rows(
    georisk_event: list[dict[str, Any]],
    curated_event: dict[str, dict[str, float]],
    full: dict[str, Any],
    ex_curated: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build event-level comparison rows."""

    full_event_summary = summarize_event_mc(full["event_rows"])
    ex_event_summary = summarize_event_mc(ex_curated["event_rows"])
    rows = []
    for row in georisk_event:
        event_id = row["event_id"]
        curated = curated_event[event_id]
        broad = full_event_summary[event_id]
        broad_ex = ex_event_summary[event_id]
        rows.append(
            {
                "event_id": event_id,
                "georisk_median_abs_scar": row["georisk_median_abs_scar"],
                "curated_random_mean_median_abs_scar": curated["curated_random_mean_event_median_abs_scar"],
                "curated_random_median_abs_scar": curated["curated_random_median_event_median_abs_scar"],
                "broad_full_mean_median_abs_scar": broad["mean_event_median_abs_scar"],
                "broad_full_median_abs_scar": broad["median_event_median_abs_scar"],
                "broad_ex_curated_mean_median_abs_scar": broad_ex["mean_event_median_abs_scar"],
                "broad_ex_curated_median_abs_scar": broad_ex["median_event_median_abs_scar"],
                "georisk_minus_curated_mean": row["georisk_median_abs_scar"]
                - curated["curated_random_mean_event_median_abs_scar"],
                "georisk_minus_broad_full_mean": row["georisk_median_abs_scar"]
                - broad["mean_event_median_abs_scar"],
                "georisk_minus_broad_ex_curated_mean": row["georisk_median_abs_scar"]
                - broad_ex["mean_event_median_abs_scar"],
            }
        )
    return rows


def summarize_event_mc(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Summarize event-level MC medians by event."""

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row["median_abs_scar"])
    return {
        event_id: {
            "mean_event_median_abs_scar": mean(values),
            "median_event_median_abs_scar": median(values),
        }
        for event_id, values in grouped.items()
    }


def georisk_event_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return GeoRisk median |SCAR| by event."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row)
    output = []
    for event_id, event_rows in sorted(grouped.items()):
        values = abs_scar_values(event_rows)
        output.append(
            {
                "event_id": event_id,
                "georisk_median_abs_scar": median(values),
                "georisk_mean_abs_scar": mean(values),
                "georisk_hit_rate": metric_row(event_rows)["hit_rate"],
            }
        )
    return output


def load_curated_event_continuous() -> dict[str, dict[str, float]]:
    """Load prior continuous event-level curated comparison."""

    path = Path("data/market_validation/scar_continuous_test/event_level_continuous_comparison.csv")
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {
        row["event_id"]: {
            "curated_random_mean_event_median_abs_scar": float(
                row["curated_random_mean_event_median_abs_scar"]
            ),
            "curated_random_median_event_median_abs_scar": float(
                row["curated_random_median_event_median_abs_scar"]
            ),
        }
        for row in rows
    }


def validate_event_eligibility(
    eligible_by_event: dict[str, list[str]],
    event_counts: Counter,
    max_required_n: int,
) -> None:
    """Fail if any event cannot draw its required sample size."""

    for event_id, required_n in event_counts.items():
        eligible = len(eligible_by_event[event_id])
        if eligible < required_n or eligible < max_required_n:
            raise RuntimeError(f"Insufficient broad universe for {event_id}: {eligible} < {required_n}")


def eligible_symbols_by_event(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map event_id to eligible broad symbols."""

    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for event_id in str(row.get("eligible_event_ids", "")).split(";"):
            if event_id:
                result[event_id].append(row["ticker"])
    return {event_id: sorted(symbols) for event_id, symbols in result.items()}


def load_georisk_rows(car_result_dir: str | Path) -> list[dict[str, Any]]:
    """Load evaluated GeoRisk CAR rows."""

    with (Path(car_result_dir) / "car_pair_results.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    output = []
    for row in rows:
        if row.get("source") == "georisk" and not row.get("missing_data_reason"):
            row["hit"] = row.get("hit", "").lower() == "true"
            row["standardized_car"] = float(row["standardized_car"])
            output.append(row)
    return output


def load_asset_mapping_symbols(path: str | Path) -> set[str]:
    """Load curated asset_mapping tickers."""

    with Path(path).open(encoding="utf-8") as handle:
        return {row["ticker"].upper() for row in csv.DictReader(handle) if row.get("ticker")}


def symbols_by_event(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Return GeoRisk sampled symbols by event."""

    grouped: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        grouped[row["event_id"]].add(row["symbol"].upper())
    return grouped


def classify_conclusion(
    georisk_aggregate: float,
    curated_cont: dict[str, Any],
    full_stats: dict[str, Any],
    ex_stats: dict[str, Any],
) -> dict[str, str]:
    """Classify curated-universe contamination result."""

    curated = curated_cont["curated_random_aggregate"]["median"]
    broad = full_stats["aggregate_event_median_abs_scar"]["median"]
    ex_broad = ex_stats["aggregate_event_median_abs_scar"]["median"]
    if georisk_aggregate > curated and curated > broad and curated > ex_broad:
        answer = "PARTIALLY"
        rationale = "Broad Random < Curated Random < GeoRisk on continuous aggregate |SCAR|."
    elif georisk_aggregate > broad and abs(georisk_aggregate - curated) <= abs(curated - broad):
        answer = "YES"
        rationale = "GeoRisk clearly exceeds Broad Random while Curated Random absorbs much of the gap."
    elif abs(curated - broad) < 0.02:
        answer = "NO"
        rationale = "Broad Random and Curated Random are close on continuous aggregate |SCAR|."
    else:
        answer = "PARTIALLY"
        rationale = "Curated universe changes baseline level, but separation is mixed."
    return {"answer": answer, "rationale": rationale}


def load_existing_price_csv(path: Path) -> pd.DataFrame:
    """Load isolated broad price CSV if present."""

    if not path.exists():
        return pd.DataFrame(columns=["Date", "Adj Close"])
    try:
        return normalize_price_frame(pd.read_csv(path))
    except Exception:
        return pd.DataFrame(columns=["Date", "Adj Close"])


def extract_yfinance_symbol(raw: pd.DataFrame, ticker: str, chunk_size: int) -> pd.DataFrame:
    """Extract one ticker from yfinance output."""

    if raw.empty:
        return pd.DataFrame(columns=["Date", "Adj Close"])
    if chunk_size == 1:
        return raw
    if isinstance(raw.columns, pd.MultiIndex) and ticker in raw.columns.get_level_values(0):
        return raw[ticker]
    return pd.DataFrame(columns=["Date", "Adj Close"])


def write_price_csv(path: Path, frame: pd.DataFrame) -> None:
    """Write normalized price CSV."""

    frame.to_csv(path, index=False)


def abs_scar_values(rows: list[dict[str, Any]]) -> list[float]:
    """Return absolute SCAR values."""

    return [abs(float(row["standardized_car"])) for row in rows if row.get("standardized_car") not in {None, ""}]


def distribution_summary(values: list[float]) -> dict[str, float]:
    """Summarize numeric distribution."""

    return {
        "mean": mean(values),
        "median": median(values),
        "p05": percentile(values, 0.05),
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
        "p95": percentile(values, 0.95),
    }


def percentile(values: list[float], q: float) -> float:
    """Return interpolated percentile."""

    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def percentile_rank(values: list[float], observed: float) -> float:
    """Return empirical percentile rank."""

    return sum(1 for value in values if value <= observed) / len(values)


def empirical_one_sided_p_value(values: list[float], observed: float) -> float:
    """Return (random >= observed + 1) / (draws + 1)."""

    return (sum(1 for value in values if value >= observed) + 1) / (len(values) + 1)


def chunks(values: list[Any], size: int) -> list[list[Any]]:
    """Split a list into chunks."""

    return [values[index : index + size] for index in range(0, len(values), size)]


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 checksum."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Write deterministic JSON."""

    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write CSV rows."""

    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
