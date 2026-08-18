import pandas as pd

from src.eval.car.car_calculator import (
    calculate_car_for_event,
    compute_abnormal_returns,
    compute_daily_returns,
)
from src.eval.car.schemas import CarWindowConfig


def test_compute_daily_returns_uses_simple_returns():
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "symbol": ["AAA", "AAA", "AAA"],
            "adj_close": [100.0, 110.0, 99.0],
        }
    )

    returns = compute_daily_returns(prices)

    assert returns["return"].round(6).tolist() == [0.1, -0.1]


def test_compute_abnormal_returns_subtracts_benchmark_returns():
    asset_returns = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "return": [0.03, -0.01],
        }
    )
    benchmark_returns = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "return": [0.01, -0.02],
        }
    )

    abnormal = compute_abnormal_returns(asset_returns, benchmark_returns)

    assert abnormal["abnormal_return"].round(6).tolist() == [0.02, 0.01]


def test_calculate_car_standardized_car_and_absolute_hit():
    dates = pd.bdate_range("2024-01-01", periods=20)
    abnormal = [0.01, -0.01] * 10
    frame = pd.DataFrame({"date": dates, "abnormal_return": abnormal})
    frame.loc[10:11, "abnormal_return"] = [-0.08, -0.07]
    config = CarWindowConfig(
        event_window_start=0,
        event_window_end=1,
        estimation_window_start=-10,
        estimation_window_end=-1,
        hit_threshold=2.0,
    )

    result = calculate_car_for_event(frame, pd.Timestamp(dates[10]), config)

    assert round(result["car"], 6) == -0.15
    assert result["standardized_car"] < -2.0
    assert result["hit"] is True
    assert result["direction"] == "negative"
    assert result["estimation_std_abnormal_return"] > 0


def test_near_zero_estimation_std_suppresses_standardized_car_and_hit():
    dates = pd.bdate_range("2024-01-01", periods=20)
    frame = pd.DataFrame(
        {
            "date": dates,
            "abnormal_return": [0.0000001] * 20,
        }
    )
    frame.loc[10:11, "abnormal_return"] = [0.04, 0.03]
    config = CarWindowConfig(
        event_window_start=0,
        event_window_end=1,
        estimation_window_start=-10,
        estimation_window_end=-1,
        hit_threshold=2.0,
    )

    result = calculate_car_for_event(frame, pd.Timestamp(dates[10]), config)

    assert round(result["car"], 6) == 0.07
    assert result["missing_data_reason"] == "zero_or_near_zero_estimation_std"
    assert pd.isna(result["standardized_car"])
    assert result["hit"] is False
    assert result["direction"] == "positive"


def test_non_trading_event_date_uses_next_available_trading_day():
    dates = pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"])
    frame = pd.DataFrame({"date": dates, "abnormal_return": [0.01, 0.04, -0.01, 0.02]})
    config = CarWindowConfig(
        event_window_start=0,
        event_window_end=0,
        estimation_window_start=-1,
        estimation_window_end=-1,
        hit_threshold=2.0,
    )

    result = calculate_car_for_event(frame, pd.Timestamp("2024-01-06"), config)

    assert result["t0_date"] == "2024-01-08"


def test_insufficient_estimation_window_returns_missing_reason():
    frame = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=5),
            "abnormal_return": [0.01, 0.02, 0.03, 0.04, 0.05],
        }
    )
    config = CarWindowConfig(
        event_window_start=0,
        event_window_end=0,
        estimation_window_start=-10,
        estimation_window_end=-2,
    )

    result = calculate_car_for_event(frame, pd.Timestamp("2024-01-03"), config)

    assert result["missing_data_reason"] == "insufficient_estimation_window"
    assert pd.isna(result["estimation_std_abnormal_return"])
    assert result["hit"] is False
