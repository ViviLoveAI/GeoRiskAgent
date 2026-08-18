import json

import pandas as pd

from src.validation.car_calculator import MarketModelConfig
from src.validation.full_car_validation import (
    load_or_create_frozen_snapshots,
    run_full_car_validation,
)


def test_load_or_create_frozen_snapshots_does_not_regenerate_existing_snapshot(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    manifest.write_text(_manifest_text(event_date="2024-02-15"), encoding="utf-8")
    snapshot_path = snapshot_dir / "event_1_snapshot_v2.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "event_id": "event_1",
                "event_date": "2024-02-15",
                "event_description": "Old frozen event.",
                "event_type": "old_type",
                "generated_at": "2024-01-01T00:00:00+00:00",
                "snapshot_version": "v2_full_pipeline",
                "pipeline_mode": "full_georisk_pipeline",
                "predicted_exposures": [
                    {
                        "event_id": "event_1",
                        "symbol": "OLD",
                        "node": "old_node",
                        "asset_type": "equity",
                        "transmission_order": "first_order",
                        "confidence": 0.64,
                        "evidence_label": "sector_proxy",
                        "supporting_case_ids": ["case_old"],
                        "source": "georisk",
                    }
                ],
                "note": "existing",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    snapshots = load_or_create_frozen_snapshots(manifest, snapshot_dir)

    assert snapshots[0]["predicted_exposures"][0]["symbol"] == "OLD"
    saved = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert saved["generated_at"] == "2024-01-01T00:00:00+00:00"


def test_run_full_car_validation_smoke_test_without_network(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    snapshot_dir = tmp_path / "snapshots"
    price_dir = tmp_path / "prices"
    result_dir = tmp_path / "results"
    manifest.write_text(_manifest_text(event_date="2024-03-15"), encoding="utf-8")
    snapshot_dir.mkdir()
    (snapshot_dir / "event_1_snapshot_v2.json").write_text(
        json.dumps(
            {
                "event_id": "event_1",
                "event_date": "2024-03-15",
                "event_description": "Fake accepted event.",
                "event_type": "fake_type",
                "generated_at": "2024-01-01T00:00:00+00:00",
                "snapshot_version": "v2_full_pipeline",
                "pipeline_mode": "full_georisk_pipeline",
                "predicted_exposures": [
                    {
                        "event_id": "event_1",
                        "symbol": "AAA",
                        "node": "fake_node",
                        "asset_type": "equity",
                        "transmission_order": "first_order",
                        "confidence": 0.7,
                        "evidence_label": "historical_supported",
                        "supporting_case_ids": ["case_fixture"],
                        "source": "georisk",
                    }
                ],
                "baseline_exposures": [
                    {
                        "symbol": "BBB",
                        "node": "broad_market",
                        "asset_type": "equity_etf",
                        "baseline_type": "broad_market_baseline",
                        "source": "baseline",
                    }
                ],
                "note": "Frozen before observing post-event returns",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    price_dir.mkdir()

    dates = pd.bdate_range("2024-01-01", periods=80)
    benchmark_returns = [0.001 + ((index % 5) - 2) * 0.0002 for index in range(79)]
    asset_returns = [
        0.001 + 1.1 * value + ((index % 3) - 1) * 0.0003
        for index, value in enumerate(benchmark_returns)
    ]
    baseline_returns = [
        0.001 + 0.8 * value + ((index % 4) - 1) * 0.0002
        for index, value in enumerate(benchmark_returns)
    ]
    event_index = list(dates).index(pd.Timestamp("2024-03-15"))
    asset_returns[event_index - 1] = 0.025
    asset_returns[event_index] = 0.026
    asset_returns[event_index + 1] = 0.027
    _write_price_csv(price_dir / "AAA.csv", dates, asset_returns, 100.0)
    _write_price_csv(price_dir / "BBB.csv", dates, baseline_returns, 80.0)
    _write_price_csv(price_dir / "SPY.csv", dates, benchmark_returns, 400.0)

    result = run_full_car_validation(
        manifest_path=manifest,
        snapshot_dir=snapshot_dir,
        price_dir=price_dir,
        result_dir=result_dir,
        benchmark_symbol="SPY",
        config=MarketModelConfig(
            estimation_window_start=-10,
            estimation_window_end=-2,
            event_window_start=-1,
            event_window_end=1,
        ),
    )

    assert result["summary"]["events_evaluated"] == 1
    assert (result_dir / "car_pair_results.csv").exists()
    assert (result_dir / "car_summary.json").exists()
    assert (result_dir / "skipped_pairs.json").exists()
    assert (result_dir / "missing_price_files.json").exists()
    assert (result_dir / "car_validation_report.md").exists()
    assert (result_dir / "car_run_config.json").exists()
    assert (result_dir / "price_preparation_report.json").exists()

    pair_rows = pd.read_csv(result_dir / "car_pair_results.csv")
    assert set(pair_rows["source"]) == {"georisk", "baseline"}
    assert "CAR Validation Complete" in result["terminal_summary"]


def _manifest_text(event_date):
    return f"""
validation_events:
  - event_id: event_1
    event_date: "{event_date}"
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
        evidence_label: historical_supported
        source: georisk
    baseline_assets:
      - symbol: BBB
        node: broad_market
        asset_type: equity_etf
        baseline_type: broad_market_baseline
"""


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
