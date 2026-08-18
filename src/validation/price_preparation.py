"""Prepare local price CSVs for snapshot-based CAR validation.

This module may use yfinance to create reproducible local CSV inputs, but the
formal CAR calculator remains CSV-first and never depends on live downloads.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.validation.car_calculator import MarketModelConfig
from src.validation.prediction_snapshot import load_accepted_validation_events


DEFAULT_PRICE_DIR = Path("data/prices")
DownloadFn = Callable[[str, pd.Timestamp, pd.Timestamp], pd.DataFrame]


def collect_required_symbols_from_snapshots(
    snapshots: list[dict[str, Any]],
    baseline_exposures_by_event_id: dict[str, list[dict[str, Any]]] | None = None,
    benchmark_symbol: str = "SPY",
) -> list[str]:
    """Collect deduplicated symbols from frozen snapshots, baselines, and benchmark."""

    baseline_exposures_by_event_id = baseline_exposures_by_event_id or {}
    symbols: list[str] = []
    for snapshot in snapshots:
        for exposure in snapshot.get("predicted_exposures", []):
            _append_symbol(symbols, exposure.get("symbol"))

        baselines = snapshot.get("baseline_exposures")
        if baselines is None:
            baselines = baseline_exposures_by_event_id.get(snapshot.get("event_id"), [])
        for baseline in baselines:
            _append_symbol(symbols, baseline.get("symbol"))

    _append_symbol(symbols, benchmark_symbol)
    return symbols


def baseline_exposures_by_event_id(
    manifest_path: str | Path,
) -> dict[str, list[dict[str, Any]]]:
    """Load accepted-event baseline exposures from the validation manifest."""

    return {
        event.event_id: [
            baseline.model_dump(mode="json")
            for baseline in event.baseline_assets
        ]
        for event in load_accepted_validation_events(manifest_path)
    }


def calculate_required_price_range(
    event_dates: list[str],
    config: MarketModelConfig,
    calendar_buffer_days: int = 10,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, list[str]]:
    """Return a buffered calendar range covering all CAR windows.

    Invalid event dates are returned for reporting instead of raising. The
    buffer converts trading-day windows into a conservative calendar-day range.
    """

    parsed_dates: list[pd.Timestamp] = []
    invalid_dates: list[str] = []
    for value in event_dates:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            invalid_dates.append(str(value))
        else:
            parsed_dates.append(pd.Timestamp(parsed).normalize())

    if not parsed_dates:
        return None, None, invalid_dates

    earliest_offset = min(config.estimation_window_start, config.event_window_start, 0)
    latest_offset = max(config.estimation_window_end, config.event_window_end, 0)
    lookback_trading_days = abs(earliest_offset) + 2
    lookforward_trading_days = max(latest_offset, 0) + 2
    lookback_calendar_days = _trading_days_to_calendar_days(
        lookback_trading_days,
        calendar_buffer_days,
    )
    lookforward_calendar_days = _trading_days_to_calendar_days(
        lookforward_trading_days,
        calendar_buffer_days,
    )

    start = min(parsed_dates) - pd.Timedelta(days=lookback_calendar_days)
    end = max(parsed_dates) + pd.Timedelta(days=lookforward_calendar_days)
    return start.normalize(), end.normalize(), invalid_dates


def prepare_price_csvs(
    symbols: list[str],
    event_dates: list[str],
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    config: MarketModelConfig | None = None,
    download_fn: DownloadFn | None = None,
) -> dict[str, Any]:
    """Ensure local price CSVs exist with sufficient buffered date coverage."""

    config = config or MarketModelConfig()
    price_path = Path(price_dir)
    price_path.mkdir(parents=True, exist_ok=True)
    start, end, invalid_event_dates = calculate_required_price_range(event_dates, config)
    unique_symbols = _dedupe_symbols(symbols)

    report: dict[str, Any] = {
        "price_dir": str(price_path),
        "symbols": unique_symbols,
        "required_start": start.date().isoformat() if start is not None else None,
        "required_end": end.date().isoformat() if end is not None else None,
        "reused_symbols": [],
        "downloaded_symbols": [],
        "failed_symbols": [],
        "invalid_event_dates": invalid_event_dates,
    }
    if start is None or end is None:
        return report

    download = download_fn or download_price_series_with_yfinance
    for symbol in unique_symbols:
        csv_path = price_path / f"{symbol}.csv"
        existing = load_existing_price_csv(csv_path)
        if has_sufficient_coverage(existing, start, end):
            report["reused_symbols"].append(symbol)
            continue

        downloaded = download(symbol, start, end)
        prepared = normalize_price_frame(downloaded)
        if prepared.empty:
            report["failed_symbols"].append(
                {
                    "symbol": symbol,
                    "reason": "download_returned_no_valid_prices",
                    "path": str(csv_path),
                }
            )
            continue

        merged = merge_price_frames(existing, prepared)
        if not has_sufficient_coverage(merged, start, end):
            report["failed_symbols"].append(
                {
                    "symbol": symbol,
                    "reason": "insufficient_downloaded_coverage",
                    "path": str(csv_path),
                }
            )
            write_price_csv(csv_path, merged)
            continue

        write_price_csv(csv_path, merged)
        report["downloaded_symbols"].append(symbol)

    return report


def load_existing_price_csv(path: str | Path) -> pd.DataFrame:
    """Load an existing per-symbol price CSV, returning an empty frame on failure."""

    csv_path = Path(path)
    if not csv_path.exists():
        return pd.DataFrame(columns=["Date", "Adj Close"])
    try:
        return normalize_price_frame(pd.read_csv(csv_path))
    except (OSError, ValueError):
        return pd.DataFrame(columns=["Date", "Adj Close"])


def has_sufficient_coverage(
    prices: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> bool:
    """Return whether a price frame covers the required inclusive date range."""

    if prices.empty or "Date" not in prices.columns:
        return False
    dates = pd.to_datetime(prices["Date"], errors="coerce").dropna()
    if dates.empty:
        return False
    return dates.min() <= start and dates.max() >= end


def download_price_series_with_yfinance(
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Download one symbol from yfinance as a Date/Adj Close dataframe."""

    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame(columns=["Date", "Adj Close"])

    try:
        raw = yf.download(
            symbol,
            start=start.date().isoformat(),
            end=(end + pd.Timedelta(days=1)).date().isoformat(),
            auto_adjust=True,
            progress=False,
        )
    except Exception:
        return pd.DataFrame(columns=["Date", "Adj Close"])

    return normalize_price_frame(raw)


def normalize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance or CSV-like prices to Date/Adj Close columns."""

    if frame.empty:
        return pd.DataFrame(columns=["Date", "Adj Close"])

    prices = frame.copy()
    if isinstance(prices.columns, pd.MultiIndex):
        if "Close" in prices.columns.get_level_values(-1):
            prices = prices.xs("Close", axis=1, level=-1)
        elif "Adj Close" in prices.columns.get_level_values(-1):
            prices = prices.xs("Adj Close", axis=1, level=-1)
        prices = prices.iloc[:, [0]]

    if "Date" not in prices.columns:
        prices = prices.reset_index()
    close_column = _close_column(prices)
    if close_column is None or "Date" not in prices.columns:
        return pd.DataFrame(columns=["Date", "Adj Close"])

    result = prices[["Date", close_column]].copy()
    result.columns = ["Date", "Adj Close"]
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["Adj Close"] = pd.to_numeric(result["Adj Close"], errors="coerce")
    result = result.dropna(subset=["Date", "Adj Close"])
    result["Date"] = result["Date"].dt.strftime("%Y-%m-%d")
    return result.sort_values("Date").reset_index(drop=True)


def merge_price_frames(existing: pd.DataFrame, downloaded: pd.DataFrame) -> pd.DataFrame:
    """Merge existing and downloaded price rows, preferring downloaded duplicates."""

    frames = [frame for frame in [existing, downloaded] if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["Date", "Adj Close"])
    merged = pd.concat(frames, ignore_index=True)
    merged["Date"] = pd.to_datetime(merged["Date"], errors="coerce")
    merged["Adj Close"] = pd.to_numeric(merged["Adj Close"], errors="coerce")
    merged = merged.dropna(subset=["Date", "Adj Close"])
    merged = merged.drop_duplicates(subset=["Date"], keep="last")
    merged["Date"] = merged["Date"].dt.strftime("%Y-%m-%d")
    return merged.sort_values("Date").reset_index(drop=True)


def write_price_csv(path: str | Path, prices: pd.DataFrame) -> Path:
    """Write a per-symbol price CSV compatible with the CAR loader."""

    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    normalize_price_frame(prices).to_csv(csv_path, index=False)
    return csv_path


def _close_column(frame: pd.DataFrame) -> str | None:
    if "Adj Close" in frame.columns:
        return "Adj Close"
    if "Close" in frame.columns:
        return "Close"
    if len(frame.columns) >= 2:
        candidates = [column for column in frame.columns if column != "Date"]
        if candidates:
            return str(candidates[0])
    return None


def _append_symbol(symbols: list[str], symbol: Any) -> None:
    if symbol is None:
        return
    normalized = str(symbol).strip().upper()
    if normalized and normalized not in symbols:
        symbols.append(normalized)


def _dedupe_symbols(symbols: list[str]) -> list[str]:
    deduped: list[str] = []
    for symbol in symbols:
        _append_symbol(deduped, symbol)
    return deduped


def _trading_days_to_calendar_days(trading_days: int, buffer_days: int) -> int:
    return int(math.ceil(trading_days * 7 / 5)) + buffer_days
