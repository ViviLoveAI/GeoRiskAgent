from scripts.replay_v3_car_provenance import (
    classify_difference,
    evidence_differences,
    exposure_key_set,
    jaccard,
)


def test_exposure_set_diff_and_evidence_change_detection():
    old = [
        {"symbol": "AAA", "node": "energy", "evidence_label": "sector_proxy", "transmission_order": "second_order"},
        {"symbol": "BBB", "node": "ports", "evidence_label": "historical_supported", "transmission_order": "first_order"},
    ]
    new = [
        {"symbol": "AAA", "node": "energy", "evidence_label": "historical_supported", "transmission_order": "second_order"},
        {"symbol": "CCC", "node": "defense", "evidence_label": "sector_proxy", "transmission_order": "second_order"},
    ]

    old_keys = exposure_key_set(old)
    new_keys = exposure_key_set(new)

    assert old_keys - new_keys == {("BBB", "ports")}
    assert new_keys - old_keys == {("CCC", "defense")}
    assert jaccard(old_keys, new_keys) == 1 / 3

    diffs = evidence_differences(old, new, sorted(old_keys & new_keys))
    assert diffs == [
        {
            "symbol": "AAA",
            "node": "energy",
            "old_evidence_label": "sector_proxy",
            "new_evidence_label": "historical_supported",
            "old_transmission_order": "second_order",
            "new_transmission_order": "second_order",
        }
    ]


def test_classification_allows_exact_match_only_without_evidence_drift():
    keys = {("AAA", "energy"), ("BBB", "ports")}

    assert classify_difference(keys, keys, [], []) == "CONSISTENT"
    assert (
        classify_difference(
            keys,
            keys,
            [{"symbol": "AAA", "node": "energy"}],
            [],
        )
        == "CONSISTENT_WITH_MINOR_DRIFT"
    )
    assert classify_difference(keys, {("AAA", "energy")}, [], [("BBB", "ports")]) == "MATERIAL_DIFFERENCE"
