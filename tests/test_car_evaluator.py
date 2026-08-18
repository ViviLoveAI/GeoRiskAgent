import pandas as pd

from src.eval.car.car_evaluator import evaluate_car
from src.eval.car.report import print_summary
from src.eval.car.schemas import CarWindowConfig


def _price_frame(symbol: str, dates: pd.DatetimeIndex, start: float, event_dates=None):
    event_dates = set(event_dates or [])
    price = start
    rows = []
    for idx, day in enumerate(dates):
        if idx:
            ret = 0.001
            if symbol != "SPY":
                ret += ((idx % 5) - 2) * 0.0002
            if day in event_dates:
                ret += 0.03
            price *= 1 + ret
        rows.append({"date": day, "symbol": symbol, "adj_close": price})
    return pd.DataFrame(rows)


def test_evaluate_car_records_missing_asset_prices_and_valid_rows():
    dates = pd.bdate_range("2024-01-01", periods=30)
    events = pd.DataFrame(
        {
            "event_id": ["event_1"],
            "event_date": [pd.Timestamp(dates[20])],
            "event_description": ["held-out event"],
            "notes": [""],
        }
    )
    predictions = pd.DataFrame(
        {
            "event_id": ["event_1", "event_1"],
            "symbol": ["AAA", "MISSING"],
            "node": ["energy", "logistics"],
            "asset_type": ["equity", "equity"],
            "confidence": [0.8, 0.4],
            "evidence_label": ["historical_supported", "inference_only"],
        }
    )
    prices = _price_frame("AAA", dates, 100.0, event_dates=[dates[20]])
    benchmark = _price_frame("SPY", dates, 400.0)
    config = CarWindowConfig(
        event_window_start=0,
        event_window_end=1,
        estimation_window_start=-10,
        estimation_window_end=-2,
        hit_threshold=2.0,
    )

    report = evaluate_car(events, predictions, prices, benchmark, "SPY", config)

    assert len(report) == 2
    assert set(report["group"]) == {"georisk_flagged"}
    assert (report["group"] == "georisk_flagged").all()
    assert report.loc[report["symbol"] == "AAA", "missing_data_reason"].iloc[0] == ""
    assert report.loc[report["symbol"] == "AAA", "estimation_std_abnormal_return"].iloc[0] > 0
    assert (
        report.loc[report["symbol"] == "MISSING", "missing_data_reason"].iloc[0]
        == "missing_asset_prices"
    )
    assert pd.isna(
        report.loc[
            report["symbol"] == "MISSING", "estimation_std_abnormal_return"
        ].iloc[0]
    )


def test_evaluate_car_uses_next_trading_day_for_weekend_event():
    dates = pd.bdate_range("2024-01-01", periods=30)
    events = pd.DataFrame(
        {
            "event_id": ["event_1"],
            "event_date": [pd.Timestamp("2024-01-13")],
            "event_description": ["weekend event"],
            "notes": [""],
        }
    )
    predictions = pd.DataFrame(
        {
            "event_id": ["event_1"],
            "symbol": ["AAA"],
            "node": ["energy"],
            "asset_type": ["equity"],
            "confidence": [0.8],
            "evidence_label": ["sector_proxy"],
        }
    )
    prices = _price_frame("AAA", dates, 100.0, event_dates=[pd.Timestamp("2024-01-15")])
    benchmark = _price_frame("SPY", dates, 400.0)
    config = CarWindowConfig(
        event_window_start=0,
        event_window_end=0,
        estimation_window_start=-5,
        estimation_window_end=-1,
        hit_threshold=2.0,
    )

    report = evaluate_car(events, predictions, prices, benchmark, "SPY", config)

    assert report["t0_date"].iloc[0] == "2024-01-15"


def test_evaluate_car_records_no_overlapping_return_dates():
    asset_dates = pd.bdate_range("2024-01-01", periods=30)
    benchmark_dates = pd.bdate_range("2024-03-01", periods=30)
    events = pd.DataFrame(
        {
            "event_id": ["event_1"],
            "event_date": [pd.Timestamp(asset_dates[20])],
            "event_description": ["held-out event"],
            "notes": [""],
        }
    )
    predictions = pd.DataFrame(
        {
            "event_id": ["event_1"],
            "symbol": ["AAA"],
            "node": ["energy"],
            "asset_type": ["equity"],
            "confidence": [0.8],
            "evidence_label": ["sector_proxy"],
        }
    )
    prices = _price_frame("AAA", asset_dates, 100.0)
    benchmark = _price_frame("SPY", benchmark_dates, 400.0)
    config = CarWindowConfig(
        event_window_start=0,
        event_window_end=1,
        estimation_window_start=-10,
        estimation_window_end=-2,
    )

    report = evaluate_car(events, predictions, prices, benchmark, "SPY", config)

    assert report["missing_data_reason"].iloc[0] == "no_overlapping_return_dates"
    assert report["group"].iloc[0] == "georisk_flagged"


def test_evaluate_car_includes_optional_baseline_assets():
    dates = pd.bdate_range("2024-01-01", periods=30)
    events = pd.DataFrame(
        {
            "event_id": ["event_1"],
            "event_date": [pd.Timestamp(dates[20])],
            "event_description": ["held-out event"],
            "notes": [""],
        }
    )
    predictions = pd.DataFrame(
        {
            "event_id": ["event_1"],
            "symbol": ["AAA"],
            "node": ["energy"],
            "asset_type": ["equity"],
            "confidence": [0.8],
            "evidence_label": ["historical_supported"],
        }
    )
    baseline_assets = pd.DataFrame(
        {
            "event_id": ["event_1"],
            "symbol": ["BBB"],
            "node": ["broad_market"],
            "asset_type": ["equity_etf"],
            "baseline_type": ["random_baseline"],
        }
    )
    prices = pd.concat(
        [
            _price_frame("AAA", dates, 100.0, event_dates=[dates[20]]),
            _price_frame("BBB", dates, 50.0),
        ],
        ignore_index=True,
    )
    benchmark = _price_frame("SPY", dates, 400.0)
    config = CarWindowConfig(
        event_window_start=0,
        event_window_end=1,
        estimation_window_start=-10,
        estimation_window_end=-2,
        hit_threshold=2.0,
    )

    report = evaluate_car(
        events,
        predictions,
        prices,
        benchmark,
        "SPY",
        config,
        baseline_assets=baseline_assets,
    )

    assert len(report) == 2
    assert set(report["group"]) == {"georisk_flagged", "baseline"}
    assert report.loc[report["group"] == "georisk_flagged", "symbol"].iloc[0] == "AAA"
    baseline_row = report.loc[report["group"] == "baseline"].iloc[0]
    assert baseline_row["symbol"] == "BBB"
    assert baseline_row["baseline_type"] == "random_baseline"
    assert baseline_row["evidence_label"] == ""
    assert pd.isna(baseline_row["confidence"])


def test_print_summary_without_baseline_reports_georisk_counts(capsys):
    report = pd.DataFrame(
        {
            "event_id": ["event_1", "event_1"],
            "group": ["georisk_flagged", "georisk_flagged"],
            "symbol": ["AAA", "MISSING"],
            "node": ["energy", "logistics"],
            "evidence_label": ["historical_supported", "inference_only"],
            "baseline_type": ["", ""],
            "hit": [True, False],
            "missing_data_reason": ["", "missing_asset_prices"],
        }
    )

    print_summary(report)

    output = capsys.readouterr().out
    assert "total_evaluated_pairs: 1" in output
    assert "skipped_pairs: 1" in output
    assert "georisk_evaluated_pairs: 1" in output
    assert "georisk_skipped_pairs: 1" in output
    assert "baseline_evaluated_pairs: 0" in output
    assert "unique_symbols_evaluated: 1" in output
    assert "unique_symbols_skipped: 1" in output
    assert "hit_rate_by_node_georisk_flagged:" in output
    assert "hit_rate_by_node_baseline:" not in output
    assert "baseline_hit_rate:" not in output


def test_print_summary_with_baseline_reports_separate_node_rates(capsys):
    report = pd.DataFrame(
        {
            "event_id": ["event_1", "event_1", "event_1"],
            "group": ["georisk_flagged", "baseline", "baseline"],
            "symbol": ["AAA", "QQQ", "MISSING_BASE"],
            "node": ["energy", "broad_market", "financials"],
            "evidence_label": ["sector_proxy", "", ""],
            "baseline_type": ["", "random_baseline", "sector_baseline"],
            "hit": [True, False, False],
            "missing_data_reason": ["", "", "missing_asset_prices"],
        }
    )

    print_summary(report)

    output = capsys.readouterr().out
    assert "total_evaluated_pairs: 2" in output
    assert "skipped_pairs: 1" in output
    assert "georisk_evaluated_pairs: 1" in output
    assert "baseline_evaluated_pairs: 1" in output
    assert "baseline_skipped_pairs: 1" in output
    assert "baseline_hit_rate: 0.00" in output
    assert "hit_rate_by_node_georisk_flagged:" in output
    assert "hit_rate_by_node_baseline:" in output
    assert "hit_rate_by_baseline_type:" in output
