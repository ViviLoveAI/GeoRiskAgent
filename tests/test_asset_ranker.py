import json
from pathlib import Path

import pytest

from src.agents.asset_ranker import (
    RANKED_SCOPE,
    REFERENCE_SCOPE,
    RANKING_VERSION,
    UNMAPPED_SCOPE,
    VALID_PRIORITY_TIERS,
    rank_assets,
)
from src.schemas import CandidateAsset, EventAnalysis, EvidenceResult, RetrievedCase, TransmissionChain


def test_evidence_level_dominates_ranking_even_with_weaker_retrieval_support():
    event = _event(nodes=["oil_shipping"])
    cases = [_case("inf_case"), _case("sector_case"), _case("hist_case")]
    historical = _result(
        "HIST",
        "oil_shipping",
        evidence_level="historical_supported",
        confidence=0.82,
        supporting_case_ids=["hist_case"],
    )
    sector = _result(
        "SECTOR",
        "oil_shipping",
        evidence_level="sector_proxy",
        confidence=0.64,
        supporting_case_ids=["sector_case"],
    )
    inference = _result(
        "INFER",
        "oil_shipping",
        evidence_level="inference_only",
        confidence=0.35,
        supporting_case_ids=["inf_case"],
    )

    ranked = rank_assets(
        [inference, sector, historical],
        event,
        cases,
        TransmissionChain(rationale="Chain"),
    )

    assert _symbols(ranked) == ["HIST", "SECTOR", "INFER"]
    assert ranked[0].ranking_key["retrieval_support"] == pytest.approx(1 / 3)
    assert ranked[2].ranking_key["retrieval_support"] == 1.0


def test_supporting_case_count_breaks_evidence_ties():
    event = _event(nodes=["oil_shipping"])
    one = _result("ONE", "oil_shipping", supporting_case_ids=["case_1"])
    two = _result("TWO", "oil_shipping", supporting_case_ids=["case_1", "case_2"])
    three = _result(
        "THREE",
        "oil_shipping",
        supporting_case_ids=["case_1", "case_2", "case_3"],
    )

    ranked = rank_assets([one, three, two], event, [], TransmissionChain(rationale="Chain"))

    assert _symbols(ranked) == ["THREE", "TWO", "ONE"]
    assert [r.ranking_key["supporting_case_count_saturated"] for r in ranked] == [3, 2, 1]


def test_duplicate_supporting_case_ids_do_not_inflate_support_count():
    event = _event(nodes=["oil_shipping"])
    duplicated = _result(
        "AAA",
        "oil_shipping",
        supporting_case_ids=["case_1", "case_1", "case_2"],
    )
    unique = _result(
        "BBB",
        "oil_shipping",
        supporting_case_ids=["case_1", "case_2"],
    )

    ranked = rank_assets([unique, duplicated], event, [], TransmissionChain(rationale="Chain"))

    assert _symbols(ranked) == ["AAA", "BBB"]
    assert ranked[0].ranking_key["supporting_case_count"] == 2
    assert ranked[1].ranking_key["supporting_case_count"] == 2
    assert ranked[0].ranking_key["supporting_case_count_saturated"] == 2
    assert ranked[1].ranking_key["supporting_case_count_saturated"] == 2


def test_support_saturates_at_three_but_provenance_retains_actual_count():
    event = _event(nodes=["oil_shipping"])
    three = _result(
        "BBB",
        "oil_shipping",
        supporting_case_ids=["case_1", "case_2", "case_3"],
    )
    four = _result(
        "AAA",
        "oil_shipping",
        supporting_case_ids=["case_1", "case_2", "case_3", "case_4"],
    )

    ranked = rank_assets([three, four], event, [], TransmissionChain(rationale="Chain"))

    assert _symbols(ranked) == ["AAA", "BBB"]
    assert ranked[0].ranking_key["supporting_case_count"] == 4
    assert ranked[0].supporting_case_count == 4
    assert ranked[0].ranking_key["supporting_case_count_saturated"] == 3
    assert ranked[1].ranking_key["supporting_case_count_saturated"] == 3


def test_retrieval_support_breaks_support_count_ties_with_mean_reciprocal_rank():
    event = _event(nodes=["oil_shipping"])
    cases = [_case("case_1"), _case("case_2"), _case("case_3")]
    top_pair = _result("TOP", "oil_shipping", supporting_case_ids=["case_1", "case_2"])
    lower_pair = _result("LOW", "oil_shipping", supporting_case_ids=["case_2", "case_3"])

    ranked = rank_assets([lower_pair, top_pair], event, cases, TransmissionChain(rationale="Chain"))

    assert _symbols(ranked) == ["TOP", "LOW"]
    assert ranked[0].ranking_key["retrieval_support"] == pytest.approx(0.75)
    assert ranked[1].ranking_key["retrieval_support"] == pytest.approx(0.416667)


def test_symbol_is_deterministic_final_tiebreaker_across_input_orders():
    event = _event(nodes=["oil_shipping"])
    aaa = _result("AAA", "oil_shipping")
    bbb = _result("BBB", "oil_shipping")

    first = rank_assets([bbb, aaa], event, [_case("case_1")], TransmissionChain(rationale="Chain"))
    second = rank_assets([aaa, bbb], event, [_case("case_1")], TransmissionChain(rationale="Chain"))

    assert _symbols(first) == ["AAA", "BBB"]
    assert _symbols(second) == ["AAA", "BBB"]
    assert [r.rank_within_order for r in first] == [1, 2]


def test_first_order_exposures_are_reference_items_excluded_from_ranked_top_k():
    event = _event(nodes=["oil_shipping"])
    first_order = _result(
        "AAA",
        "oil_shipping",
        evidence_level="historical_supported",
        confidence=0.82,
        transmission_order="first_order",
        supporting_case_ids=["case_1", "case_2", "case_3"],
    )
    second_order = _result(
        "ZZZ",
        "oil_shipping",
        evidence_level="inference_only",
        confidence=0.35,
        transmission_order="second_order",
        supporting_case_ids=[],
    )

    ranked = rank_assets(
        [first_order, second_order],
        event,
        [_case("case_1"), _case("case_2"), _case("case_3")],
        TransmissionChain(rationale="Chain"),
    )

    assert _symbols(ranked) == ["ZZZ", "AAA"]
    assert ranked[0].ranking_scope == RANKED_SCOPE
    assert ranked[0].priority_tier == "exploratory"
    assert ranked[0].rank_within_order == 1
    assert ranked[1].ranking_scope == REFERENCE_SCOPE
    assert ranked[1].priority_tier == "reference"
    assert ranked[1].ranking_key is None


def test_unmapped_exposures_are_preserved_but_not_first_or_second_order():
    event = _event(nodes=["oil_shipping"])
    first_order = _result(
        "FIRST",
        "oil_shipping",
        transmission_order="first_order",
    )
    second_order = _result(
        "SECOND",
        "oil_shipping",
        transmission_order="second_order",
    )
    unmapped = _result(
        "UNMAPPED",
        "unknown_node",
        transmission_order="unmapped",
    )

    ranked = rank_assets(
        [unmapped, first_order, second_order],
        event,
        [_case("case_1")],
        TransmissionChain(rationale="Chain"),
    )

    assert len(ranked) == 3
    by_symbol = {result.ticker: result for result in ranked}
    assert by_symbol["SECOND"].ranking_scope == RANKED_SCOPE
    assert by_symbol["FIRST"].ranking_scope == REFERENCE_SCOPE
    assert by_symbol["UNMAPPED"].ranking_scope == UNMAPPED_SCOPE
    assert by_symbol["UNMAPPED"].priority_tier == "unmapped"
    assert by_symbol["UNMAPPED"].ranking_key is None
    assert "Direct-exposure reference" not in (
        by_symbol["UNMAPPED"].ranking_rationale or ""
    )
    assert "excluded from the first-order direct-exposure control group" in (
        by_symbol["UNMAPPED"].ranking_rationale or ""
    )


def test_unknown_transmission_order_does_not_contaminate_first_order_reference():
    event = _event(nodes=["oil_shipping"])
    unknown = _result(
        "UNKNOWN",
        "oil_shipping",
        evidence_level="historical_supported",
        confidence=0.82,
        transmission_order="unknown",
    )
    first_order = _result(
        "FIRST",
        "oil_shipping",
        transmission_order="first_order",
    )

    ranked = rank_assets(
        [unknown, first_order],
        event,
        [_case("case_1")],
        TransmissionChain(rationale="Chain"),
    )

    by_symbol = {result.ticker: result for result in ranked}
    assert by_symbol["FIRST"].ranking_scope == REFERENCE_SCOPE
    assert by_symbol["UNKNOWN"].ranking_scope == UNMAPPED_SCOPE
    assert by_symbol["UNKNOWN"].rank_within_order == 1
    assert by_symbol["UNKNOWN"].priority_tier == "unmapped"
    assert "Direct-exposure reference" not in (
        by_symbol["UNKNOWN"].ranking_rationale or ""
    )


def test_ranker_never_removes_candidates():
    event = _event(nodes=["oil_shipping"])
    inputs = [
        _result("SECOND_A", "oil_shipping", transmission_order="second_order"),
        _result("FIRST_A", "oil_shipping", transmission_order="first_order"),
        _result("SECOND_B", "oil_shipping", transmission_order="second_order"),
    ]

    ranked = rank_assets(inputs, event, [_case("case_1")], TransmissionChain(rationale="Chain"))

    assert len(ranked) == len(inputs)
    assert {r.ticker for r in ranked} == {r.ticker for r in inputs}


def test_ranker_preserves_semantic_fields():
    event = _event(nodes=["oil_shipping"])
    inputs = [
        _result(
            "AAA",
            "oil_shipping",
            evidence_level="sector_proxy",
            confidence=0.64,
            transmission_order="second_order",
            linkage_tier="related_exposure",
            supporting_case_ids=["case_1", "case_1", "case_2"],
        ),
        _result(
            "BBB",
            "oil_shipping",
            evidence_level="historical_supported",
            confidence=0.82,
            transmission_order="first_order",
            linkage_tier="broad_proxy",
            supporting_case_ids=["case_3"],
        ),
    ]
    before = {
        r.ticker: {
            "asset_id": r.asset.asset_id,
            "asset_name": r.asset_name,
            "evidence_level": r.evidence_level,
            "confidence": r.confidence,
            "linkage_tier": r.linkage_tier,
            "transmission_order": r.transmission_order,
            "supporting_case_ids": list(r.supporting_case_ids),
        }
        for r in inputs
    }

    ranked = rank_assets(
        inputs,
        event,
        [_case("case_1"), _case("case_2"), _case("case_3")],
        TransmissionChain(rationale="Chain"),
    )

    for result in ranked:
        assert before[result.ticker] == {
            "asset_id": result.asset.asset_id,
            "asset_name": result.asset_name,
            "evidence_level": result.evidence_level,
            "confidence": result.confidence,
            "linkage_tier": result.linkage_tier,
            "transmission_order": result.transmission_order,
            "supporting_case_ids": list(result.supporting_case_ids),
        }


def test_linkage_tier_does_not_affect_rank():
    event = _event(nodes=["oil_shipping"])
    direct = _result("ZZZ", "oil_shipping", linkage_tier="direct_exposure")
    broad = _result("AAA", "oil_shipping", linkage_tier="broad_proxy")

    ranked = rank_assets([direct, broad], event, [_case("case_1")], TransmissionChain(rationale="Chain"))

    assert _symbols(ranked) == ["AAA", "ZZZ"]
    assert "linkage_tier" not in ranked[0].ranking_key
    assert "linkage_tier" not in ranked[1].ranking_key


def test_missing_retrieved_case_support_is_safe_and_scores_zero():
    event = _event(nodes=["oil_shipping"])
    missing = _result("AAA", "oil_shipping", supporting_case_ids=["unknown_case"])
    none = _result("BBB", "oil_shipping", supporting_case_ids=[])

    ranked = rank_assets([missing, none], event, [], TransmissionChain(rationale="Chain"))

    assert ranked[0].ranking_key["retrieval_support"] == 0.0
    assert ranked[0].supporting_case_details == []
    assert ranked[1].ranking_key["retrieval_support"] == 0.0


def test_empty_input_returns_empty_list():
    assert rank_assets([], _event(nodes=[]), [], TransmissionChain(rationale="Chain")) == []


def test_ranked_second_order_metadata_is_complete_and_sequential():
    event = _event(nodes=["oil_shipping"])
    results = [
        _result("CCC", "oil_shipping"),
        _result("AAA", "oil_shipping"),
        _result("BBB", "oil_shipping"),
    ]

    ranked = rank_assets(results, event, [_case("case_1")], TransmissionChain(rationale="Chain"))

    assert [r.rank_within_order for r in ranked] == [1, 2, 3]
    for result in ranked:
        assert result.ranking_version == RANKING_VERSION
        assert result.ranking_scope == RANKED_SCOPE
        assert result.priority_tier in VALID_PRIORITY_TIERS - {"reference"}
        assert result.ranking_key is not None
        assert result.supporting_case_count == result.ranking_key["supporting_case_count"]
        assert result.supporting_case_details[0]["case_id"] == "case_1"
        assert "Second-order rank" in (result.ranking_rationale or "")
        assert "not a probability of price movement" in (result.ranking_rationale or "")


def test_supporting_case_details_are_ordered_by_retrieval_rank():
    event = _event(nodes=["oil_shipping"])
    cases = [_case("case_1"), _case("case_2"), _case("case_3")]
    result = _result(
        "AAA",
        "oil_shipping",
        supporting_case_ids=["case_3", "case_1", "case_2"],
    )

    ranked = rank_assets([result], event, cases, TransmissionChain(rationale="Chain"))

    assert [d["case_id"] for d in ranked[0].supporting_case_details] == [
        "case_1",
        "case_2",
        "case_3",
    ]
    assert [d["retrieval_rank"] for d in ranked[0].supporting_case_details] == [1, 2, 3]


def test_relevance_metadata_is_preserved_but_rank_position_drives_retrieval_support():
    event = _event(nodes=["oil_shipping"])
    cases = [
        _case("distance_case", relevance="distance=999.0"),
        _case("semantic_case", relevance="semantic_distance=0.2500"),
        _case("similarity_case", relevance="similarity=0.9900"),
        _case("none_case", relevance=None),
        _case("malformed_case", relevance="not_a_score"),
    ]
    distance_asset = _result("AAA", "oil_shipping", supporting_case_ids=["distance_case"])
    similarity_asset = _result("BBB", "oil_shipping", supporting_case_ids=["similarity_case"])

    ranked = rank_assets(
        [similarity_asset, distance_asset],
        event,
        cases,
        TransmissionChain(rationale="Chain"),
    )

    assert _symbols(ranked) == ["AAA", "BBB"]
    assert ranked[0].ranking_key["retrieval_support"] == 1.0
    assert ranked[1].ranking_key["retrieval_support"] == pytest.approx(1 / 3)

    details = {
        detail["case_id"]: detail
        for result in ranked
        for detail in result.supporting_case_details
    }
    assert details["distance_case"]["retrieval_distance"] == 999.0
    assert details["similarity_case"]["retrieval_similarity"] == 0.99

    all_metadata = rank_assets(
        [
            _result("CCC", "oil_shipping", supporting_case_ids=["semantic_case"]),
            _result("DDD", "oil_shipping", supporting_case_ids=["none_case"]),
            _result("EEE", "oil_shipping", supporting_case_ids=["malformed_case"]),
        ],
        event,
        cases,
        TransmissionChain(rationale="Chain"),
    )
    by_symbol = {r.ticker: r for r in all_metadata}
    assert by_symbol["CCC"].supporting_case_details[0]["retrieval_distance"] == 0.25
    assert "retrieval_distance" not in by_symbol["DDD"].supporting_case_details[0]
    assert "retrieval_similarity" not in by_symbol["EEE"].supporting_case_details[0]


def test_ranking_ignores_outcome_like_extra_attributes():
    event = _event(nodes=["oil_shipping"])
    low_outcome = _result("AAA", "oil_shipping")
    high_outcome = _result("BBB", "oil_shipping")
    # Pydantic models are intentionally immutable in spirit here; attach
    # arbitrary outcome-like attributes to prove the ranker does not consult
    # CAR, returns, hit labels, or price direction even if they exist nearby.
    object.__setattr__(low_outcome, "car", -10.0)
    object.__setattr__(low_outcome, "standardized_car", -5.0)
    object.__setattr__(low_outcome, "hit", True)
    object.__setattr__(high_outcome, "car", 10.0)
    object.__setattr__(high_outcome, "standardized_car", 5.0)
    object.__setattr__(high_outcome, "hit", False)

    ranked = rank_assets(
        [high_outcome, low_outcome],
        event,
        [_case("case_1")],
        TransmissionChain(rationale="Chain"),
    )

    assert _symbols(ranked) == ["AAA", "BBB"]
    for result in ranked:
        assert "car" not in result.ranking_key
        assert "standardized_car" not in result.ranking_key
        assert "hit" not in result.ranking_key


def test_v3_manifest_identifier_is_unchanged():
    manifest_path = Path("data/validation_v3/v3_manifest.json")
    if not manifest_path.exists():
        return

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload.get("manifest_hash") == (
        "d67ae3db74eb150acf94d41985f28a04f4bd97a5837597a3800384110ebf2010"
    )
    assert len(payload.get("event_ids", [])) == 12


def _symbols(results):
    return [result.ticker for result in results]


def _event(nodes):
    return EventAnalysis(
        title="Event",
        summary="Summary",
        event_type="test",
        regions=["Global"],
        supply_chain_nodes=nodes,
        shock_direction="risk_watchlist_candidate",
    )


def _case(case_id, relevance="semantic_distance=0.1000"):
    return RetrievedCase(
        case_id=case_id,
        title=case_id,
        summary="Case summary",
        relevance=relevance,
    )


def _result(
    symbol,
    node,
    evidence_level="sector_proxy",
    confidence=0.64,
    transmission_order="second_order",
    linkage_tier="direct_exposure",
    supporting_case_ids=None,
):
    supporting_case_ids = supporting_case_ids if supporting_case_ids is not None else ["case_1"]
    asset = CandidateAsset(
        asset_id=symbol,
        name=symbol,
        ticker=symbol,
        asset_name=symbol,
        asset_type="Stock",
        supply_chain_node=node,
        linkage_tier=linkage_tier,
        linkage_rationale=f"{linkage_tier} rationale",
    )
    return EvidenceResult(
        asset=asset,
        evidence_grade=evidence_level,
        rationale=f"{evidence_level} rationale",
        supporting_case_ids=supporting_case_ids,
        ticker=symbol,
        asset_name=symbol,
        evidence_level=evidence_level,
        confidence=confidence,
        reason=f"{evidence_level} reason",
        transmission_order=transmission_order,
        linkage_tier=asset.linkage_tier,
        linkage_rationale=asset.linkage_rationale,
    )
