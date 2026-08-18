import csv
import json

from src.validation import baseline_universe_test as universe_test


def write_csv(path, rows):
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_broad_universe_rejected_when_price_universe_is_curated_contaminated():
    georisk_rows = [
        {"event_id": "e1"},
        {"event_id": "e1"},
        {"event_id": "e2"},
    ]
    audit = universe_test.broad_universe_audit(
        curated_universe=["AAA", "BBB", "CCC"],
        price_universe=["AAA", "BBB", "CCC", "QQQ"],
        georisk_rows=georisk_rows,
        benchmark_symbol="SPY",
    )

    assert audit["broad_random_runnable"] is False
    assert "only_1_non_curated_symbols" in audit["blocking_reason"]
    assert "overlaps_asset_mapping" in audit["blocking_reason"]


def test_curated_pool_results_renames_existing_random_matched_summary():
    random_summary = {
        "scopes": {
            "all": {
                "hit_rate": {"mean": 0.1, "median": 0.11, "p05": 0.04, "p95": 0.2},
                "actual_georisk_percentile_rank_hit_rate": 0.87,
            }
        }
    }
    random_config = {"runs": 1000, "random_seed": 20260805}
    georisk_metrics = {"hit_rate": 0.12}

    result = universe_test.curated_pool_results(random_summary, random_config, georisk_metrics)

    assert result["summary"]["baseline_name"] == "Curated-Pool Random Baseline"
    assert result["summary"]["sampling_universe"] == "asset_mapping.csv"
    assert result["summary"]["mean_hit_rate"] == 0.1


def test_run_diagnostic_does_not_require_prices_or_modify_car_method(tmp_path):
    asset_mapping = tmp_path / "asset_mapping.csv"
    write_csv(
        asset_mapping,
        [
            {"ticker": "AAA", "supply_chain_node": "node_a", "asset_type": "Stock"},
            {"ticker": "BBB", "supply_chain_node": "node_b", "asset_type": "Stock"},
        ],
    )
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    for symbol in ["AAA", "BBB", "QQQ", "SPY"]:
        (price_dir / f"{symbol}.csv").write_text("Date,Adj Close\n2024-01-01,1\n", encoding="utf-8")

    car_dir = tmp_path / "car"
    car_dir.mkdir()
    write_csv(
        car_dir / "car_pair_results.csv",
        [
            {
                "event_id": "e1",
                "source": "georisk",
                "hit": "True",
                "standardized_car": "2.1",
                "car": "0.01",
                "missing_data_reason": "",
            },
            {
                "event_id": "e1",
                "source": "georisk",
                "hit": "False",
                "standardized_car": "0.5",
                "car": "0.02",
                "missing_data_reason": "",
            },
        ],
    )
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    (curated_dir / "random_matched_summary.json").write_text(
        json.dumps(
            {
                "scopes": {
                    "all": {
                        "hit_rate": {"mean": 0.25, "median": 0.25, "p05": 0.0, "p95": 0.5},
                        "actual_georisk_percentile_rank_hit_rate": 0.9,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (curated_dir / "random_matched_config.json").write_text(
        json.dumps({"runs": 1000, "random_seed": 7}),
        encoding="utf-8",
    )
    (curated_dir / "random_matched_runs.csv").write_text("run_id\n0\n", encoding="utf-8")
    write_csv(
        curated_dir / "random_matched_event_summary.csv",
        [
            {
                "event_id": "e1",
                "random_baseline_mean_hit_rate": "0.25",
            }
        ],
    )

    summary = universe_test.run_baseline_universe_contamination_test(
        output_dir=tmp_path / "out",
        asset_mapping_path=asset_mapping,
        price_dir=price_dir,
        car_result_dir=car_dir,
        curated_baseline_dir=curated_dir,
    )

    assert summary["integrity"]["CAR_SCAR_implementation_unchanged"] is True
    assert summary["integrity"]["prices_downloaded"] is False
    assert summary["curated_random"]["baseline_name"] == "Curated-Pool Random Baseline"
    assert summary["broad_random"]["status"] == "not_run"
