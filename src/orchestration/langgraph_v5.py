"""LangGraph orchestration for the frozen GeoRisk V5 bounded recovery workflow.

This module is a thin state-machine adapter around the existing V5
implementation. It preserves the frozen V4 verification boundary and delegates
methodology-relevant work to the same functions used by ``src.v5_pipeline``.
"""

from __future__ import annotations

from time import perf_counter
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.case_retriever import retrieve_cases
from src.agents.llm_event_analyst import get_last_analysis_trace
from src.agents.node_discovery_repair import (
    compatible_support_counts,
    diagnose_evidence_state,
    historical_evidence_nodes,
    repaired_retrieved_cases,
)
from src.agents.repaired_context_projection import project_repaired_node_context
from src.pipeline import _analyze_event
from src.config import USE_LLM_EVENT_ANALYST
from src.gate_observability import record_pipeline_gate_decisions
from src.observability import (
    ExecutionMetadata,
    FunnelMetrics,
    analysis_run,
    emit_run_record,
)
from src.schemas import EventAnalysis, FinalReport, RetrievedCase, TransmissionChain
from src.v4_config import V4_CONFIG
from src.v5_config import V5_CONFIG, V5DiscoveryConfig, assert_v5_config
from src.v5_models import (
    AnalysisState,
    NodeRepairProposal,
    V5AnalysisResult,
    V5RuntimeMetrics,
)
from src.v5_pipeline import (
    _current_candidate_nodes,
    _current_proposed_nodes,
    _elapsed_ms,
    _projection_overrides,
    _proposal_case_ids,
    _record,
    _result,
    _run_frozen_v4_verify,
    _run_v5_specificity_recovery_verify,
)


Route = Literal["diagnose", "repair", "finalize"]


class GeoRiskV5State(TypedDict, total=False):
    """LangGraph-compatible state for one bounded V5 execution."""

    news_text: str
    event_analyzer: str | None
    config: V5DiscoveryConfig
    state: AnalysisState
    event: EventAnalysis
    retrieved_cases: list[RetrievedCase]
    initial_report: FinalReport
    initial_chain: TransmissionChain
    final_report: FinalReport
    final_chain: TransmissionChain
    proposals: list[NodeRepairProposal]
    projection_overrides: dict[str, dict[str, str]]
    support_delta: dict[str, int]
    phase_latency_ms: dict[str, float]
    result: V5AnalysisResult


def build_v5_langgraph():
    """Build the explicit LangGraph state machine for frozen V5."""

    graph = StateGraph(GeoRiskV5State)
    graph.add_node("prepare_event", prepare_event_node)
    graph.add_node("retrieve_candidates", retrieve_candidates_node)
    graph.add_node("verify_initial_v4", verify_initial_v4_node)
    graph.add_node("diagnose_repair_need", diagnose_repair_need_node)
    graph.add_node("apply_node_repair", apply_node_repair_node)
    graph.add_node("project_repaired_context", project_repaired_context_node)
    graph.add_node("verify_repaired_v4", verify_repaired_v4_node)
    graph.add_node("recover_specificity", recover_specificity_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "prepare_event")
    graph.add_edge("prepare_event", "retrieve_candidates")
    graph.add_edge("retrieve_candidates", "verify_initial_v4")
    graph.add_conditional_edges(
        "verify_initial_v4",
        route_after_initial_verify,
        {"diagnose": "diagnose_repair_need", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "diagnose_repair_need",
        route_after_diagnosis,
        {"repair": "apply_node_repair", "finalize": "finalize"},
    )
    graph.add_edge("apply_node_repair", "project_repaired_context")
    graph.add_edge("project_repaired_context", "verify_repaired_v4")
    graph.add_edge("verify_repaired_v4", "recover_specificity")
    graph.add_edge("recover_specificity", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def run_v5_langgraph(
    news_text: str,
    event_analyzer: str | None = None,
    config: V5DiscoveryConfig = V5_CONFIG,
) -> V5AnalysisResult:
    """Run frozen V5 through the LangGraph orchestration adapter."""

    assert_v5_config(config)
    if not news_text.strip():
        raise ValueError("news_text must contain a geopolitical risk news item.")

    graph = build_v5_langgraph()
    start = perf_counter()
    with analysis_run() as telemetry:
        requested_analyzer = _selected_event_analyzer(event_analyzer)
        try:
            output = graph.invoke(
                {
                    "news_text": news_text,
                    "event_analyzer": event_analyzer,
                    "config": config,
                }
            )
        except Exception:
            total_latency_ms = _elapsed_precise_ms(start)
            trace = get_last_analysis_trace() if requested_analyzer == "llm" else {}
            failure_metadata = ExecutionMetadata(
                run_id=telemetry.run_id,
                requested_event_analyzer=requested_analyzer,
                effective_event_analyzer=str(
                    trace.get("effective_event_analyzer", requested_analyzer)
                ),
                degraded=bool(trace.get("fallback_occurred", False)),
                degradation_reason=(
                    str(trace.get("degradation_reason"))
                    if trace.get("degradation_reason")
                    else None
                ),
                total_latency_ms=total_latency_ms,
                llm_latency_ms=float(trace.get("llm_latency_ms", 0.0) or 0.0),
                llm_latency_share_pct=(
                    min(
                        100.0,
                        float(trace.get("llm_latency_ms", 0.0) or 0.0)
                        / total_latency_ms
                        * 100.0,
                    )
                    if total_latency_ms > 0
                    else 0.0
                ),
                token_usage=(
                    trace.get("token_usage")
                    if isinstance(trace.get("token_usage"), dict)
                    else None
                ),
                outcome_status="OPERATIONAL_FAILURE",
                funnel=FunnelMetrics(
                    rejected_decision_count=sum(
                        not decision.accepted for decision in telemetry.gate_decisions
                    )
                ),
                gate_decisions=list(telemetry.gate_decisions),
            )
            emit_run_record(failure_metadata, total_latency_ms=total_latency_ms)
            raise
        total_latency_ms = _elapsed_precise_ms(start)
        result = output["result"].model_copy(
            update={
                "runtime_metrics": V5RuntimeMetrics(
                    total_latency_ms=total_latency_ms,
                    phase_latency_ms=output.get("phase_latency_ms", {}),
                )
            }
        )
        metadata = _execution_metadata(
            result,
            run_id=telemetry.run_id,
            requested_event_analyzer=requested_analyzer,
        )
        result = result.model_copy(
            update={
                "final_report": result.final_report.model_copy(
                    update={"execution_metadata": metadata}
                )
            }
        )
        emit_run_record(metadata, total_latency_ms=total_latency_ms)
        return result


def prepare_event_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Analyze the current event and initialize shared V5 state."""

    news_text = state["news_text"]
    event_analyzer = state.get("event_analyzer")
    start = perf_counter()
    event = _analyze_event(news_text, event_analyzer)
    analysis_state = AnalysisState(
        event=event,
        direct_nodes=list(event.supply_chain_nodes),
        candidate_nodes=list(event.supply_chain_nodes),
        status="DISCOVERY",
    )
    _record(
        analysis_state,
        action="ANALYZE_EVENT",
        reason="V4 event analysis produced initial direct nodes",
        before="DISCOVERY",
        after="RETRIEVAL",
        latency_ms=_elapsed_ms(start),
    )
    return _with_phase_timing(
        {"event": event, "state": analysis_state},
        state,
        "event_analysis",
        start,
    )


def retrieve_candidates_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Run frozen V4 retrieval and derive the initial candidate node view."""

    analysis_state = state["state"]
    event = state["event"]
    start = perf_counter()
    retrieved_cases = retrieve_cases(
        state["news_text"],
        event,
        top_k=V4_CONFIG.retrieval_top_k,
    )
    analysis_state.retrieved_cases = retrieved_cases
    analysis_state.retrieval_attempts = 1
    analysis_state.historical_evidence_nodes = historical_evidence_nodes(retrieved_cases)
    analysis_state.current_proposed_nodes = _current_proposed_nodes(event, [])
    analysis_state.candidate_nodes = _current_candidate_nodes(event, retrieved_cases, [])
    _record(
        analysis_state,
        action="RETRIEVE",
        reason="Frozen V4 retrieval with configured top_k",
        before="RETRIEVAL",
        after="VERIFY",
        source_case_ids=[case.case_id for case in retrieved_cases],
        latency_ms=_elapsed_ms(start),
    )
    return _with_phase_timing(
        {"retrieved_cases": retrieved_cases, "state": analysis_state},
        state,
        "retrieval",
        start,
    )


def verify_initial_v4_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Enter the frozen V4 verification boundary for the initial candidates."""

    start = perf_counter()
    analysis_state = state["state"]
    event = state["event"]
    retrieved_cases = state["retrieved_cases"]
    initial_report, initial_chain = _run_frozen_v4_verify(event, retrieved_cases)
    analysis_state.current_proposed_nodes = _current_proposed_nodes(
        event,
        initial_chain.affected_nodes,
    )
    analysis_state.repair_candidate_pool = [
        node
        for node in analysis_state.historical_evidence_nodes
        if node not in set(analysis_state.current_proposed_nodes)
    ]
    analysis_state.compatible_support = compatible_support_counts(
        event,
        retrieved_cases,
        analysis_state.candidate_nodes,
    )
    return _with_phase_timing(
        {
            "initial_report": initial_report,
            "initial_chain": initial_chain,
            "final_report": initial_report,
            "final_chain": initial_chain,
            "state": analysis_state,
        },
        state,
        "initial_verification_mapping_ranking",
        start,
    )


def route_after_initial_verify(state: GeoRiskV5State) -> Route:
    """Skip repair exactly when the frozen V5 config disables repair."""

    return "diagnose" if state["config"].enable_node_repair else "finalize"


def diagnose_repair_need_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Run the existing deterministic V5 evidence diagnostic."""

    analysis_state = state["state"]
    event = state["event"]
    start = perf_counter()
    diagnosis, proposals = diagnose_evidence_state(
        event,
        state["retrieved_cases"],
        analysis_state.current_proposed_nodes,
        analysis_state.compatible_support,
        state["config"],
    )
    analysis_state.diagnosis = diagnosis
    analysis_state.repair_proposals = proposals
    analysis_state.repaired_candidate_nodes = [
        proposal.proposed_node for proposal in proposals
    ]
    _record(
        analysis_state,
        action=f"DIAGNOSE_{diagnosis}",
        reason="Deterministic V5 evidence diagnostic",
        before="VERIFY",
        after="REPAIR" if diagnosis == "NODE_GAP" else "FINAL",
        candidate_nodes_added=[proposal.proposed_node for proposal in proposals],
        source_case_ids=_proposal_case_ids(proposals),
        latency_ms=_elapsed_ms(start),
    )
    return _with_phase_timing(
        {"proposals": proposals, "state": analysis_state},
        state,
        "repair_diagnosis",
        start,
    )


def route_after_diagnosis(state: GeoRiskV5State) -> Route:
    """Respect the frozen one-pass repair budget."""

    analysis_state = state["state"]
    if (
        analysis_state.diagnosis == "NODE_GAP"
        and analysis_state.repair_attempts < state["config"].max_repair_attempts
    ):
        return "repair"
    return "finalize"


def apply_node_repair_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Apply existing bounded node repair proposals to retrieved cases."""

    start = perf_counter()
    repaired_cases = repaired_retrieved_cases(
        state["retrieved_cases"],
        state.get("proposals", []),
    )
    return _with_phase_timing(
        {"retrieved_cases": repaired_cases},
        state,
        "node_repair",
        start,
    )


def project_repaired_context_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Project current-event context for repaired nodes using existing rules."""

    start = perf_counter()
    analysis_state = state["state"]
    event = state["event"]
    proposals = state.get("proposals", [])
    projections = {
        proposal.proposed_node: project_repaired_node_context(
            event,
            proposal.proposed_node,
        )
        for proposal in proposals
    }
    projection_overrides = {
        node: projection.projected_current_context
        for node, projection in projections.items()
        if projection.projected_current_context is not None
    }
    analysis_state.current_context_projections = projections
    proposals = [
        proposal.model_copy(
            update={
                "projection_attempted": projections[proposal.proposed_node].projection_attempted,
                "projection_source": projections[proposal.proposed_node].projection_source,
                "projection_status": projections[proposal.proposed_node].projection_status,
                "projected_current_context": projections[proposal.proposed_node].projected_current_context,
                "projection_cues": projections[proposal.proposed_node].projection_cues,
                "applicability_status": projections[proposal.proposed_node].applicability_status,
                "applicability_reason": projections[proposal.proposed_node].applicability_reason,
                "current_context_available": projections[proposal.proposed_node].projected_current_context is not None,
            }
        )
        for proposal in proposals
    ]
    analysis_state.repair_proposals = proposals
    return _with_phase_timing(
        {
            "projection_overrides": projection_overrides,
            "proposals": proposals,
            "state": analysis_state,
        },
        state,
        "context_projection",
        start,
    )


def verify_repaired_v4_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Re-enter frozen V4 verification with repaired candidates and projections."""

    start = perf_counter()
    analysis_state = state["state"]
    event = state["event"]
    proposals = state.get("proposals", [])
    repaired_cases = state["retrieved_cases"]
    repaired_nodes = _current_candidate_nodes(event, repaired_cases, [])
    repaired_support = compatible_support_counts(
        event,
        repaired_cases,
        repaired_nodes,
        current_context_overrides=state.get("projection_overrides", {}),
    )
    support_delta = {
        proposal.proposed_node: (
            repaired_support.get(proposal.proposed_node, 0)
            - analysis_state.compatible_support.get(proposal.proposed_node, 0)
        )
        for proposal in proposals
    }
    proposals = [
        proposal.model_copy(
            update={
                "compatible_support_count": repaired_support.get(
                    proposal.proposed_node,
                    0,
                )
            }
        )
        for proposal in proposals
    ]
    analysis_state.repair_proposals = proposals
    analysis_state.repair_attempts += 1
    analysis_state.retrieved_cases = repaired_cases
    analysis_state.candidate_nodes = repaired_nodes
    analysis_state.historical_evidence_nodes = historical_evidence_nodes(repaired_cases)
    analysis_state.compatible_support = repaired_support
    with _projection_overrides(state.get("projection_overrides", {})):
        final_report, final_chain = _run_frozen_v4_verify(event, repaired_cases)
    return _with_phase_timing(
        {
            "final_report": final_report,
            "final_chain": final_chain,
            "proposals": proposals,
            "support_delta": support_delta,
            "state": analysis_state,
        },
        state,
        "repaired_verification_mapping_ranking",
        start,
    )


def recover_specificity_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Run existing candidate-local specificity recovery when configured."""

    start = perf_counter()
    analysis_state = state["state"]
    event = state["event"]
    proposals = state.get("proposals", [])
    final_report = state["final_report"]
    final_chain = state["final_chain"]
    if state["config"].enable_specificity_recovery:
        final_report, final_chain, proposals = _run_v5_specificity_recovery_verify(
            event,
            state["retrieved_cases"],
            final_chain,
            proposals,
            state.get("projection_overrides", {}),
            require_grounded_applicability=state[
                "config"
            ].enable_current_event_applicability_gate,
        )
        analysis_state.repair_proposals = proposals
    analysis_state.current_proposed_nodes = _current_proposed_nodes(
        event,
        final_chain.affected_nodes,
    )
    accepted = set(final_report.transmission_chain.affected_nodes)
    analysis_state.unresolved_nodes = [
        proposal.proposed_node
        for proposal in proposals
        if proposal.proposed_node not in accepted
    ]
    _record(
        analysis_state,
        action="EXPAND_NODES",
        reason="Added bounded sidecar-derived node proposals, then reran frozen V4 verify",
        before="REPAIR",
        after="FINAL",
        candidate_nodes_added=[proposal.proposed_node for proposal in proposals],
        source_case_ids=_proposal_case_ids(proposals),
        support_delta=state.get("support_delta", {}),
    )
    return _with_phase_timing(
        {
            "final_report": final_report,
            "final_chain": final_chain,
            "proposals": proposals,
            "state": analysis_state,
        },
        state,
        "specificity_recovery",
        start,
    )


def finalize_node(state: GeoRiskV5State) -> GeoRiskV5State:
    """Finalize the V5 result without changing final evidence semantics."""

    start = perf_counter()
    analysis_state = state["state"]
    final_report = state["final_report"]
    config = state["config"]
    terminal_status = _terminal_status(final_report)
    if not config.enable_node_repair and analysis_state.diagnosis is None:
        _record(
            analysis_state,
            action="FINALIZE",
            reason="Node repair disabled; returning frozen V4-equivalent output",
            before="VERIFY",
            after=terminal_status,
        )
    else:
        analysis_state.status = terminal_status
        if terminal_status != "RANKED":
            _record(
                analysis_state,
                action="ABSTAIN",
                reason=(
                    "No second-order exposure qualified for ranking"
                    if terminal_status == "RANKING_ABSTAIN"
                    else "Frozen V4 verification produced no mapped evidence results"
                ),
                before="FINAL",
                after=terminal_status,
            )
    return _with_phase_timing(
        {"result": _result(final_report, analysis_state, config), "state": analysis_state},
        state,
        "finalization",
        start,
    )


def _with_phase_timing(
    update: GeoRiskV5State,
    state: GeoRiskV5State,
    phase: str,
    start: float,
) -> GeoRiskV5State:
    """Attach one non-semantic phase duration to a graph state update."""

    timings = dict(state.get("phase_latency_ms", {}))
    timings[phase] = timings.get(phase, 0.0) + _elapsed_precise_ms(start)
    return {**update, "phase_latency_ms": timings}


def _elapsed_precise_ms(start: float) -> float:
    """Return a non-negative millisecond duration without integer rounding."""

    return max(0.0, (perf_counter() - start) * 1000.0)


def _terminal_status(final_report: FinalReport) -> str:
    """Classify analytical completion separately from operational failures."""

    if any(
        result.ranking_scope == "ranked_second_order"
        for result in final_report.evidence_results
    ):
        return "RANKED"
    if final_report.evidence_results:
        return "RANKING_ABSTAIN"
    return "FULL_ABSTAIN"


def _selected_event_analyzer(event_analyzer: str | None) -> str:
    """Resolve the requested analyzer exactly as the pipeline selector does."""

    if event_analyzer is not None:
        return event_analyzer
    return "llm" if USE_LLM_EVENT_ANALYST else "rule"


def _execution_metadata(
    result: V5AnalysisResult,
    *,
    run_id: str,
    requested_event_analyzer: str,
) -> ExecutionMetadata:
    """Build output metadata and final gate records for one completed run."""

    from src.observability import current_telemetry

    report = result.final_report
    record_pipeline_gate_decisions(result)
    ranked = [
        item for item in report.evidence_results
        if item.ranking_scope == "ranked_second_order"
    ]
    first_order = [
        item for item in report.evidence_results
        if item.ranking_scope == "reference_first_order"
    ]
    collector = current_telemetry()
    decisions = list(collector.gate_decisions if collector else [])
    mechanism_nodes = {
        decision.candidate_id
        for decision in decisions
        if decision.gate == "mechanism_check" and decision.accepted
    }
    qualified_nodes = {
        decision.candidate_id
        for decision in decisions
        if decision.gate == "support_threshold" and decision.accepted
    }
    trace = get_last_analysis_trace() if requested_event_analyzer == "llm" else {}
    degraded = bool(trace.get("fallback_occurred", False))
    effective_analyzer = str(
        trace.get("effective_event_analyzer", requested_event_analyzer)
    )
    funnel = FunnelMetrics(
        direct_node_count=len(set(result.state.direct_nodes)),
        retrieved_case_count=len(result.state.retrieved_cases),
        raw_candidate_node_count=len(
            set(result.state.candidate_nodes) - set(result.state.direct_nodes)
        ),
        mechanism_compatible_node_count=len(mechanism_nodes),
        support_qualified_node_count=len(qualified_nodes),
        affected_node_count=len(set(report.transmission_chain.affected_nodes)),
        mapped_asset_count=len({item.ticker for item in report.evidence_results}),
        ranked_second_order_count=len(ranked),
        first_order_reference_count=len(first_order),
        rejected_decision_count=sum(not decision.accepted for decision in decisions),
    )
    return ExecutionMetadata(
        run_id=run_id,
        requested_event_analyzer=requested_event_analyzer,
        effective_event_analyzer=effective_analyzer,
        degraded=degraded,
        degradation_reason=(
            str(trace.get("degradation_reason"))
            if trace.get("degradation_reason")
            else None
        ),
        total_latency_ms=(
            result.runtime_metrics.total_latency_ms if result.runtime_metrics else 0.0
        ),
        llm_latency_ms=float(trace.get("llm_latency_ms", 0.0) or 0.0),
        llm_latency_share_pct=(
            min(
                100.0,
                float(trace.get("llm_latency_ms", 0.0) or 0.0)
                / result.runtime_metrics.total_latency_ms
                * 100.0,
            )
            if result.runtime_metrics and result.runtime_metrics.total_latency_ms > 0
            else 0.0
        ),
        phase_latency_ms=(
            result.runtime_metrics.phase_latency_ms if result.runtime_metrics else {}
        ),
        token_usage=trace.get("token_usage") if isinstance(trace.get("token_usage"), dict) else None,
        outcome_status=_terminal_status(report),
        funnel=funnel,
        gate_decisions=decisions,
    )
