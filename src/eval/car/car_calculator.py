"""CAR calculation utilities.

The MVP uses simple daily returns and a market-adjusted abnormal return model:

``asset_return_t = adj_close_t / adj_close_t-1 - 1``
``benchmark_return_t = benchmark_adj_close_t / benchmark_adj_close_t-1 - 1``
``abnormal_return_t = asset_return_t - benchmark_return_t``

CAR is the sum of abnormal returns over a trading-day event window. The hit
test uses absolute standardized CAR because GeoRisk predicts exposure, not
price direction.
"""

from __future__ import annotations

import math

import pandas as pd

from src.eval.car.schemas import CarWindowConfig

MIN_ESTIMATION_STD_ABNORMAL_RETURN = 1e-6


def compute_daily_returns(price_frame: pd.DataFrame) -> pd.DataFrame:
    """Compute simple daily returns for a single-symbol price series."""

    if price_frame.empty:
        return pd.DataFrame(columns=["date", "symbol", "adj_close", "return"])

    ordered = price_frame.sort_values("date").copy()
    ordered["return"] = ordered["adj_close"].pct_change()
    return ordered.dropna(subset=["return"]).reset_index(drop=True)


def compute_abnormal_returns(
    asset_returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
) -> pd.DataFrame:
    """Align asset and benchmark returns and compute abnormal returns."""

    asset = asset_returns[["date", "return"]].rename(columns={"return": "asset_return"})
    benchmark = benchmark_returns[["date", "return"]].rename(
        columns={"return": "benchmark_return"}
    )
    merged = asset.merge(benchmark, on="date", how="inner")
    merged["abnormal_return"] = merged["asset_return"] - merged["benchmark_return"]
    return merged.sort_values("date").reset_index(drop=True)


def locate_t0_date(available_dates: pd.Series, event_date: pd.Timestamp) -> pd.Timestamp | None:
    """Return the event trading date, using the next available date if needed."""

    dates = pd.Series(pd.to_datetime(available_dates).sort_values().unique())
    candidates = dates[dates >= event_date]
    if candidates.empty:
        return None
    return pd.Timestamp(candidates.iloc[0])


def calculate_car_for_event(
    abnormal_returns: pd.DataFrame,
    event_date: pd.Timestamp,
    config: CarWindowConfig,
) -> dict[str, object]:
    """Calculate CAR, standardized CAR, hit, and missing-data status.

    Windows are interpreted in trading-day index positions over the available
    abnormal-return dates, not calendar-day offsets.
    """

    if abnormal_returns.empty:
        return _missing("missing_asset_prices")

    ordered = abnormal_returns.sort_values("date").reset_index(drop=True)
    t0_date = locate_t0_date(ordered["date"], event_date)
    if t0_date is None:
        return _missing("event_date_out_of_range")

    matches = ordered.index[ordered["date"] == t0_date].tolist()
    if not matches:
        return _missing("event_date_out_of_range")
    t0_index = matches[0]

    event_start = t0_index + config.event_window_start
    event_end = t0_index + config.event_window_end
    if event_start < 0 or event_end >= len(ordered):
        return _missing("insufficient_event_window", t0_date=t0_date)

    estimation_start = t0_index + config.estimation_window_start
    estimation_end = t0_index + config.estimation_window_end
    if estimation_start < 0 or estimation_end >= len(ordered) or estimation_start > estimation_end:
        return _missing("insufficient_estimation_window", t0_date=t0_date)

    event_window = ordered.iloc[event_start : event_end + 1]
    estimation_window = ordered.iloc[estimation_start : estimation_end + 1]
    if event_window.empty:
        return _missing("insufficient_event_window", t0_date=t0_date)
    if estimation_window.empty:
        return _missing("insufficient_estimation_window", t0_date=t0_date)

    car = float(event_window["abnormal_return"].sum())
    estimation_std = float(estimation_window["abnormal_return"].std(ddof=1))
    if (
        math.isnan(estimation_std)
        or estimation_std == 0.0
        or estimation_std < MIN_ESTIMATION_STD_ABNORMAL_RETURN
    ):
        return {
            "t0_date": t0_date.date().isoformat(),
            "car": car,
            "estimation_std_abnormal_return": estimation_std,
            "standardized_car": math.nan,
            "hit": False,
            "direction": direction_from_car(car),
            "missing_data_reason": "zero_or_near_zero_estimation_std",
        }

    standardized_car = car / (estimation_std * math.sqrt(len(event_window)))
    return {
        "t0_date": t0_date.date().isoformat(),
        "car": car,
        "estimation_std_abnormal_return": estimation_std,
        "standardized_car": standardized_car,
        "hit": abs(standardized_car) >= config.hit_threshold,
        "direction": direction_from_car(car),
        "missing_data_reason": "",
    }


def direction_from_car(car: float) -> str:
    """Return informational CAR direction; direction is not used for hit logic."""

    if car > 0:
        return "positive"
    if car < 0:
        return "negative"
    return "neutral"


def _missing(reason: str, t0_date: pd.Timestamp | None = None) -> dict[str, object]:
    """Return a consistent missing-data calculation result."""

    return {
        "t0_date": t0_date.date().isoformat() if t0_date is not None else "",
        "car": math.nan,
        "estimation_std_abnormal_return": math.nan,
        "standardized_car": math.nan,
        "hit": False,
        "direction": "",
        "missing_data_reason": reason,
    }
