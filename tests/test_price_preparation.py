import pandas as pd

from src.validation.car_calculator import MarketModelConfig
from src.validation.price_preparation import (
    calculate_required_price_range,
    collect_required_symbols_from_snapshots,
    has_sufficient_coverage,
    prepare_price_csvs,
)


def test_collect_required_symbols_dedupes_snapshots_baselines_and_benchmark():
    snapshots = [
        {
            "event_id": "event_1",
            "predicted_exposures": [
                {"symbol": "aaa"},
                {"symbol": "BBB"},
                {"symbol": "AAA"},
            ],
        }
    ]
    baselines = {"event_1": [{"symbol": "bbb"}, {"symbol": "QQQ"}]}

    symbols = collect_required_symbols_from_snapshots(snapshots, baselines, "spy")

    assert symbols == ["AAA", "BBB", "QQQ", "SPY"]


def test_calculate_required_price_range_uses_buffer_and_reports_invalid_dates():
    start, end, invalid = calculate_required_price_range(
        ["2024-06-03", "not-a-date"],
        MarketModelConfig(
            estimation_window_start=-10,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
    )

    assert invalid == ["not-a-date"]
    assert start < pd.Timestamp("2024-06-03")
    assert end > pd.Timestamp("2024-06-03")


def test_prepare_price_csvs_reuses_existing_sufficient_csv(tmp_path):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    _write_price_csv(price_dir / "AAA.csv", "2024-01-01", periods=80)
    calls = []

    report = prepare_price_csvs(
        symbols=["AAA"],
        event_dates=["2024-02-15"],
        price_dir=price_dir,
        config=MarketModelConfig(
            estimation_window_start=-5,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
        download_fn=lambda symbol, start, end: calls.append(symbol) or pd.DataFrame(),
    )

    assert report["reused_symbols"] == ["AAA"]
    assert report["downloaded_symbols"] == []
    assert calls == []


def test_prepare_price_csvs_updates_insufficient_csv(tmp_path):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    _write_price_csv(price_dir / "AAA.csv", "2024-02-01", periods=3)

    def download(symbol, start, end):
        dates = pd.date_range(start, end, freq="D")
        return pd.DataFrame({"Date": dates, "Adj Close": range(100, 100 + len(dates))})

    report = prepare_price_csvs(
        symbols=["AAA"],
        event_dates=["2024-02-15"],
        price_dir=price_dir,
        config=MarketModelConfig(
            estimation_window_start=-5,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
        download_fn=download,
    )

    saved = pd.read_csv(price_dir / "AAA.csv")
    required_start = pd.Timestamp(report["required_start"])
    required_end = pd.Timestamp(report["required_end"])
    assert report["downloaded_symbols"] == ["AAA"]
    assert has_sufficient_coverage(saved, required_start, required_end)


def test_prepare_price_csvs_records_failed_download_without_crashing(tmp_path):
    report = prepare_price_csvs(
        symbols=["MISSING"],
        event_dates=["2024-02-15"],
        price_dir=tmp_path / "prices",
        config=MarketModelConfig(
            estimation_window_start=-5,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
        download_fn=lambda symbol, start, end: pd.DataFrame(),
    )

    assert report["failed_symbols"][0]["symbol"] == "MISSING"


def _write_price_csv(path, start, periods):
    dates = pd.date_range(start, periods=periods, freq="D")
    rows = ["Date,Adj Close"]
    rows.extend(f"{date.date().isoformat()},{100 + index}" for index, date in enumerate(dates))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
