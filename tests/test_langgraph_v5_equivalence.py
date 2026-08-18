from __future__ import annotations

from typing import Any

from src.orchestration import langgraph_v5
from src.schemas import EventAnalysis, RetrievedCase
from src.v5_config import V5DiscoveryConfig
from src.v5_pipeline import run_v5_pipeline


NEWS = "Red Sea shipping sanctions increase marine insurance costs for oil tankers."


def test_langgraph_v5_repair_disabled_matches_frozen_runner():
    config = V5DiscoveryConfig(enable_node_repair=False)

    frozen = run_v5_pipeline(NEWS, event_analyzer="rule", config=config)
    graph = langgraph_v5.run_v5_langgraph(NEWS, event_analyzer="rule", config=config)

    assert _canonical_result(graph) == _canonical_result(frozen)


def test_langgraph_v5_repair_path_matches_frozen_runner(monkeypatch):
    _patch_fixture_pipeline(monkeypatch, _fixture_contexts(["case_a", "case_b"]))

    frozen = run_v5_pipeline(NEWS, event_analyzer="rule")
    graph = langgraph_v5.run_v5_langgraph(NEWS, event_analyzer="rule")

    assert _canonical_result(graph) == _canonical_result(frozen)


def test_langgraph_v5_specificity_and_applicability_match_frozen_runner(monkeypatch):
    config = V5DiscoveryConfig(
        enable_specificity_recovery=True,
        enable_current_event_applicability_gate=True,
    )
    _patch_fixture_pipeline(
        monkeypatch,
        {
            ("case_a", "maritime_chokepoint"): _maritime_chokepoint_context("case_a"),
            ("case_b", "maritime_chokepoint"): _maritime_chokepoint_context("case_b"),
            ("case_a", "defense"): _defense_context("case_a"),
            ("case_b", "defense"): _defense_context("case_b"),
        },
        event=_hormuz_event(),
        retrieved_cases=[
            RetrievedCase(
                case_id="case_a",
                title="Mixed case A",
                summary="Historical Hormuz route security disruption.",
                event_type="mixed",
                supply_chain_nodes=["maritime_chokepoint", "defense"],
            ),
            RetrievedCase(
                case_id="case_b",
                title="Mixed case B",
                summary="Historical maritime chokepoint security disruption.",
                event_type="mixed",
                supply_chain_nodes=["maritime_chokepoint", "defense"],
            ),
        ],
    )

    frozen = run_v5_pipeline(NEWS, event_analyzer="rule", config=config)
    graph = langgraph_v5.run_v5_langgraph(NEWS, event_analyzer="rule", config=config)

    assert _canonical_result(graph) == _canonical_result(frozen)
    frozen_eligibility = {
        p.proposed_node: p.specificity_recovery_eligible
        for p in frozen.state.repair_proposals
    }
    graph_eligibility = {
        p.proposed_node: p.specificity_recovery_eligible
        for p in graph.state.repair_proposals
    }
    assert graph_eligibility == frozen_eligibility


def test_langgraph_v5_graph_exposes_expected_control_nodes():
    graph = langgraph_v5.build_v5_langgraph()
    graph_nodes = set(graph.get_graph().nodes)

    assert {
        "prepare_event",
        "retrieve_candidates",
        "verify_initial_v4",
        "diagnose_repair_need",
        "apply_node_repair",
        "project_repaired_context",
        "verify_repaired_v4",
        "recover_specificity",
        "finalize",
    }.issubset(graph_nodes)


def _canonical_result(result) -> dict[str, Any]:
    payload = result.model_dump(mode="json")
    for action in payload["state"]["trajectory"]:
        action["latency_ms"] = 0
    return {
        "final_report": payload["final_report"],
        "architecture_version": payload["architecture_version"],
        "repair_policy_version": payload["repair_policy_version"],
        "repair_enabled": payload["repair_enabled"],
        "state": payload["state"],
    }


def _patch_fixture_pipeline(monkeypatch, contexts, event=None, retrieved_cases=None):
    fixture_event = event or _event()
    fixture_retrieved = retrieved_cases or _retrieved_cases()
    monkeypatch.setattr("src.v5_pipeline._analyze_event", lambda news, analyzer: fixture_event)
    monkeypatch.setattr("src.v5_pipeline.retrieve_cases", lambda news, event, top_k: fixture_retrieved)
    monkeypatch.setattr("src.orchestration.langgraph_v5._analyze_event", lambda news, analyzer: fixture_event)
    monkeypatch.setattr(
        "src.orchestration.langgraph_v5.retrieve_cases",
        lambda news, event, top_k: fixture_retrieved,
    )
    monkeypatch.setattr(
        "src.agents.node_discovery_repair.load_historical_contexts",
        lambda: contexts,
    )
    monkeypatch.setattr(
        "src.agents.transmission_builder.load_historical_contexts",
        lambda: contexts,
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
        summary=(
            "Framework concerning safe passage through the Strait of Hormuz "
            "following maritime security concerns."
        ),
        event_type="geopolitical_risk_event",
        regions=["Middle East", "Global"],
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
            summary="Port congestion affected container shipping.",
            event_type="logistics_disruption",
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
        "event_id": "fixture",
        "node": node,
        "shock_type": "shipping disruption",
        "constraint_type": "insurance and route constraint",
        "upstream_driver": "maritime security disruption",
        "target_node_role": "secondary exposure channel",
        "canonical_context": "maritime route disruption raising insurance pressure",
    }


def _maritime_chokepoint_context(case_id: str) -> dict[str, str]:
    return {
        "event_id": case_id,
        "node": "maritime_chokepoint",
        "shock_type": "shipping disruption",
        "constraint_type": "route security constraint",
        "upstream_driver": "maritime security disruption",
        "target_node_role": "critical shipping chokepoint",
        "canonical_context": "maritime chokepoint disruption around Hormuz",
    }


def _defense_context(case_id: str) -> dict[str, str]:
    return {
        "event_id": case_id,
        "node": "defense",
        "shock_type": "defense procurement",
        "constraint_type": "defense supply constraint",
        "upstream_driver": "military procurement demand",
        "target_node_role": "defense industrial channel",
        "canonical_context": "defense industrial base pressure",
    }
