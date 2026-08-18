"""Optional yfinance adapter for CAR validation price CSVs.

This module is intentionally separate from the CAR calculator. The core CAR
workflow remains CSV-first and works with manually supplied price files. This
adapter only helps create those CSVs when yfinance and internet access are
available.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

from src.eval.car.price_loader import load_csv
from src.eval.car.schemas import (
    BASELINE_ASSET_COLUMNS,
    HELDOUT_EVENT_COLUMNS,
    PREDICTED_ASSET_COLUMNS,
)


def collect_tickers(
    predicted_assets: pd.DataFrame,
    baseline_assets: pd.DataFrame | None,
    benchmark_symbol: str,
) -> list[str]:
    """Collect unique symbols needed for the CAR pilot."""

    symbols: list[str] = []
    symbols.extend(_clean_symbols(predicted_assets.get("symbol", [])))
    if baseline_assets is not None:
        symbols.extend(_clean_symbols(baseline_assets.get("symbol", [])))
    symbols.append(str(benchmark_symbol).strip().upper())
    return _dedupe(symbols)


def calculate_download_range(
    events: pd.DataFrame,
    lookback_calendar_days: int,
    lookforward_calendar_days: int,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return inclusive calendar range needed around all event dates."""

    event_dates = pd.to_datetime(events["event_date"])
    start = event_dates.min() - pd.Timedelta(days=lookback_calendar_days)
    end = event_dates.max() + pd.Timedelta(days=lookforward_calendar_days)
    return pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()


def transform_yfinance_prices(raw_prices: pd.DataFrame) -> pd.DataFrame:
    """Transform yfinance output into date,symbol,adj_close long format.

    The fetcher uses ``auto_adjust=True``, so yfinance's ``Close`` column is an
    adjusted close series. Tests can pass a yfinance-like dataframe with either
    multi-index columns or a single-symbol dataframe.
    """

    if raw_prices.empty:
        return pd.DataFrame(columns=["date", "symbol", "adj_close"])

    frame = raw_prices.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        close = _extract_close_from_multiindex(frame)
        long = close.stack().reset_index()
        long.columns = ["date", "symbol", "adj_close"]
    else:
        close_column = "Close" if "Close" in frame.columns else "Adj Close"
        if close_column not in frame.columns:
            return pd.DataFrame(columns=["date", "symbol", "adj_close"])
        symbol = frame.attrs.get("symbol", "")
        long = frame[[close_column]].reset_index()
        long.columns = ["date", "adj_close"]
        long["symbol"] = symbol
        long = long[["date", "symbol", "adj_close"]]

    long["date"] = pd.to_datetime(long["date"]).dt.strftime("%Y-%m-%d")
    long["symbol"] = long["symbol"].astype(str)
    long["adj_close"] = pd.to_numeric(long["adj_close"], errors="coerce")
    return long.dropna(subset=["date", "symbol", "adj_close"]).reset_index(drop=True)


def split_benchmark_rows(
    long_prices: pd.DataFrame,
    benchmark_symbol: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split long prices into non-benchmark assets and benchmark rows."""

    benchmark = str(benchmark_symbol).strip().upper()
    prices = long_prices.copy()
    symbols = prices["symbol"].astype(str).str.upper()
    benchmark_rows = prices[symbols == benchmark].reset_index(drop=True)
    asset_rows = prices[symbols != benchmark].reset_index(drop=True)
    return asset_rows, benchmark_rows


def fetch_prices_with_yfinance(
    tickers: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Fetch adjusted close prices via yfinance and return long-format rows."""

    try:
        import yfinance as yf
    except ImportError:
        print("yfinance is not installed. Install it with: pip install yfinance")
        return pd.DataFrame(columns=["date", "symbol", "adj_close"])

    try:
        # yfinance end date is exclusive, so add one day to include requested end.
        raw = yf.download(
            tickers=tickers,
            start=start.date().isoformat(),
            end=(end + pd.Timedelta(days=1)).date().isoformat(),
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception as exc:
        print(f"Failed to download price data with yfinance: {type(exc).__name__}: {exc}")
        return pd.DataFrame(columns=["date", "symbol", "adj_close"])

    if raw.empty:
        print("yfinance returned no price data for the requested tickers/date range.")
        return pd.DataFrame(columns=["date", "symbol", "adj_close"])

    if len(tickers) == 1:
        raw.attrs["symbol"] = tickers[0]
    return transform_yfinance_prices(raw)


def run_fetcher(
    events_path: str | Path,
    predicted_assets_path: str | Path,
    baseline_assets_path: str | Path | None,
    benchmark_symbol: str,
    prices_output: str | Path,
    benchmark_output: str | Path,
    lookback_calendar_days: int,
    lookforward_calendar_days: int,
) -> int:
    """Create real-data price CSVs for the CAR evaluator."""

    events = load_csv(events_path, HELDOUT_EVENT_COLUMNS)
    predicted_assets = load_csv(predicted_assets_path, PREDICTED_ASSET_COLUMNS)
    baseline_assets = (
        load_csv(baseline_assets_path, BASELINE_ASSET_COLUMNS)
        if baseline_assets_path
        else None
    )

    tickers = collect_tickers(predicted_assets, baseline_assets, benchmark_symbol)
    start, end = calculate_download_range(
        events,
        lookback_calendar_days,
        lookforward_calendar_days,
    )
    long_prices = fetch_prices_with_yfinance(tickers, start, end)
    if long_prices.empty:
        return 1

    asset_rows, benchmark_rows = split_benchmark_rows(long_prices, benchmark_symbol)
    fetched_symbols = set(long_prices["symbol"].astype(str).str.upper())
    requested_symbols = {ticker.upper() for ticker in tickers}
    missing_symbols = sorted(requested_symbols - fetched_symbols)

    prices_output = Path(prices_output)
    benchmark_output = Path(benchmark_output)
    prices_output.parent.mkdir(parents=True, exist_ok=True)
    benchmark_output.parent.mkdir(parents=True, exist_ok=True)
    asset_rows.to_csv(prices_output, index=False)
    benchmark_rows.to_csv(benchmark_output, index=False)

    print("GeoRisk CAR yfinance Fetch Summary")
    print(f"tickers_requested: {len(tickers)} ({', '.join(tickers)})")
    print(f"tickers_successfully_fetched: {len(fetched_symbols)} ({', '.join(sorted(fetched_symbols))})")
    print(f"tickers_missing_or_empty: {len(missing_symbols)} ({', '.join(missing_symbols)})")
    print(f"date_range: {start.date().isoformat()} to {end.date().isoformat()}")
    print(f"prices_output: {prices_output}")
    print(f"benchmark_output: {benchmark_output}")
    return 0


def main() -> None:
    """CLI entry point for optional yfinance price fetching."""

    parser = argparse.ArgumentParser(
        description="Fetch optional yfinance price CSVs for CAR validation."
    )
    parser.add_argument("--events", default="data/eval/heldout_events_real.csv")
    parser.add_argument("--predicted-assets", default="data/eval/predicted_assets_real.csv")
    parser.add_argument("--baseline-assets", default=None)
    parser.add_argument("--benchmark-symbol", default="SPY")
    parser.add_argument("--prices-output", default="data/eval/prices_real.csv")
    parser.add_argument("--benchmark-output", default="data/eval/benchmark_prices_real.csv")
    parser.add_argument("--lookback-calendar-days", type=int, default=260)
    parser.add_argument("--lookforward-calendar-days", type=int, default=10)
    args = parser.parse_args()

    raise SystemExit(
        run_fetcher(
            args.events,
            args.predicted_assets,
            args.baseline_assets,
            args.benchmark_symbol,
            args.prices_output,
            args.benchmark_output,
            args.lookback_calendar_days,
            args.lookforward_calendar_days,
        )
    )


def _extract_close_from_multiindex(frame: pd.DataFrame) -> pd.DataFrame:
    """Extract adjusted close columns from common yfinance multi-index shapes."""

    level_0 = set(map(str, frame.columns.get_level_values(0)))
    level_1 = set(map(str, frame.columns.get_level_values(1)))
    if "Close" in level_1:
        return frame.xs("Close", axis=1, level=1)
    if "Adj Close" in level_1:
        return frame.xs("Adj Close", axis=1, level=1)
    if "Close" in level_0:
        return frame.xs("Close", axis=1, level=0)
    if "Adj Close" in level_0:
        return frame.xs("Adj Close", axis=1, level=0)
    return pd.DataFrame(index=frame.index)


def _clean_symbols(values: Iterable[object]) -> list[str]:
    """Normalize ticker-like values from CSV columns."""

    return [
        str(value).strip().upper()
        for value in values
        if value is not None and str(value).strip()
    ]


def _dedupe(values: list[str]) -> list[str]:
    """Preserve order while removing duplicates."""

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


if __name__ == "__main__":
    main()
