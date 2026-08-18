import csv
import json

import pandas as pd

from src.validation.exposure_evaluator import (
    evaluate_exposure_results,
    magnitude_hit,
    split_evaluated_and_skipped,
)
from src.validation.car_calculator import MarketModelConfig
from src.validation.run_car_validation import (
    build_missing_price_files_report,
    run_car_validation,
)


def test_magnitude_hit_logic():
    assert magnitude_hit({"standardized_car": 2.1, "hit": True}) is True
    assert magnitude_hit({"standardized_car": -2.1, "hit": True}) is True
    assert magnitude_hit({"standardized_car": 1.2, "hit": False}) is False
    assert magnitude_hit({"standardized_car": None, "hit": False}) is None


def test_evaluate_exposure_results_summary():
    rows = [
        {
            "event_id": "event_1",
            "symbol": "AAA",
            "car": 0.02,
            "standardized_car": 2.1,
            "hit": True,
            "expected_direction": "positive",
            "source": "georisk",
            "evidence_label": "historical_supported",
            "event_type": "fake_type",
            "missing_data_reason": None,
        },
        {
            "event_id": "event_1",
            "symbol": "BBB",
            "car": 0.01,
            "standardized_car": 2.2,
            "hit": True,
            "expected_direction": "negative",
            "source": "baseline",
            "event_type": "fake_type",
            "missing_data_reason": None,
        },
        {
            "event_id": "event_2",
            "symbol": "CCC",
            "car": None,
            "standardized_car": None,
            "hit": False,
            "expected_direction": "positive",
            "source": "georisk",
            "missing_data_reason": "missing_asset_prices",
        },
    ]

    summary = evaluate_exposure_results(rows)

    assert summary["overall_hit_rate"] == 1.0
    assert summary["georisk_flagged_hit_rate"] == 1.0
    assert summary["baseline_hit_rate"] == 1.0
    assert summary["hit_rate_by_evidence_label"] == {"historical_supported": 1.0}
    assert summary["hit_rate_by_event_type"] == {"fake_type": 1.0}
    assert summary["evaluated_pairs"] == 2
    assert summary["skipped_pairs"] == 1
    assert summary["skipped_reasons"] == {"missing_asset_prices": 1}


def test_evaluate_exposure_results_skips_unavailable_standardized_car():
    rows = [
        {
            "event_id": "event_1",
            "symbol": "AAA",
            "car": 0.02,
            "standardized_car": None,
            "hit": False,
            "expected_direction": None,
            "source": "georisk",
            "missing_data_reason": None,
        }
    ]

    summary = evaluate_exposure_results(rows)

    assert summary["evaluated_pairs"] == 0
    assert summary["skipped_pairs"] == 1
    assert summary["skipped_reasons"] == {"standardized_car_unavailable": 1}
    evaluated, skipped = split_evaluated_and_skipped(rows)
    assert evaluated == []
    assert skipped[0]["missing_data_reason"] == "standardized_car_unavailable"
    assert skipped[0]["skip_reason"] == "standardized_car_unavailable"


def test_run_car_validation_marks_asset_equals_benchmark_as_skipped(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    snapshot_dir = tmp_path / "snapshots"
    result_dir = tmp_path / "results"
    price_dir = tmp_path / "prices"
    price_dir.mkdir()

    manifest.write_text(
        """
validation_events:
  - event_id: event_spy
    event_date: "2024-01-18"
    event_description: "Fake accepted event."
    event_type: fake_type
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
""",
        encoding="utf-8",
    )
    _write_v2_snapshot(
        snapshot_dir,
        "event_spy",
        "2024-01-18",
        "fake_type",
        "SPY",
    )
    _write_price_csv(
        price_dir / "SPY.csv",
        pd.bdate_range("2024-01-01", periods=30),
        [0.001 + ((index % 5) - 2) * 0.0002 for index in range(29)],
        400.0,
    )

    summary = run_car_validation(
        manifest_path=manifest,
        snapshot_dir=snapshot_dir,
        result_dir=result_dir,
        price_dir=price_dir,
        benchmark_symbol="SPY",
        config=MarketModelConfig(
            estimation_window_start=-10,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
    )

    assert summary["evaluated_pairs"] == 0
    assert summary["skipped_pairs"] == 1
    assert summary["skipped_reasons"] == {"asset_equals_benchmark": 1}

    with (result_dir / "car_pair_results.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["missing_data_reason"] == "asset_equals_benchmark"
    assert rows[0]["standardized_car"] == ""
    assert rows[0]["hit"] == "False"

    skipped = json.loads((result_dir / "skipped_pairs.json").read_text())
    assert len(skipped) == 1
    assert skipped[0]["symbol"] == "SPY"
    assert skipped[0]["missing_data_reason"] == "asset_equals_benchmark"
    assert skipped[0]["skip_reason"] == "asset_equals_benchmark"


def test_run_car_validation_writes_outputs(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    snapshot_dir = tmp_path / "snapshots"
    result_dir = tmp_path / "results"
    price_dir = tmp_path / "prices"
    price_dir.mkdir()

    manifest.write_text(
        """
validation_events:
  - event_id: event_1
    event_date: "2024-01-18"
    event_description: "Fake accepted event."
    event_type: fake_type
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
    predicted_exposures:
      - event_id: event_1
        symbol: AAA
        node: fake_node
        asset_type: equity
        confidence: 0.7
        evidence_label: sector_proxy
        expected_direction: positive
        source: georisk
""",
        encoding="utf-8",
    )
    _write_v2_snapshot(
        snapshot_dir,
        "event_1",
        "2024-01-18",
        "fake_type",
        "AAA",
        expected_direction="positive",
    )

    dates = pd.bdate_range("2024-01-01", periods=30)
    benchmark_returns = [0.001 + ((index % 5) - 2) * 0.0002 for index in range(29)]
    asset_returns = [
        0.001 + 1.1 * value + ((index % 3) - 1) * 0.0003
        for index, value in enumerate(benchmark_returns)
    ]
    asset_returns[13] = 0.02
    asset_returns[14] = 0.021
    asset_returns[15] = 0.022
    _write_price_csv(price_dir / "AAA.csv", dates, asset_returns, 100.0)
    _write_price_csv(price_dir / "SPY.csv", dates, benchmark_returns, 400.0)

    summary = run_car_validation(
        manifest_path=manifest,
        snapshot_dir=snapshot_dir,
        result_dir=result_dir,
        price_dir=price_dir,
        benchmark_symbol="SPY",
        config=MarketModelConfig(
            estimation_window_start=-10,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
    )

    assert summary["evaluated_pairs"] == 1
    assert (result_dir / "car_pair_results.csv").exists()
    assert (result_dir / "car_summary.json").exists()
    assert (result_dir / "skipped_pairs.json").exists()
    assert (result_dir / "missing_price_files.json").exists()

    saved_summary = json.loads((result_dir / "car_summary.json").read_text())
    assert saved_summary["georisk_flagged_hit_rate"] == 1.0

    with (result_dir / "car_pair_results.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["event_id"] == "event_1"
    assert rows[0]["linkage_tier"] == "direct_exposure"
    assert rows[0]["linkage_rationale"] == "Fixture direct operating linkage."
    assert rows[0]["transmission_order"] == "first_order"
    assert rows[0]["supporting_case_ids"] == "case_fixture"
    assert float(rows[0]["standardized_car"]) >= 1.96
    assert rows[0]["hit"] == "True"


def test_run_car_validation_writes_missing_asset_price_diagnostics(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    snapshot_dir = tmp_path / "snapshots"
    result_dir = tmp_path / "results"
    price_dir = tmp_path / "prices"
    price_dir.mkdir()

    manifest.write_text(
        """
validation_events:
  - event_id: event_missing_asset
    event_date: "2024-01-18"
    event_description: "Fake accepted event."
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
    predicted_exposures:
      - event_id: event_missing_asset
        symbol: AAA
        node: fake_node
        asset_type: equity
        expected_direction: positive
        source: georisk
""",
        encoding="utf-8",
    )
    _write_v2_snapshot(
        snapshot_dir,
        "event_missing_asset",
        "2024-01-18",
        None,
        "AAA",
        expected_direction="positive",
    )
    _write_price_csv(
        price_dir / "SPY.csv",
        pd.bdate_range("2024-01-01", periods=30),
        [0.001] * 29,
        400.0,
    )

    run_car_validation(
        manifest_path=manifest,
        snapshot_dir=snapshot_dir,
        result_dir=result_dir,
        price_dir=price_dir,
        benchmark_symbol="SPY",
        config=MarketModelConfig(
            estimation_window_start=-10,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
    )

    skipped = json.loads((result_dir / "skipped_pairs.json").read_text())
    assert skipped[0]["event_id"] == "event_missing_asset"
    assert skipped[0]["symbol"] == "AAA"
    assert skipped[0]["expected_direction"] == "positive"
    assert skipped[0]["skip_reason"] == "missing_asset_prices"
    assert skipped[0]["expected_csv_path"].endswith("prices/AAA.csv")

    missing_files = json.loads((result_dir / "missing_price_files.json").read_text())
    assert missing_files["missing_asset_price_files"][0].endswith("prices/AAA.csv")
    assert missing_files["missing_benchmark_price_files"] == []
    assert missing_files["unique_missing_files"][0].endswith("prices/AAA.csv")


def test_run_car_validation_writes_missing_benchmark_price_diagnostics(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    snapshot_dir = tmp_path / "snapshots"
    result_dir = tmp_path / "results"
    price_dir = tmp_path / "prices"
    price_dir.mkdir()

    manifest.write_text(
        """
validation_events:
  - event_id: event_missing_benchmark
    event_date: "2024-01-18"
    event_description: "Fake accepted event."
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
    predicted_exposures:
      - event_id: event_missing_benchmark
        symbol: AAA
        node: fake_node
        asset_type: equity
        expected_direction: negative
        source: georisk
""",
        encoding="utf-8",
    )
    _write_v2_snapshot(
        snapshot_dir,
        "event_missing_benchmark",
        "2024-01-18",
        None,
        "AAA",
        expected_direction="negative",
    )
    _write_price_csv(
        price_dir / "AAA.csv",
        pd.bdate_range("2024-01-01", periods=30),
        [0.001] * 29,
        100.0,
    )

    run_car_validation(
        manifest_path=manifest,
        snapshot_dir=snapshot_dir,
        result_dir=result_dir,
        price_dir=price_dir,
        benchmark_symbol="SPY",
        config=MarketModelConfig(
            estimation_window_start=-10,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
    )

    skipped = json.loads((result_dir / "skipped_pairs.json").read_text())
    assert skipped[0]["event_id"] == "event_missing_benchmark"
    assert skipped[0]["symbol"] == "AAA"
    assert skipped[0]["benchmark"] == "SPY"
    assert skipped[0]["expected_direction"] == "negative"
    assert skipped[0]["skip_reason"] == "missing_benchmark_prices"
    assert skipped[0]["expected_benchmark_csv_path"].endswith("prices/SPY.csv")

    missing_files = json.loads((result_dir / "missing_price_files.json").read_text())
    assert missing_files["missing_asset_price_files"] == []
    assert missing_files["missing_benchmark_price_files"][0].endswith("prices/SPY.csv")
    assert missing_files["unique_missing_files"][0].endswith("prices/SPY.csv")


def test_build_missing_price_files_report_dedupes_files():
    report = build_missing_price_files_report(
        [
            {
                "missing_data_reason": "missing_asset_prices",
                "expected_csv_path": "data/prices/AAA.csv",
            },
            {
                "missing_data_reason": "missing_asset_prices",
                "expected_csv_path": "data/prices/AAA.csv",
            },
            {
                "missing_data_reason": "missing_benchmark_prices",
                "expected_benchmark_csv_path": "data/prices/SPY.csv",
            },
        ]
    )

    assert report == {
        "missing_asset_price_files": ["data/prices/AAA.csv"],
        "missing_benchmark_price_files": ["data/prices/SPY.csv"],
        "unique_missing_files": ["data/prices/AAA.csv", "data/prices/SPY.csv"],
    }

def _write_price_csv(path, dates, returns, start_price):
    price = start_price
    rows = [(dates[0].date().isoformat(), price)]
    for date, daily_return in zip(dates[1:], returns, strict=True):
        price *= 1 + daily_return
        rows.append((date.date().isoformat(), price))

    with path.open("w", encoding="utf-8") as handle:
        handle.write("Date,Adj Close\n")
        for date, close in rows:
            handle.write(f"{date},{close}\n")


def _write_v2_snapshot(
    snapshot_dir,
    event_id,
    event_date,
    event_type,
    symbol,
    expected_direction=None,
):
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / f"{event_id}_snapshot_v2.json").write_text(
        json.dumps(
            {
                "event_id": event_id,
                "event_date": event_date,
                "event_description": "Fake accepted event.",
                "event_type": event_type,
                "generated_at": "2024-01-01T00:00:00+00:00",
                "snapshot_version": "v2_full_pipeline",
                "pipeline_mode": "full_georisk_pipeline",
                "predicted_exposures": [
                    {
                        "event_id": event_id,
                        "symbol": symbol,
                        "node": "fake_node",
                        "asset_type": "equity",
                        "linkage_tier": "direct_exposure",
                        "linkage_rationale": "Fixture direct operating linkage.",
                        "transmission_order": "first_order",
                        "confidence": 0.7,
                        "evidence_label": "sector_proxy",
                        "supporting_case_ids": ["case_fixture"],
                        "evidence_reason": "Fixture support.",
                        "expected_direction": expected_direction,
                        "source": "georisk",
                    }
                ],
                "baseline_exposures": [],
                "note": "Frozen before observing post-event returns",
            }
        )
        + "\n",
        encoding="utf-8",
    )
