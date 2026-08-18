from src.agents.asset_ranker import rank_assets
from src.agents.evidence_agent import grade_evidence
from src.agents.market_mapper import map_assets
from src.agents.transmission_builder import build_transmission_chain
from src.schemas import CandidateAsset, EventAnalysis, RetrievedCase, TransmissionChain
from src.transmission_context_store import project_current_event_context


def test_tariff_event_does_not_admit_oil_shipping_from_historical_analogs(monkeypatch):
    """Historical oil cases cannot qualify oil shipping without current linkage."""

    event = EventAnalysis(
        title="US-China Tariff Escalation",
        summary=(
            "The US raises tariffs on Chinese industrial goods and imported "
            "components, increasing input costs for manufacturers and prompting "
            "firms to reconsider sourcing from China and shift procurement "
            "toward Mexico and Southeast Asia."
        ),
        event_type="trade_policy_and_tariffs",
        supply_chain_nodes=["trade_lanes", "customs", "manufacturing_inputs"],
        shock_direction="trade_cost_risk",
    )
    cases = [_case("oil_case_1", ["oil_shipping"]), _case("oil_case_2", ["oil_shipping"])]
    monkeypatch.setattr(
        "src.agents.transmission_builder.load_historical_contexts",
        lambda: {
            ("oil_case_1", "oil_shipping"): _oil_shipping_context(),
            ("oil_case_2", "oil_shipping"): _oil_shipping_context(),
        },
    )

    chain = build_transmission_chain(
        event,
        cases,
        use_mechanism_compatible_support=True,
    )

    assert project_current_event_context(event, "oil_shipping") is None
    assert "oil_shipping" not in chain.affected_nodes
    assert "oil_shipping" not in chain.node_supporting_case_ids


def test_current_event_linkage_uses_token_boundaries():
    """Words such as imported and production must not trigger port context."""

    event = EventAnalysis(
        title="Tariff escalation",
        summary="Imported components raise production costs for manufacturers.",
        event_type="trade_policy_and_tariffs",
        supply_chain_nodes=["trade_lanes", "customs"],
        shock_direction="trade_cost_risk",
    )

    assert project_current_event_context(event, "ports") is None
    assert project_current_event_context(event, "logistics") is None


def test_maritime_event_can_still_admit_oil_shipping_when_semantics_match(monkeypatch):
    """The stricter gate preserves legitimate maritime second-order channels."""

    event = EventAnalysis(
        title="Red Sea vessel attacks",
        summary="Vessel attacks disrupt Red Sea shipping routes.",
        event_type="maritime_security_disruption",
        supply_chain_nodes=["maritime_chokepoint"],
        shock_direction="route_disruption_risk",
    )
    cases = [_case("maritime_case_1", ["oil_shipping"]), _case("maritime_case_2", ["oil_shipping"])]
    monkeypatch.setattr(
        "src.agents.transmission_builder.load_historical_contexts",
        lambda: {
            ("maritime_case_1", "oil_shipping"): _oil_shipping_context(),
            ("maritime_case_2", "oil_shipping"): _oil_shipping_context(),
        },
    )

    chain = build_transmission_chain(
        event,
        cases,
        use_mechanism_compatible_support=True,
    )

    assert "oil_shipping" in chain.affected_nodes
    assert chain.node_supporting_case_ids["oil_shipping"] == [
        "maritime_case_1",
        "maritime_case_2",
    ]


def test_energy_event_can_still_admit_oil_shipping_when_semantics_match(monkeypatch):
    """Energy shocks may still qualify oil-shipping transmission channels."""

    event = EventAnalysis(
        title="Oil supply disruption",
        summary="Oil supply disruption raises tanker shipping and refining risk.",
        event_type="energy_infrastructure_disruption",
        supply_chain_nodes=["energy"],
        shock_direction="energy_supply_disruption_risk",
    )
    cases = [_case("energy_case_1", ["oil_shipping"]), _case("energy_case_2", ["oil_shipping"])]
    monkeypatch.setattr(
        "src.agents.transmission_builder.load_historical_contexts",
        lambda: {
            ("energy_case_1", "oil_shipping"): _oil_shipping_context(),
            ("energy_case_2", "oil_shipping"): _oil_shipping_context(),
        },
    )

    chain = build_transmission_chain(
        event,
        cases,
        use_mechanism_compatible_support=True,
    )

    assert "oil_shipping" in chain.affected_nodes


def test_ranked_second_order_asset_support_metadata_matches_qualified_node(monkeypatch):
    """Ranked second-order assets expose the node support used to qualify them."""

    event = EventAnalysis(
        title="Red Sea vessel attacks",
        summary="Vessel attacks disrupt Red Sea shipping routes.",
        event_type="maritime_security_disruption",
        supply_chain_nodes=["maritime_chokepoint"],
        shock_direction="route_disruption_risk",
    )
    cases = [
        _case("maritime_case_1", ["oil_shipping"], relevance="distance=0.1"),
        _case("maritime_case_2", ["oil_shipping"], relevance="distance=0.2"),
    ]
    monkeypatch.setattr(
        "src.agents.transmission_builder.load_historical_contexts",
        lambda: {
            ("maritime_case_1", "oil_shipping"): _oil_shipping_context(),
            ("maritime_case_2", "oil_shipping"): _oil_shipping_context(),
        },
    )

    chain = build_transmission_chain(
        event,
        cases,
        use_mechanism_compatible_support=True,
    )
    ranked = rank_assets(
        grade_evidence(event, map_assets(event, chain), cases, chain),
        event,
        cases,
        chain,
    )
    oil_assets = [
        result for result in ranked
        if result.asset.supply_chain_node == "oil_shipping"
        and result.ranking_scope == "ranked_second_order"
    ]

    assert oil_assets
    for result in oil_assets:
        assert result.evidence_level == "sector_proxy"
        assert set(result.supporting_case_ids) == {"maritime_case_1", "maritime_case_2"}
        assert result.supporting_case_count == 2
        assert result.ranking_key["supporting_case_count"] == 2
        assert len(result.supporting_case_details) == 2


def test_historical_supported_asset_distinguishes_asset_evidence_from_node_qualification(monkeypatch):
    """A one-case direct asset match must not hide two-case node qualification."""

    event = EventAnalysis(
        title="Red Sea vessel attacks",
        summary="Vessel attacks disrupt Red Sea shipping routes.",
        event_type="maritime_security_disruption",
        supply_chain_nodes=["maritime_chokepoint"],
        shock_direction="route_disruption_risk",
    )
    cases = [
        _case("asset_match_case", ["oil_shipping"], relevance="distance=0.1"),
        _case("node_support_case", ["oil_shipping"], relevance="distance=0.2"),
    ]
    chain = TransmissionChain(
        affected_nodes=["maritime_chokepoint", "oil_shipping"],
        node_supporting_case_ids={
            "oil_shipping": ["asset_match_case", "node_support_case"],
        },
        node_evidence_levels={
            "maritime_chokepoint": "event_node",
            "oil_shipping": "case_grounded",
        },
        rationale="Chain",
    )
    asset = CandidateAsset(
        asset_id="DHT",
        name="DHT Holdings Inc",
        ticker="DHT",
        asset_name="DHT Holdings Inc",
        supply_chain_node="oil_shipping",
    )
    monkeypatch.setattr(
        "src.agents.evidence_agent._load_cases_by_id",
        lambda: {
            "asset_match_case": {
                "event_id": "asset_match_case",
                "event_name": "Oil tanker disruption",
                "affected_assets": ["DHT Holdings Inc"],
                "affected_asset_types": [],
                "supply_chain_nodes": ["oil_shipping"],
                "transmission_chain": [],
            },
            "node_support_case": {
                "event_id": "node_support_case",
                "event_name": "Oil shipping disruption",
                "affected_assets": [],
                "affected_asset_types": [],
                "supply_chain_nodes": ["oil_shipping"],
                "transmission_chain": [],
            },
        },
    )

    ranked = rank_assets(
        grade_evidence(event, [asset], cases, chain),
        event,
        cases,
        chain,
    )
    result = ranked[0]

    assert result.evidence_level == "historical_supported"
    assert result.supporting_case_ids == ["asset_match_case"]
    assert result.supporting_case_count == 1
    assert result.qualification_case_ids == ["asset_match_case", "node_support_case"]
    assert result.qualification_case_count == 2
    assert result.ranking_key["qualification_case_count"] == 2
    assert "Node qualified with 2 mechanism-compatible historical case(s)" in (
        result.ranking_rationale or ""
    )


def _case(case_id: str, nodes: list[str], relevance: str | None = None) -> RetrievedCase:
    return RetrievedCase(
        case_id=case_id,
        title=case_id.replace("_", " ").title(),
        summary="Historical analog.",
        event_type="historical",
        supply_chain_nodes=nodes,
        relevance=relevance,
    )


def _oil_shipping_context() -> dict[str, str]:
    return {
        "node": "oil_shipping",
        "shock_type": "military_escalation",
        "constraint_type": "route_disruption",
        "upstream_driver": "oil_shipping_compliance_or_security_risk",
        "target_node_role": "transmission_channel",
        "canonical_context": "oil_shipping_security_constraint",
    }
