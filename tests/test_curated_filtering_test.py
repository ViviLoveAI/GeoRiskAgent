import pytest
import pandas as pd

from src.validation import curated_filtering_test as filtering


def test_candidate_snapshot_uses_event_specific_nodes_not_asset_mapping_complement():
    snapshots = [
        {
            "event_id": "e1",
            "transmission_chain": {"affected_nodes": ["shipping"]},
            "predicted_exposures": [{"symbol": "AAA", "evidence_label": "sector_proxy"}],
        }
    ]
    mapping = pd.DataFrame(
        [
            {"supply_chain_node": "shipping", "ticker": "AAA", "asset_type": "Stock"},
            {"supply_chain_node": "shipping", "ticker": "BBB", "asset_type": "Stock"},
            {"supply_chain_node": "energy", "ticker": "CCC", "asset_type": "Stock"},
        ]
    )

    rows = filtering.reconstruct_candidate_snapshot(snapshots, mapping)

    assert {row["ticker"] for row in rows} == {"AAA", "BBB"}
    assert "CCC" not in {row["ticker"] for row in rows}
    assert [row for row in rows if row["rejected_final"] == "true"][0]["ticker"] == "BBB"


def test_candidate_rows_require_selected_xor_rejected():
    with pytest.raises(ValueError, match="exactly one"):
        filtering.validate_candidate_rows(
            [
                {
                    "candidate": "true",
                    "selected_final": "true",
                    "rejected_final": "true",
                }
            ]
        )


def test_join_candidate_market_results_keeps_rejected_missing_when_no_scar():
    candidates = [
        {
            "event_id": "e1",
            "ticker": "AAA",
            "candidate_source_node": "shipping",
            "asset_type": "Stock",
            "candidate": "true",
            "selected_final": "true",
            "rejected_final": "false",
        },
        {
            "event_id": "e1",
            "ticker": "BBB",
            "candidate_source_node": "shipping",
            "asset_type": "Stock",
            "candidate": "true",
            "selected_final": "false",
            "rejected_final": "true",
        },
    ]
    car_rows = [{"event_id": "e1", "symbol": "AAA", "standardized_car": -2.0, "hit": True}]

    rows = filtering.join_candidate_market_results(candidates, car_rows)

    assert rows[0]["evaluable"] == "true"
    assert rows[0]["absolute_scar"] == 2.0
    assert rows[1]["evaluable"] == "false"
    assert rows[1]["missing_data_reason"] == "missing_existing_scar_result"


def test_event_level_rows_exclude_events_without_rejected_candidates():
    asset_rows = [
        {
            "event_id": "e1",
            "selected_final": "true",
            "rejected_final": "false",
            "evaluable": "true",
            "absolute_scar": 1.0,
        }
    ]

    rows = filtering.event_level_rows(asset_rows)

    assert rows[0]["paired_filtering_eligible"] == "false"
    assert rows[0]["exclusion_reason"] == "no_evaluable_rejected_candidates"


def test_sign_flip_uses_fixed_seed_and_plus_one_p_value():
    result = filtering.paired_sign_flip_test([1.0, 2.0], seed=1, draws=10)

    assert result["seed"] == 1
    assert result["draws"] == 10
    assert 0 < result["empirical_one_sided_p_value"] <= 1


def test_summary_records_no_when_frozen_path_has_no_rejected_candidates(tmp_path):
    candidates = [
        {
            "event_id": "e1",
            "ticker": "AAA",
            "candidate_source_node": "shipping",
            "asset_type": "Stock",
            "candidate": "true",
            "selected_final": "true",
            "rejected_final": "false",
        }
    ]
    candidate_path = tmp_path / "candidate_snapshot.csv"
    filtering.write_csv(candidate_path, candidates)
    assets = filtering.join_candidate_market_results(
        candidates,
        [{"event_id": "e1", "symbol": "AAA", "standardized_car": 1.5, "hit": False}],
    )
    event_rows = filtering.event_level_rows(assets)
    car_path = tmp_path / "car.csv"
    mapping_path = tmp_path / "asset_mapping.csv"
    car_path.write_text("x\n", encoding="utf-8")
    mapping_path.write_text("x\n", encoding="utf-8")

    summary = filtering.build_filtering_summary(
        candidates,
        assets,
        event_rows,
        random_seed=7,
        permutation_draws=100,
        car_results_path=car_path,
        asset_mapping_path=mapping_path,
        candidate_path=candidate_path,
    )

    assert summary["main_conclusion"]["answer"] == "NO"
    assert summary["continuous_primary"]["primary_metric_status"] == "not_evaluable_no_rejected_candidates"
    assert summary["integrity"]["prices_not_used_for_candidate_construction"] is True
