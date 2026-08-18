import pytest
import pandas as pd

from src.validation import curated_activation_test as activation


def test_unique_asset_mapping_rows_preserves_one_row_per_ticker():
    frame = pd.DataFrame(
        [
            {"ticker": "AAA", "supply_chain_node": "shipping", "asset_type": "Stock"},
            {"ticker": "AAA", "supply_chain_node": "energy", "asset_type": "Stock"},
            {"ticker": "BBB", "supply_chain_node": "customs", "asset_type": "Stock"},
        ]
    )

    rows = activation.unique_asset_mapping_rows(frame)

    assert [row["ticker"] for row in rows] == ["AAA", "BBB"]
    assert rows[0]["supply_chain_node"] == "shipping"


def test_activation_rows_require_xor_boundary():
    with pytest.raises(ValueError, match="exactly one"):
        activation.validate_activation_rows(
            [
                {
                    "activated": "true",
                    "non_activated": "true",
                }
            ]
        )


def test_event_level_activation_rows_uses_event_medians():
    rows = [
        {"event_id": "e1", "activated": "true", "non_activated": "false", "evaluable": "true", "absolute_scar": 1.0, "hit": "false"},
        {"event_id": "e1", "activated": "true", "non_activated": "false", "evaluable": "true", "absolute_scar": 3.0, "hit": "true"},
        {"event_id": "e1", "activated": "false", "non_activated": "true", "evaluable": "true", "absolute_scar": 0.5, "hit": "false"},
        {"event_id": "e1", "activated": "false", "non_activated": "true", "evaluable": "true", "absolute_scar": 1.5, "hit": "false"},
    ]

    result = activation.event_level_activation_rows(rows)

    assert result[0]["paired_activation_eligible"] == "true"
    assert result[0]["activated_event_median_abs_scar"] == 2.0
    assert result[0]["nonactivated_event_median_abs_scar"] == 1.0
    assert result[0]["delta_event"] == 1.0


def test_sign_flip_is_one_sided_and_seeded():
    result = activation.paired_sign_flip_test([1.0, -0.5, 0.25], seed=7, draws=20)

    assert result["seed"] == 7
    assert result["draws"] == 20
    assert 0 < result["empirical_one_sided_p_value"] <= 1


def test_classify_conclusion_partial_for_positive_majority_without_strong_p():
    result = activation.classify_conclusion(
        deltas=[0.1, 0.2, -0.1],
        activation_lift=0.05,
        sign_flip={"empirical_one_sided_p_value": 0.3},
    )

    assert result["answer"] == "PARTIALLY"
    assert result["selectivity_stage"] == "upstream event-specific node activation / mapping"


def test_binary_secondary_keeps_threshold_diagnostic():
    activated = [
        {"evaluable": "true", "hit": "true"},
        {"evaluable": "true", "hit": "false"},
    ]
    nonactivated = [
        {"evaluable": "true", "hit": "false"},
        {"evaluable": "true", "hit": "false"},
    ]

    result = activation.binary_secondary(activated, nonactivated, [])

    assert result["activated_hit_rate"] == 0.5
    assert result["nonactivated_hit_rate"] == 0.0
    assert result["delta_percentage_points"] == 50.0
