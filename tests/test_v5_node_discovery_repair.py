import csv

from src.agents.node_discovery_repair import propose_node_repairs
from src.pipeline import run_v4_pipeline
from src.schemas import EventAnalysis, RetrievedCase
from src.v5_config import V5DiscoveryConfig
from src.v5_models import NodeRepairProposal
from src.v5_pipeline import _specificity_recovery_proposal, run_v5_pipeline


NEWS = "Red Sea shipping sanctions increase marine insurance costs for oil tankers."


def test_v5_repair_disabled_matches_v4_output():
    v4 = run_v4_pipeline(NEWS, event_analyzer="rule")
    v5 = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(enable_node_repair=False),
    )

    assert v5.final_report == v4
    assert v5.repair_enabled is False
    assert v5.state.repair_attempts == 0


def test_node_repair_triggers_from_missing_sidecar_node(monkeypatch):
    _patch_fixture_pipeline(monkeypatch, _fixture_contexts(["case_a", "case_b"]))

    result = run_v5_pipeline(NEWS, event_analyzer="rule")

    assert result.state.diagnosis == "NODE_GAP"
    assert result.state.repair_attempts == 1
    assert result.state.repair_proposals[0].proposed_node == "marine_insurance"
    assert result.state.repair_proposals[0].source_case_ids == ["case_a", "case_b"]
    assert "marine_insurance" in result.final_report.transmission_chain.affected_nodes
    assert any(
        action.action == "EXPAND_NODES"
        and action.candidate_nodes_added == ["marine_insurance"]
        for action in result.state.trajectory
    )


def test_repaired_candidate_still_fails_frozen_gate_with_weak_support(monkeypatch):
    _patch_fixture_pipeline(monkeypatch, _fixture_contexts(["case_a"]))

    result = run_v5_pipeline(NEWS, event_analyzer="rule")

    assert result.state.diagnosis == "NODE_GAP"
    assert result.state.repair_attempts == 1
    assert result.state.repair_proposals[0].proposed_node == "marine_insurance"
    assert result.state.repair_proposals[0].source_case_ids == ["case_a"]
    assert "marine_insurance" not in result.final_report.transmission_chain.affected_nodes
    assert result.state.unresolved_nodes == ["marine_insurance"]


def test_repaired_node_gets_current_context_projection(monkeypatch):
    contexts = {
        ("case_a", "maritime_chokepoint"): _maritime_chokepoint_context("case_a"),
        ("case_b", "maritime_chokepoint"): _maritime_chokepoint_context("case_b"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Hormuz tanker tensions A",
                summary="Historical Hormuz route security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            ),
            RetrievedCase(
                case_id="case_b",
                title="Hormuz tanker tensions B",
                summary="Historical maritime chokepoint security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            ),
        ],
    )

    result = run_v5_pipeline(NEWS, event_analyzer="rule")
    proposal = result.state.repair_proposals[0]

    assert proposal.proposed_node == "maritime_chokepoint"
    assert proposal.projection_attempted is True
    assert proposal.projection_status == "projected"
    assert proposal.projected_current_context is not None


def test_existing_v4_context_is_not_overwritten_for_repaired_node(monkeypatch):
    _patch_fixture_pipeline(monkeypatch, _fixture_contexts(["case_a", "case_b"]))

    result = run_v5_pipeline(NEWS, event_analyzer="rule")
    proposal = result.state.repair_proposals[0]

    assert proposal.proposed_node == "marine_insurance"
    assert proposal.projection_status == "existing_v4_context"
    assert proposal.projection_source == "v4_project_current_event_context"


def test_projection_success_does_not_force_acceptance(monkeypatch):
    contexts = {
        ("case_a", "maritime_chokepoint"): _maritime_chokepoint_context("case_a"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Hormuz tanker tensions A",
                summary="Historical Hormuz route security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            )
        ],
    )

    result = run_v5_pipeline(NEWS, event_analyzer="rule")
    proposal = result.state.repair_proposals[0]

    assert proposal.projection_status == "projected"
    assert proposal.compatible_support_count == 1
    assert "maritime_chokepoint" not in result.final_report.transmission_chain.affected_nodes
    assert result.state.unresolved_nodes == ["maritime_chokepoint"]


def test_projection_failure_stays_conservative(monkeypatch):
    contexts = {
        ("case_a", "defense"): _defense_context("case_a"),
        ("case_b", "defense"): _defense_context("case_b"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Defense context A",
                summary="Historical defense context.",
                event_type="defense",
                supply_chain_nodes=["defense"],
            ),
            RetrievedCase(
                case_id="case_b",
                title="Defense context B",
                summary="Historical defense context.",
                event_type="defense",
                supply_chain_nodes=["defense"],
            ),
        ],
    )

    result = run_v5_pipeline(NEWS, event_analyzer="rule")
    proposal = result.state.repair_proposals[0]

    assert proposal.proposed_node == "defense"
    assert proposal.projection_status == "projection_unavailable"
    assert proposal.compatible_support_count == 0
    assert "defense" not in result.final_report.transmission_chain.affected_nodes


def test_historical_present_current_missing_becomes_repair_candidate(monkeypatch):
    contexts = {("case_a", "marine_insurance"): _maritime_context("marine_insurance")}
    monkeypatch.setattr(
        "src.agents.node_discovery_repair.load_historical_contexts",
        lambda: contexts,
    )
    retrieved = [
        RetrievedCase(
            case_id="case_a",
            title="Historical tanker insurance disruption A",
            summary="Oil tanker route disruptions raised insurance constraints.",
            event_type="maritime_security_disruption",
            supply_chain_nodes=["maritime_chokepoint", "marine_insurance"],
        )
    ]

    proposals = propose_node_repairs(
        _event(),
        retrieved,
        current_proposed_nodes=["maritime_chokepoint"],
        max_candidates=5,
    )

    assert [proposal.proposed_node for proposal in proposals] == ["marine_insurance"]
    assert proposals[0].historical_support_count == 1


def test_historical_present_current_present_does_not_duplicate_repair(monkeypatch):
    contexts = {("case_a", "marine_insurance"): _maritime_context("marine_insurance")}
    monkeypatch.setattr(
        "src.agents.node_discovery_repair.load_historical_contexts",
        lambda: contexts,
    )
    retrieved = [
        RetrievedCase(
            case_id="case_a",
            title="Historical tanker insurance disruption A",
            summary="Oil tanker route disruptions raised insurance constraints.",
            event_type="maritime_security_disruption",
            supply_chain_nodes=["marine_insurance"],
        )
    ]

    proposals = propose_node_repairs(
        _event(),
        retrieved,
        current_proposed_nodes=["maritime_chokepoint", "marine_insurance"],
        max_candidates=5,
    )

    assert proposals == []


def test_repair_budget_limits_attempts_and_candidates(monkeypatch):
    contexts = {}
    for node in (
        [
            "marine_insurance",
            "oil_shipping",
            "lng_shipping",
            "container_shipping",
            "logistics",
            "freight_routes",
        ]
    ):
        contexts[("case_a", node)] = _maritime_context(node)
    _patch_fixture_pipeline(monkeypatch, contexts)

    result = run_v5_pipeline(NEWS, event_analyzer="rule")

    assert result.state.repair_attempts <= 1
    assert len(result.state.repair_proposals) <= 5
    expand_actions = [
        action for action in result.state.trajectory if action.action == "EXPAND_NODES"
    ]
    assert len(expand_actions) <= 1
    assert len(expand_actions[0].candidate_nodes_added) <= 5


def test_node_repair_cannot_introduce_arbitrary_tickers(monkeypatch):
    contexts = _fixture_contexts(["case_a", "case_b"])
    contexts[("case_a", "FAKE")] = _maritime_context("FAKE")
    _patch_fixture_pipeline(monkeypatch, contexts)

    result = run_v5_pipeline(NEWS, event_analyzer="rule")

    proposed_nodes = {proposal.proposed_node for proposal in result.state.repair_proposals}
    tickers = {evidence.ticker for evidence in result.final_report.evidence_results}

    assert "FAKE" not in proposed_nodes
    assert "XYZ" not in tickers
    assert all(proposal.proposed_node.islower() for proposal in result.state.repair_proposals)


def test_hormuz_temporal_gap_is_not_treated_as_already_proposed():
    result = run_v5_pipeline(
        _heldout_description("v4cand_20260319_imo_hormuz_safe_passage"),
        event_analyzer="rule",
    )

    proposed = {proposal.proposed_node for proposal in result.state.repair_proposals}

    assert "maritime_chokepoint" in result.state.historical_evidence_nodes
    assert "maritime_chokepoint" not in result.state.current_proposed_nodes
    assert result.state.diagnosis == "NODE_GAP"
    assert "maritime_chokepoint" in proposed
    proposal = next(
        proposal
        for proposal in result.state.repair_proposals
        if proposal.proposed_node == "maritime_chokepoint"
    )
    assert proposal.projection_attempted is True
    assert proposal.projection_status == "projected"


def test_gru_dns_temporal_gap_is_not_treated_as_already_proposed():
    result = run_v5_pipeline(
        _heldout_description("v4cand_20260407_us_gru_dns_hijacking_disruption"),
        event_analyzer="rule",
    )

    proposed = {proposal.proposed_node for proposal in result.state.repair_proposals}

    assert "cyber_infrastructure" in result.state.historical_evidence_nodes
    assert "cyber_infrastructure" not in result.state.current_proposed_nodes
    assert result.state.diagnosis == "NODE_GAP"
    assert "cyber_infrastructure" in proposed
    proposal = next(
        proposal
        for proposal in result.state.repair_proposals
        if proposal.proposed_node == "cyber_infrastructure"
    )
    assert proposal.projection_attempted is True
    assert proposal.projection_status == "projected"


def test_specificity_recovery_disabled_preserves_v5_0_2_broad_lock(monkeypatch):
    _patch_default_broad_specific_fixture(monkeypatch)

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(enable_specificity_recovery=False),
    )
    proposal = result.state.repair_proposals[0]

    assert proposal.proposed_node == "maritime_chokepoint"
    assert proposal.compatible_support_count == 2
    assert proposal.specificity_recovery_evaluated is False
    assert "maritime_chokepoint" not in result.final_report.transmission_chain.affected_nodes


def test_eligible_specific_repaired_candidate_recovers_from_default_broad_lock(monkeypatch):
    _patch_default_broad_specific_fixture(monkeypatch)

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(enable_specificity_recovery=True),
    )
    proposal = result.state.repair_proposals[0]

    assert proposal.proposed_node == "maritime_chokepoint"
    assert proposal.specificity_recovery_evaluated is True
    assert proposal.specificity_recovery_eligible is True
    assert proposal.event_guardrail_bypassed_for_candidate is True
    assert "maritime_chokepoint" in result.final_report.transmission_chain.affected_nodes
    assert (
        result.final_report.transmission_chain.node_evidence_levels["maritime_chokepoint"]
        == "case_grounded"
    )


def test_broad_candidate_is_not_specificity_recovery_eligible():
    proposal = NodeRepairProposal(
        proposed_node="broad_etf",
        reason="unit test",
        projected_current_context=_maritime_chokepoint_context("current"),
    )

    updated = _specificity_recovery_proposal(
        _hormuz_event(),
        proposal,
        ["case_a", "case_b"],
    )

    assert updated.specificity_recovery_evaluated is True
    assert updated.specificity_recovery_eligible is False
    assert updated.candidate_specificity == "broad"


def test_specificity_recovery_requires_projection(monkeypatch):
    contexts = {
        ("case_a", "defense"): _defense_context("case_a"),
        ("case_b", "defense"): _defense_context("case_b"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Defense context A",
                summary="Historical defense context.",
                event_type="defense",
                supply_chain_nodes=["defense"],
            ),
            RetrievedCase(
                case_id="case_b",
                title="Defense context B",
                summary="Historical defense context.",
                event_type="defense",
                supply_chain_nodes=["defense"],
            ),
        ],
    )

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(enable_specificity_recovery=True),
    )
    proposal = result.state.repair_proposals[0]

    assert proposal.projection_status == "projection_unavailable"
    assert proposal.specificity_recovery_eligible is False
    assert "defense" not in result.final_report.transmission_chain.affected_nodes


def test_specificity_recovery_requires_support_threshold(monkeypatch):
    contexts = {
        ("case_a", "maritime_chokepoint"): _maritime_chokepoint_context("case_a"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Hormuz tanker tensions A",
                summary="Historical Hormuz route security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            ),
        ],
    )

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(enable_specificity_recovery=True),
    )
    proposal = result.state.repair_proposals[0]

    assert proposal.compatible_support_count == 1
    assert proposal.specificity_recovery_eligible is False
    assert "maritime_chokepoint" not in result.final_report.transmission_chain.affected_nodes


def test_non_repair_node_source_cannot_use_specificity_recovery():
    proposal = NodeRepairProposal(
        proposed_node="maritime_chokepoint",
        reason="unit test",
        candidate_source="manual_non_repair",
        projected_current_context=_maritime_chokepoint_context("current"),
    )

    updated = _specificity_recovery_proposal(
        _hormuz_event(),
        proposal,
        ["case_a", "case_b"],
    )

    assert updated.specificity_recovery_eligible is False
    assert "candidate_not_from_v5_node_repair" in updated.specificity_recovery_reason


def test_specificity_recovery_is_candidate_local(monkeypatch):
    contexts = {
        ("case_a", "maritime_chokepoint"): _maritime_chokepoint_context("case_a"),
        ("case_b", "maritime_chokepoint"): _maritime_chokepoint_context("case_b"),
        ("case_a", "defense"): _defense_context("case_a"),
        ("case_b", "defense"): _defense_context("case_b"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Mixed case A",
                summary="Historical mixed context.",
                event_type="mixed",
                supply_chain_nodes=["maritime_chokepoint", "defense"],
            ),
            RetrievedCase(
                case_id="case_b",
                title="Mixed case B",
                summary="Historical mixed context.",
                event_type="mixed",
                supply_chain_nodes=["maritime_chokepoint", "defense"],
            ),
        ],
    )

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(enable_specificity_recovery=True),
    )
    eligibility = {
        proposal.proposed_node: proposal.specificity_recovery_eligible
        for proposal in result.state.repair_proposals
    }

    assert eligibility["maritime_chokepoint"] is True
    assert eligibility["defense"] is False
    assert "maritime_chokepoint" in result.final_report.transmission_chain.affected_nodes
    assert "defense" not in result.final_report.transmission_chain.affected_nodes


def test_applicability_gate_preserves_existing_recovery_when_disabled(monkeypatch):
    _patch_default_broad_domain_only_fixture(monkeypatch)

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(enable_specificity_recovery=True),
    )
    proposal = result.state.repair_proposals[0]

    assert proposal.applicability_status == "domain_association_only"
    assert proposal.compatible_support_count == 2
    assert proposal.specificity_recovery_eligible is True
    assert "maritime_chokepoint" in result.final_report.transmission_chain.affected_nodes


def test_applicability_gate_allows_grounded_current_event(monkeypatch):
    _patch_default_broad_specific_fixture(monkeypatch)

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(
            enable_specificity_recovery=True,
            enable_current_event_applicability_gate=True,
        ),
    )
    proposal = result.state.repair_proposals[0]

    assert proposal.applicability_status == "grounded"
    assert proposal.specificity_recovery_eligible is True
    assert "hormuz" in proposal.projection_cues
    assert "maritime_chokepoint" in result.final_report.transmission_chain.affected_nodes


def test_applicability_gate_blocks_domain_only_candidate(monkeypatch):
    _patch_default_broad_domain_only_fixture(monkeypatch)

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(
            enable_specificity_recovery=True,
            enable_current_event_applicability_gate=True,
        ),
    )
    proposal = result.state.repair_proposals[0]

    assert proposal.proposed_node == "maritime_chokepoint"
    assert proposal.projection_status == "projected"
    assert proposal.applicability_status == "domain_association_only"
    assert proposal.compatible_support_count == 2
    assert proposal.specificity_recovery_eligible is False
    assert "current_event_applicability_domain_association_only" in proposal.specificity_recovery_reason
    assert "maritime_chokepoint" not in result.final_report.transmission_chain.affected_nodes


def test_historical_support_cannot_substitute_for_applicability(monkeypatch):
    contexts = {
        (f"case_{index}", "maritime_chokepoint"): _maritime_chokepoint_context(f"case_{index}")
        for index in range(8)
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_domain_only_maritime_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id=f"case_{index}",
                title=f"Domain-only maritime case {index}",
                summary="Historical maritime chokepoint route security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            )
            for index in range(8)
        ],
    )

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(
            enable_specificity_recovery=True,
            enable_current_event_applicability_gate=True,
        ),
    )
    proposal = result.state.repair_proposals[0]

    assert proposal.compatible_support_count == 8
    assert proposal.applicability_status == "domain_association_only"
    assert proposal.specificity_recovery_eligible is False


def test_applicability_gate_is_candidate_local(monkeypatch):
    contexts = {
        ("case_a", "maritime_chokepoint"): _maritime_chokepoint_context("case_a"),
        ("case_b", "maritime_chokepoint"): _maritime_chokepoint_context("case_b"),
        ("case_a", "defense"): _defense_context("case_a"),
        ("case_b", "defense"): _defense_context("case_b"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Mixed case A",
                summary="Historical mixed context.",
                event_type="mixed",
                supply_chain_nodes=["maritime_chokepoint", "defense"],
            ),
            RetrievedCase(
                case_id="case_b",
                title="Mixed case B",
                summary="Historical mixed context.",
                event_type="mixed",
                supply_chain_nodes=["maritime_chokepoint", "defense"],
            ),
        ],
    )

    result = run_v5_pipeline(
        NEWS,
        event_analyzer="rule",
        config=V5DiscoveryConfig(
            enable_specificity_recovery=True,
            enable_current_event_applicability_gate=True,
        ),
    )
    eligibility = {
        proposal.proposed_node: proposal.specificity_recovery_eligible
        for proposal in result.state.repair_proposals
    }

    assert eligibility["maritime_chokepoint"] is True
    assert eligibility["defense"] is False


def _patch_fixture_pipeline(monkeypatch, contexts, event=None, retrieved_cases=None):
    monkeypatch.setattr("src.v5_pipeline._analyze_event", lambda news, analyzer: event or _event())
    monkeypatch.setattr(
        "src.v5_pipeline.retrieve_cases",
        lambda news, event, top_k: retrieved_cases or _retrieved_cases(),
    )
    monkeypatch.setattr(
        "src.agents.node_discovery_repair.load_historical_contexts",
        lambda: contexts,
    )
    monkeypatch.setattr(
        "src.agents.transmission_builder.load_historical_contexts",
        lambda: contexts,
    )


def _patch_default_broad_specific_fixture(monkeypatch):
    contexts = {
        ("case_a", "maritime_chokepoint"): _maritime_chokepoint_context("case_a"),
        ("case_b", "maritime_chokepoint"): _maritime_chokepoint_context("case_b"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Hormuz tanker tensions A",
                summary="Historical Hormuz route security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            ),
            RetrievedCase(
                case_id="case_b",
                title="Hormuz tanker tensions B",
                summary="Historical maritime chokepoint security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            ),
        ],
    )


def _patch_default_broad_domain_only_fixture(monkeypatch):
    contexts = {
        ("case_a", "maritime_chokepoint"): _maritime_chokepoint_context("case_a"),
        ("case_b", "maritime_chokepoint"): _maritime_chokepoint_context("case_b"),
    }
    _patch_fixture_pipeline(
        monkeypatch,
        contexts,
        event=_domain_only_maritime_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Hormuz tanker tensions A",
                summary="Historical Hormuz route security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            ),
            RetrievedCase(
                case_id="case_b",
                title="Hormuz tanker tensions B",
                summary="Historical maritime chokepoint security disruption.",
                event_type="maritime_security_disruption",
                supply_chain_nodes=["maritime_chokepoint"],
            ),
        ],
    )


def _event() -> EventAnalysis:
    return EventAnalysis(
        title="Red Sea shipping sanctions",
        summary=NEWS,
        event_type="maritime_security_disruption",
        regions=["Middle East", "Global"],
        industries=["shipping", "insurance", "energy"],
        supply_chain_nodes=["maritime_chokepoint"],
        shock_direction="route_disruption_risk",
        risk_factors=["shipping", "sanctions"],
    )


def _hormuz_event() -> EventAnalysis:
    return EventAnalysis(
        title="Hormuz safe passage",
        summary="Framework concerning safe passage through the Strait of Hormuz following maritime security concerns.",
        event_type="geopolitical_risk_event",
        regions=["Middle East", "Global"],
        industries=[],
        supply_chain_nodes=["broad_etf"],
        shock_direction="risk_watchlist_candidate",
        risk_factors=[],
    )


def _domain_only_maritime_event() -> EventAnalysis:
    return EventAnalysis(
        title="MT Settebello attack",
        summary="The IMO reported an attack involving the MT Settebello, documenting a maritime security disruption.",
        event_type="geopolitical_risk_event",
        regions=["Global"],
        industries=[],
        supply_chain_nodes=["broad_etf"],
        shock_direction="risk_watchlist_candidate",
        risk_factors=[],
    )


def _retrieved_cases() -> list[RetrievedCase]:
    return [
        RetrievedCase(
            case_id="case_a",
            title="Historical tanker insurance disruption A",
            summary="Oil tanker route disruptions raised insurance constraints.",
            event_type="maritime_security_disruption",
            supply_chain_nodes=["maritime_chokepoint"],
        ),
        RetrievedCase(
            case_id="case_b",
            title="Historical tanker insurance disruption B",
            summary="Regional shipping attacks raised insurance constraints.",
            event_type="maritime_security_disruption",
            supply_chain_nodes=["maritime_chokepoint"],
        ),
        RetrievedCase(
            case_id="case_c",
            title="Unrelated port case",
            summary="A port disruption affected logistics.",
            event_type="port_disruption",
            supply_chain_nodes=["ports"],
        ),
    ]


def _fixture_contexts(case_ids: list[str]) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (case_id, "marine_insurance"): _maritime_context("marine_insurance")
        for case_id in case_ids
    }


def _maritime_context(node: str) -> dict[str, str]:
    return {
        "node": node,
        "shock_type": "sanctions",
        "constraint_type": "insurance_constraint",
        "upstream_driver": "shipping_insurance_constraint",
        "target_node_role": "financing_or_insurance_channel",
        "canonical_context": "energy_shipping_insurance_constraint",
    }


def _maritime_chokepoint_context(case_id: str) -> dict[str, str]:
    return {
        "node": "maritime_chokepoint",
        "shock_type": "military_escalation",
        "constraint_type": "route_disruption",
        "upstream_driver": f"{case_id}_security_risk",
        "target_node_role": "direct_disruption_target",
        "canonical_context": "maritime_route_security_constraint",
    }


def _defense_context(case_id: str) -> dict[str, str]:
    return {
        "node": "defense",
        "shock_type": "military_escalation",
        "constraint_type": "security_risk",
        "upstream_driver": f"{case_id}_defense_context",
        "target_node_role": "downstream_exposure",
        "canonical_context": "regional_security_context",
    }


def _heldout_description(event_id: str) -> str:
    with open(
        "data/validation_v4/temporal_final_heldout_events.csv",
        newline="",
        encoding="utf-8",
    ) as handle:
        for row in csv.DictReader(handle):
            if row["event_id"] == event_id:
                return row["short_description"]
    raise AssertionError(f"missing held-out event fixture: {event_id}")
