"""Market-model CAR calculation for validation snapshots.

This module computes ex-post CAR for validation only. It does not predict
prices, does not provide investment advice, and does not run final evaluation.

Hits are magnitude-based, not directional: because GeoRisk predicts *exposure*
(that an asset is affected) rather than direction (up vs down), a hit means the
absolute standardized CAR crosses a significance threshold in either direction.
The signed ``car`` and ``direction`` fields are retained as diagnostics only and
do not participate in hit detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_PRICE_DIR = Path("data/prices")
DEFAULT_ESTIMATION_WINDOW = (-130, -10)
DEFAULT_EVENT_WINDOW = (-1, 1)
MIN_ABNORMAL_RETURN_STD = 1e-12


@dataclass(frozen=True)
class MarketModelConfig:
    """Trading-day windows for market-model CAR calculation."""

    estimation_window_start: int = DEFAULT_ESTIMATION_WINDOW[0]
    estimation_window_end: int = DEFAULT_ESTIMATION_WINDOW[1]
    event_window_start: int = DEFAULT_EVENT_WINDOW[0]
    event_window_end: int = DEFAULT_EVENT_WINDOW[1]
    significance_threshold: float = 1.96
    """|standardized CAR| at or above which an exposure counts as a hit.

    Magnitude-based and direction-agnostic. 1.96 is the two-sided ~5% normal
    default; it is exposed here so it can be recalibrated without changing the
    calculation logic.
    """


def load_price_series_from_csv(
    symbol: str,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
) -> pd.DataFrame:
    """Load Date and adjusted close prices from data/prices/{symbol}.csv."""

    path = Path(price_dir) / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing price CSV: {path}")

    frame = pd.read_csv(path)
    if "Date" not in frame.columns:
        raise ValueError(f"{path} must include a Date column.")

    price_column = _price_column(frame)
    result = frame[["Date", price_column]].copy()
    result.columns = ["date", "adj_close"]
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["adj_close"] = pd.to_numeric(result["adj_close"], errors="coerce")
    result = result.dropna(subset=["date", "adj_close"])
    result["symbol"] = symbol
    return result.sort_values("date").reset_index(drop=True)


def load_price_series(
    symbol: str,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    allow_yfinance: bool = False,
    start: str | None = None,
    end: str | None = None,
) -> tuple[pd.DataFrame | None, str | None]:
    """Load prices from CSV, optionally falling back to yfinance if installed."""

    try:
        return load_price_series_from_csv(symbol, price_dir), None
    except (FileNotFoundError, ValueError) as exc:
        if not allow_yfinance:
            return None, str(exc)

    return _load_price_series_from_yfinance(symbol, start=start, end=end)


def calculate_market_model_car(
    event_id: str,
    symbol: str,
    benchmark_symbol: str,
    event_date: str,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    config: MarketModelConfig | None = None,
    allow_yfinance: bool = False,
) -> dict[str, Any]:
    """Calculate market-model CAR for one event-symbol pair.

    Returns a dictionary compatible with ``CARResult`` fields plus supporting
    diagnostics such as t0, alpha, beta, and abnormal-return rows.
    """

    config = config or MarketModelConfig()
    if symbol.upper() == benchmark_symbol.upper():
        return _missing_result(
            event_id,
            symbol,
            "asset_equals_benchmark",
            benchmark=benchmark_symbol,
        )

    asset_prices, asset_error = load_price_series(
        symbol,
        price_dir=price_dir,
        allow_yfinance=allow_yfinance,
    )
    if asset_prices is None:
        return _missing_result(
            event_id,
            symbol,
            "missing_asset_prices",
            asset_error,
            expected_csv_path=str(Path(price_dir) / f"{symbol}.csv"),
        )

    benchmark_prices, benchmark_error = load_price_series(
        benchmark_symbol,
        price_dir=price_dir,
        allow_yfinance=allow_yfinance,
    )
    if benchmark_prices is None:
        return _missing_result(
            event_id,
            symbol,
            "missing_benchmark_prices",
            benchmark_error,
            benchmark=benchmark_symbol,
            expected_benchmark_csv_path=str(Path(price_dir) / f"{benchmark_symbol}.csv"),
        )

    return calculate_market_model_car_from_prices(
        event_id=event_id,
        symbol=symbol,
        event_date=event_date,
        asset_prices=asset_prices,
        benchmark_prices=benchmark_prices,
        config=config,
    )


def calculate_market_model_car_from_prices(
    event_id: str,
    symbol: str,
    event_date: str,
    asset_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    config: MarketModelConfig | None = None,
) -> dict[str, Any]:
    """Calculate market-model CAR from prepared asset and benchmark prices."""

    config = config or MarketModelConfig()
    returns = align_asset_and_benchmark_returns(asset_prices, benchmark_prices)
    if returns.empty:
        return _missing_result(event_id, symbol, "no_overlapping_return_dates")

    event_timestamp = pd.to_datetime(event_date, errors="coerce")
    if pd.isna(event_timestamp):
        return _missing_result(event_id, symbol, "invalid_event_date")

    t0_date = align_event_date_to_next_trading_day(
        returns["date"],
        pd.Timestamp(event_timestamp),
    )
    if t0_date is None:
        return _missing_result(event_id, symbol, "event_date_out_of_range")

    matches = returns.index[returns["date"] == t0_date].tolist()
    if not matches:
        return _missing_result(event_id, symbol, "event_date_out_of_range")
    t0_index = matches[0]

    estimation_start = t0_index + config.estimation_window_start
    estimation_end = t0_index + config.estimation_window_end
    event_start = t0_index + config.event_window_start
    event_end = t0_index + config.event_window_end

    if (
        estimation_start < 0
        or estimation_end >= len(returns)
        or estimation_start > estimation_end
    ):
        return _missing_result(
            event_id,
            symbol,
            "insufficient_estimation_data",
            t0_date=t0_date,
            estimation_window=_window_dict(config.estimation_window_start, config.estimation_window_end),
            available_rows=len(returns),
        )
    if event_start < 0 or event_end >= len(returns) or event_start > event_end:
        return _missing_result(
            event_id,
            symbol,
            "missing_event_window_data",
            t0_date=t0_date,
            event_window=_window_dict(config.event_window_start, config.event_window_end),
        )

    estimation = returns.iloc[estimation_start : estimation_end + 1]
    event_window = returns.iloc[event_start : event_end + 1].copy()
    if len(estimation) < 2:
        return _missing_result(
            event_id,
            symbol,
            "insufficient_estimation_data",
            t0_date=t0_date,
            estimation_window=_window_dict(config.estimation_window_start, config.estimation_window_end),
            available_rows=len(returns),
        )
    if event_window.empty:
        return _missing_result(
            event_id,
            symbol,
            "missing_event_window_data",
            t0_date=t0_date,
            event_window=_window_dict(config.event_window_start, config.event_window_end),
        )

    alpha, beta = estimate_market_model(estimation)
    if alpha is None or beta is None:
        return _missing_result(event_id, symbol, "market_model_estimation_failed", t0_date)

    event_window["expected_return"] = alpha + beta * event_window["benchmark_return"]
    event_window["abnormal_return"] = (
        event_window["asset_return"] - event_window["expected_return"]
    )
    car = float(event_window["abnormal_return"].sum())

    estimation_abnormal_returns = estimation["asset_return"] - (
        alpha + beta * estimation["benchmark_return"]
    )
    ar_std = float(estimation_abnormal_returns.std(ddof=1))
    event_days = len(event_window)
    if np.isfinite(ar_std) and ar_std > MIN_ABNORMAL_RETURN_STD and event_days > 0:
        standardized_car = car / (ar_std * (event_days ** 0.5))
        hit = bool(abs(standardized_car) >= config.significance_threshold)
    else:
        standardized_car = None
        hit = False

    return {
        "event_id": event_id,
        "symbol": symbol,
        "car": car,
        "standardized_car": standardized_car,
        "hit": hit,
        "direction": _direction(car),
        "missing_data_reason": None,
        "supporting_notes": [
            f"t0_date={t0_date.date().isoformat()}",
            f"alpha={alpha}",
            f"beta={beta}",
            f"ar_std={ar_std}",
            f"standardized_car={standardized_car}",
            f"significance_threshold={config.significance_threshold}",
            "method=market_model",
            "hit_rule=abs_standardized_car",
        ],
        "t0_date": t0_date.date().isoformat(),
        "alpha": alpha,
        "beta": beta,
        "event_window_abnormal_returns": event_window[
            ["date", "asset_return", "benchmark_return", "expected_return", "abnormal_return"]
        ].assign(date=lambda frame: frame["date"].dt.strftime("%Y-%m-%d")).to_dict(
            orient="records"
        ),
    }


def align_asset_and_benchmark_returns(
    asset_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
) -> pd.DataFrame:
    """Compute simple returns and align asset and benchmark by trading date."""

    asset_returns = _compute_returns(asset_prices).rename(
        columns={"return": "asset_return"}
    )
    benchmark_returns = _compute_returns(benchmark_prices).rename(
        columns={"return": "benchmark_return"}
    )
    aligned = asset_returns[["date", "asset_return"]].merge(
        benchmark_returns[["date", "benchmark_return"]],
        on="date",
        how="inner",
    )
    return aligned.sort_values("date").reset_index(drop=True)


def align_event_date_to_next_trading_day(
    available_dates: pd.Series,
    event_date: pd.Timestamp,
) -> pd.Timestamp | None:
    """Align an event date to the nearest next available trading day."""

    dates = pd.Series(pd.to_datetime(available_dates).sort_values().unique())
    candidates = dates[dates >= event_date]
    if candidates.empty:
        return None
    return pd.Timestamp(candidates.iloc[0])


def estimate_market_model(returns: pd.DataFrame) -> tuple[float | None, float | None]:
    """Estimate alpha and beta for asset_return = alpha + beta * benchmark_return."""

    clean = returns.dropna(subset=["asset_return", "benchmark_return"])
    if len(clean) < 2:
        return None, None

    x = clean["benchmark_return"].to_numpy(dtype=float)
    y = clean["asset_return"].to_numpy(dtype=float)
    if np.var(x) == 0:
        return None, None

    beta, alpha = np.polyfit(x, y, deg=1)
    return float(alpha), float(beta)


def _compute_returns(price_frame: pd.DataFrame) -> pd.DataFrame:
    """Compute simple daily returns from a normalized price dataframe."""

    ordered = price_frame.sort_values("date").copy()
    ordered["return"] = ordered["adj_close"].pct_change()
    return ordered.dropna(subset=["return"]).reset_index(drop=True)


def _price_column(frame: pd.DataFrame) -> str:
    """Return the adjusted close column if present, otherwise Close."""

    if "Adj Close" in frame.columns:
        return "Adj Close"
    if "Close" in frame.columns:
        return "Close"
    raise ValueError("Price CSV must include either Adj Close or Close.")


def _load_price_series_from_yfinance(
    symbol: str,
    start: str | None,
    end: str | None,
) -> tuple[pd.DataFrame | None, str | None]:
    """Optionally load prices from yfinance when available."""

    try:
        import yfinance as yf
    except ImportError:
        return None, "yfinance_not_installed"

    try:
        raw = yf.download(
            symbol,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        return None, f"yfinance_download_failed: {type(exc).__name__}: {exc}"

    if raw.empty or "Close" not in raw.columns:
        return None, "yfinance_no_price_data"

    frame = raw[["Close"]].reset_index()
    frame.columns = ["date", "adj_close"]
    frame["symbol"] = symbol
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adj_close"] = pd.to_numeric(frame["adj_close"], errors="coerce")
    return frame.dropna(subset=["date", "adj_close"]).reset_index(drop=True), None


def _missing_result(
    event_id: str,
    symbol: str,
    reason: str,
    detail: str | None = None,
    **diagnostics: Any,
) -> dict[str, Any]:
    """Return a CARResult-compatible missing-data result."""

    notes = [detail] if detail else []
    return {
        "event_id": event_id,
        "symbol": symbol,
        "car": None,
        "standardized_car": None,
        "hit": False,
        "direction": None,
        "missing_data_reason": reason,
        "supporting_notes": notes,
        **diagnostics,
    }


def _window_dict(start: int, end: int) -> dict[str, int]:
    """Return a serializable trading-day window descriptor."""

    return {"start": start, "end": end}


def _direction(car: float) -> str:
    """Return informational CAR direction."""

    if car > 0:
        return "positive"
    if car < 0:
        return "negative"
    return "neutral"
