"""Post-stage gate diagnostics that preserve the frozen verification code."""

from __future__ import annotations

import pandas as pd

from src.config import ASSET_MAPPING_PATH
from src.mechanism_context import support_diagnostics
from src.observability import record_gate_decision
from src.transmission_context_store import (
    load_historical_contexts,
    missing_context,
    project_current_event_context,
)
from src.v4_config import V4_CONFIG
from src.v5_models import V5AnalysisResult


def record_pipeline_gate_decisions(result: V5AnalysisResult) -> None:
    """Record final-run gate decisions from V5 state without changing outputs."""

    state = result.state
    event = state.event
    direct_nodes = set(state.direct_nodes)
    raw_support = _raw_node_support(state.retrieved_cases)
    historical_contexts = load_historical_contexts()
    default_broad = (
        event.event_type == "geopolitical_risk_event"
        and event.supply_chain_nodes == ["broad_etf"]
    )

    for node in state.candidate_nodes:
        if node in direct_nodes or node not in raw_support:
            continue
        projection = state.current_context_projections.get(node)
        current_context = (
            projection.projected_current_context
            if projection and projection.projected_current_context is not None
            else project_current_event_context(event, node)
        )
        supporting_contexts = [
            {
                "case_id": case_id,
                **historical_contexts.get((case_id, node), missing_context(node)),
            }
            for case_id in raw_support[node]
        ]
        diagnostics = support_diagnostics(current_context, supporting_contexts)
        compatible_count = int(
            state.compatible_support.get(
                node,
                diagnostics["compatible_support_count"],
            )
        )
        insufficient_count = int(diagnostics["insufficient_context_count"])
        mechanism_accepted = compatible_count > 0
        record_gate_decision(
            candidate_type="supply_chain_node",
            candidate_id=node,
            gate="mechanism_check",
            accepted=mechanism_accepted,
            reason_code=(
                "MECHANISM_COMPATIBLE"
                if mechanism_accepted
                else "MECHANISM_CONTEXT_INSUFFICIENT"
                if insufficient_count > 0
                else "MECHANISM_INCOMPATIBLE"
            ),
            support_count=compatible_count,
        )
        if not mechanism_accepted:
            continue
        support_accepted = compatible_count >= V4_CONFIG.compatible_support_threshold
        record_gate_decision(
            candidate_type="supply_chain_node",
            candidate_id=node,
            gate="support_threshold",
            accepted=support_accepted,
            reason_code=(
                "SUPPORT_THRESHOLD_MET"
                if support_accepted
                else "SUPPORT_BELOW_THRESHOLD"
            ),
            support_count=compatible_count,
            threshold=V4_CONFIG.compatible_support_threshold,
        )
        if default_broad:
            record_gate_decision(
                candidate_type="supply_chain_node",
                candidate_id=node,
                gate="broad_event_guardrail",
                accepted=False,
                reason_code="BROAD_EVENT_GUARDRAIL",
                support_count=compatible_count,
            )

    _record_applicability_decisions(result)
    _record_asset_resolution_decisions(result)
    _record_ranking_decision(result)


def _record_applicability_decisions(result: V5AnalysisResult) -> None:
    """Record current-event applicability outcomes for evaluated repair nodes."""

    for proposal in result.state.repair_proposals:
        if not proposal.specificity_recovery_evaluated:
            continue
        accepted = proposal.specificity_recovery_eligible
        reason = proposal.specificity_recovery_reason
        rejection_code = "SPECIFICITY_RECOVERY_INELIGIBLE"
        if (
            "current_event_applicability" in reason
            or "current_context_not_informative" in reason
        ):
            rejection_code = "CURRENT_EVENT_APPLICABILITY_FAILED"
        elif "compatible_support_below_threshold" in reason:
            rejection_code = "SUPPORT_BELOW_THRESHOLD"
        record_gate_decision(
            candidate_type="supply_chain_node",
            candidate_id=proposal.proposed_node,
            gate="current_event_applicability",
            accepted=accepted,
            reason_code=(
                "CURRENT_EVENT_APPLICABILITY_PASSED"
                if accepted
                else rejection_code
            ),
            support_count=proposal.compatible_support_count,
        )


def _record_asset_resolution_decisions(result: V5AnalysisResult) -> None:
    """Record whether each accepted node resolves in the authoritative mapping."""

    mapping = pd.read_csv(ASSET_MAPPING_PATH, usecols=["supply_chain_node"])
    mapped_nodes = set(mapping["supply_chain_node"].dropna().astype(str))
    for node in set(result.final_report.transmission_chain.affected_nodes):
        mapped = node in mapped_nodes
        record_gate_decision(
            candidate_type="supply_chain_node",
            candidate_id=node,
            gate="asset_resolution",
            accepted=mapped,
            reason_code=(
                "ASSET_MAPPING_RESOLVED" if mapped else "NODE_NOT_IN_ASSET_MAPPING"
            ),
        )


def _record_ranking_decision(result: V5AnalysisResult) -> None:
    """Record the explicit final second-order ranking qualification decision."""

    ranked = any(
        item.ranking_scope == "ranked_second_order"
        for item in result.final_report.evidence_results
    )
    record_gate_decision(
        candidate_type="ranking_output",
        candidate_id="second_order_ranking",
        gate="ranking_qualification",
        accepted=ranked,
        reason_code=(
            "SECOND_ORDER_ASSETS_RANKED"
            if ranked
            else "NO_QUALIFIED_SECOND_ORDER_ASSET"
        ),
    )


def _raw_node_support(retrieved_cases: list) -> dict[str, list[str]]:
    """Return unique retrieved-case support ids for each candidate node."""

    support: dict[str, list[str]] = {}
    for case in retrieved_cases:
        for node in set(case.supply_chain_nodes):
            if node:
                support.setdefault(node, []).append(case.case_id)
    return support
