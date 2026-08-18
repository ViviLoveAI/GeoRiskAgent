import pandas as pd

from src.validation.car_calculator import (
    MarketModelConfig,
    align_event_date_to_next_trading_day,
    calculate_market_model_car,
    calculate_market_model_car_from_prices,
    estimate_market_model,
    load_price_series_from_csv,
)


def _prices(symbol: str, dates: pd.DatetimeIndex, returns: list[float], start=100.0):
    price = start
    rows = [{"date": dates[0], "adj_close": price, "symbol": symbol}]
    for date, daily_return in zip(dates[1:], returns, strict=True):
        price *= 1 + daily_return
        rows.append({"date": date, "adj_close": price, "symbol": symbol})
    return pd.DataFrame(rows)


def test_load_price_series_from_csv_prefers_adj_close(tmp_path):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "AAA.csv").write_text(
        "Date,Close,Adj Close\n2024-01-01,10,9\n2024-01-02,11,10\n",
        encoding="utf-8",
    )

    prices = load_price_series_from_csv("AAA", price_dir)

    assert prices["adj_close"].tolist() == [9, 10]


def test_load_price_series_from_csv_supports_close(tmp_path):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "AAA.csv").write_text(
        "Date,Close\n2024-01-01,10\n2024-01-02,11\n",
        encoding="utf-8",
    )

    prices = load_price_series_from_csv("AAA", price_dir)

    assert prices["adj_close"].tolist() == [10, 11]


def test_calculator_skips_asset_equal_to_benchmark(tmp_path):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "SPY.csv").write_text(
        "Date,Adj Close\n2024-01-01,400\n2024-01-02,401\n",
        encoding="utf-8",
    )

    result = calculate_market_model_car(
        event_id="event_spy",
        symbol="SPY",
        benchmark_symbol="SPY",
        event_date="2024-01-02",
        price_dir=price_dir,
    )

    assert result["missing_data_reason"] == "asset_equals_benchmark"
    assert result["standardized_car"] is None
    assert result["hit"] is False


def test_align_event_date_to_next_trading_day():
    dates = pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09"])

    t0 = align_event_date_to_next_trading_day(pd.Series(dates), pd.Timestamp("2024-01-06"))

    assert t0 == pd.Timestamp("2024-01-08")


def test_estimate_market_model_alpha_beta():
    returns = pd.DataFrame(
        {
            "asset_return": [0.01, 0.03, 0.05, 0.07],
            "benchmark_return": [0.00, 0.01, 0.02, 0.03],
        }
    )

    alpha, beta = estimate_market_model(returns)

    assert round(alpha, 6) == 0.01
    assert round(beta, 6) == 2.0


def test_calculate_market_model_car_from_prices():
    dates = pd.bdate_range("2024-01-01", periods=20)
    benchmark_returns = [0.001 + ((index % 5) - 2) * 0.0002 for index in range(19)]
    asset_returns = [
        0.001 + 1.2 * benchmark_return + ((index % 3) - 1) * 0.0003
        for index, benchmark_return in enumerate(benchmark_returns)
    ]
    asset_returns[14] = 0.012
    asset_returns[15] = 0.013
    asset_returns[16] = 0.014
    asset_prices = _prices("AAA", dates, asset_returns)
    benchmark_prices = _prices("SPY", dates, benchmark_returns, start=400.0)
    config = MarketModelConfig(
        estimation_window_start=-10,
        estimation_window_end=-2,
        event_window_start=-1,
        event_window_end=1,
    )

    result = calculate_market_model_car_from_prices(
        event_id="event_1",
        symbol="AAA",
        event_date=str(dates[15].date()),
        asset_prices=asset_prices,
        benchmark_prices=benchmark_prices,
        config=config,
    )

    assert result["missing_data_reason"] is None
    assert result["car"] > 0
    assert result["standardized_car"] is not None
    assert result["hit"] is True
    assert result["direction"] == "positive"
    assert result["t0_date"] == str(dates[15].date())
    assert result["alpha"] is not None
    assert result["beta"] is not None
    assert len(result["event_window_abnormal_returns"]) == 3


def test_calculate_market_model_car_reports_missing_asset_prices(tmp_path):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "SPY.csv").write_text(
        "Date,Adj Close\n2024-01-01,400\n2024-01-02,401\n",
        encoding="utf-8",
    )

    result = calculate_market_model_car(
        event_id="event_1",
        symbol="AAA",
        benchmark_symbol="SPY",
        event_date="2024-01-02",
        price_dir=price_dir,
    )

    assert result["missing_data_reason"] == "missing_asset_prices"
    assert result["expected_csv_path"].endswith("AAA.csv")


def test_calculate_market_model_car_reports_missing_benchmark_prices(tmp_path):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "AAA.csv").write_text(
        "Date,Adj Close\n2024-01-01,100\n2024-01-02,101\n",
        encoding="utf-8",
    )

    result = calculate_market_model_car(
        event_id="event_1",
        symbol="AAA",
        benchmark_symbol="SPY",
        event_date="2024-01-02",
        price_dir=price_dir,
    )

    assert result["missing_data_reason"] == "missing_benchmark_prices"
    assert result["benchmark"] == "SPY"
    assert result["expected_benchmark_csv_path"].endswith("SPY.csv")


def test_calculate_market_model_car_reports_insufficient_estimation_window():
    dates = pd.bdate_range("2024-01-01", periods=5)
    asset_prices = _prices("AAA", dates, [0.002] * 4)
    benchmark_prices = _prices("SPY", dates, [0.001] * 4)

    result = calculate_market_model_car_from_prices(
        event_id="event_1",
        symbol="AAA",
        event_date=str(dates[3].date()),
        asset_prices=asset_prices,
        benchmark_prices=benchmark_prices,
        config=MarketModelConfig(),
    )

    assert result["missing_data_reason"] == "insufficient_estimation_data"
    assert result["estimation_window"] == {"start": -130, "end": -10}
    assert result["available_rows"] == 4


def test_negative_standardized_car_counts_as_magnitude_hit():
    dates = pd.bdate_range("2024-01-01", periods=25)
    benchmark_returns = [0.001 + ((index % 5) - 2) * 0.0002 for index in range(24)]
    asset_returns = [
        0.001 + 1.1 * benchmark_return + ((index % 3) - 1) * 0.0003
        for index, benchmark_return in enumerate(benchmark_returns)
    ]
    asset_returns[14] = -0.025
    asset_returns[15] = -0.024
    asset_returns[16] = -0.023
    asset_prices = _prices("AAA", dates, asset_returns)
    benchmark_prices = _prices("SPY", dates, benchmark_returns, start=400.0)
    config = MarketModelConfig(
        estimation_window_start=-10,
        estimation_window_end=-2,
        event_window_start=-1,
        event_window_end=1,
    )

    result = calculate_market_model_car_from_prices(
        event_id="event_1",
        symbol="AAA",
        event_date=str(dates[15].date()),
        asset_prices=asset_prices,
        benchmark_prices=benchmark_prices,
        config=config,
    )

    assert result["missing_data_reason"] is None
    assert result["standardized_car"] <= -1.96
    assert result["hit"] is True
    assert result["direction"] == "negative"


def test_zero_abnormal_return_variance_leaves_standardized_car_unavailable():
    dates = pd.bdate_range("2024-01-01", periods=20)
    benchmark_returns = [0.001 + ((index % 5) - 2) * 0.0002 for index in range(19)]
    asset_returns = [0.001 + 1.2 * benchmark_return for benchmark_return in benchmark_returns]
    asset_returns[14] = 0.03
    asset_returns[15] = 0.03
    asset_returns[16] = 0.03
    asset_prices = _prices("AAA", dates, asset_returns)
    benchmark_prices = _prices("SPY", dates, benchmark_returns, start=400.0)
    config = MarketModelConfig(
        estimation_window_start=-10,
        estimation_window_end=-2,
        event_window_start=-1,
        event_window_end=1,
    )

    result = calculate_market_model_car_from_prices(
        event_id="event_1",
        symbol="AAA",
        event_date=str(dates[15].date()),
        asset_prices=asset_prices,
        benchmark_prices=benchmark_prices,
        config=config,
    )

    assert result["missing_data_reason"] is None
    assert result["standardized_car"] is None
    assert result["hit"] is False


def test_estimate_market_model_fails_for_zero_benchmark_variance():
    returns = pd.DataFrame(
        {
            "asset_return": [0.01, 0.02, 0.03],
            "benchmark_return": [0.01, 0.01, 0.01],
        }
    )

    assert estimate_market_model(returns) == (None, None)
