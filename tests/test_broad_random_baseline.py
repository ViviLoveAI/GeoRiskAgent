import pytest

from src.validation import broad_random_baseline as broad


def test_eligible_symbols_by_event_parses_semicolon_lists():
    rows = [
        {"ticker": "AAA", "eligible_event_ids": "e1;e2"},
        {"ticker": "BBB", "eligible_event_ids": "e2"},
        {"ticker": "CCC", "eligible_event_ids": ""},
    ]

    result = broad.eligible_symbols_by_event(rows)

    assert result == {"e1": ["AAA"], "e2": ["AAA", "BBB"]}


def test_validate_event_eligibility_fails_instead_of_lowering_sample_size():
    with pytest.raises(RuntimeError, match="Insufficient broad universe"):
        broad.validate_event_eligibility({"e1": ["AAA"]}, {"e1": 2}, max_required_n=2)


def test_empirical_p_value_uses_plus_one_definition():
    assert broad.empirical_one_sided_p_value([0.1, 0.2, 0.3], 0.2) == pytest.approx(3 / 4)


def test_classify_conclusion_partial_for_broad_curated_georisk_ladder():
    result = broad.classify_conclusion(
        georisk_aggregate=0.8,
        curated_cont={"curated_random_aggregate": {"median": 0.7}},
        full_stats={"aggregate_event_median_abs_scar": {"median": 0.6}},
        ex_stats={"aggregate_event_median_abs_scar": {"median": 0.55}},
    )

    assert result["answer"] == "PARTIALLY"


def test_symbols_by_event_groups_georisk_exclusions():
    rows = [
        {"event_id": "e1", "symbol": "AAA"},
        {"event_id": "e1", "symbol": "bbb"},
        {"event_id": "e2", "symbol": "CCC"},
    ]

    result = broad.symbols_by_event(rows)

    assert result["e1"] == {"AAA", "BBB"}
    assert result["e2"] == {"CCC"}
