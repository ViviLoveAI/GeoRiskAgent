import sys

import pandas as pd

from src.eval.car import yfinance_fetcher


def test_collect_tickers_from_predictions_baseline_and_benchmark():
    predicted = pd.DataFrame({"symbol": ["xle", "LMT", "XLE"]})
    baseline = pd.DataFrame({"symbol": ["QQQ", "xlf"]})

    tickers = yfinance_fetcher.collect_tickers(predicted, baseline, "spy")

    assert tickers == ["XLE", "LMT", "QQQ", "XLF", "SPY"]


def test_calculate_download_range_from_event_dates():
    events = pd.DataFrame(
        {"event_date": ["2022-02-24", "2023-10-07", "2022-08-04"]}
    )

    start, end = yfinance_fetcher.calculate_download_range(events, 260, 10)

    assert start == pd.Timestamp("2021-06-09")
    assert end == pd.Timestamp("2023-10-17")


def test_transform_yfinance_multiindex_to_long_format():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    columns = pd.MultiIndex.from_product([["AAA", "SPY"], ["Close", "Volume"]])
    raw = pd.DataFrame(
        [
            [10.0, 100, 400.0, 1000],
            [10.5, 110, 402.0, 1200],
        ],
        index=dates,
        columns=columns,
    )

    long = yfinance_fetcher.transform_yfinance_prices(raw)

    assert list(long.columns) == ["date", "symbol", "adj_close"]
    assert len(long) == 4
    assert set(long["symbol"]) == {"AAA", "SPY"}
    assert long.loc[long["symbol"] == "AAA", "adj_close"].tolist() == [10.0, 10.5]


def test_split_benchmark_rows_separates_assets_and_benchmark():
    long = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-02", "2024-01-02"],
            "symbol": ["AAA", "SPY", "QQQ"],
            "adj_close": [10.0, 400.0, 330.0],
        }
    )

    assets, benchmark = yfinance_fetcher.split_benchmark_rows(long, "SPY")

    assert set(assets["symbol"]) == {"AAA", "QQQ"}
    assert benchmark["symbol"].tolist() == ["SPY"]


def test_missing_yfinance_is_handled_gracefully(monkeypatch, capsys):
    real_import = __import__
    monkeypatch.setitem(sys.modules, "yfinance", None)

    def fake_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("missing yfinance")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    result = yfinance_fetcher.fetch_prices_with_yfinance(
        ["SPY"],
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-10"),
    )

    output = capsys.readouterr().out
    assert result.empty
    assert "yfinance is not installed. Install it with: pip install yfinance" in output
