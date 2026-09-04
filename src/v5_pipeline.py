"""GeoRisk V5 Agentic Discovery MVP pipeline.

V5 wraps frozen V4 discovery and evidence verification with one deterministic,
bounded node discovery repair pass. It does not change V4 evidence thresholds,
mechanism compatibility, evidence labels, asset mapping, or ranking semantics.
"""

from __future__ import annotations

from time import perf_counter
from contextlib import contextmanager
from collections.abc import Iterator

from src import nodes
from src.agents.asset_ranker import rank_assets
from src.agents.case_retriever import retrieve_cases
from src.agents.evidence_agent import grade_evidence
from src.agents.market_mapper import map_assets
from src.agents.node_discovery_repair import (
    compatible_support_case_ids,
    compatible_support_counts,
    diagnose_evidence_state,
    historical_evidence_nodes,
    repaired_retrieved_cases,
)
from src.agents.repaired_context_projection import project_repaired_node_context
from src.agents.report_agent import generate_report
from src.agents.transmission_builder import build_transmission_chain
from src.pipeline import _analyze_event
from src.schemas import EventAnalysis, FinalReport, RetrievedCase, TransmissionChain
from src.v4_config import V4_CONFIG, assert_v4_config
from src.v5_config import V5_CONFIG, V5DiscoveryConfig, assert_v5_config
from src.v5_models import AgentAction, AnalysisState, NodeRepairProposal, V5AnalysisResult


def run_v5_pipeline(
    news_text: str,
    event_analyzer: str | None = None,
    config: V5DiscoveryConfig = V5_CONFIG,
) -> V5AnalysisResult:
    """Run V5 bounded node discovery repair with frozen V4 verification."""

    assert_v5_config(config)
    if not news_text.strip():
        raise ValueError("news_text must contain a geopolitical risk news item.")

    state_start = perf_counter()
    event = _analyze_event(news_text, event_analyzer)
    state = AnalysisState(
        event=event,
        direct_nodes=list(event.supply_chain_nodes),
        candidate_nodes=list(event.supply_chain_nodes),
        status="DISCOVERY",
    )
    _record(
        state,
        action="ANALYZE_EVENT",
        reason="V4 event analysis produced initial direct nodes",
        before="DISCOVERY",
        after="RETRIEVAL",
        latency_ms=_elapsed_ms(state_start),
    )

    retrieve_start = perf_counter()
    retrieved_cases = retrieve_cases(news_text, event, top_k=V4_CONFIG.retrieval_top_k)
    state.retrieved_cases = retrieved_cases
    state.retrieval_attempts = 1
    state.historical_evidence_nodes = historical_evidence_nodes(retrieved_cases)
    state.current_proposed_nodes = _current_proposed_nodes(event, [])
    state.candidate_nodes = _current_candidate_nodes(event, retrieved_cases, [])
    _record(
        state,
        action="RETRIEVE",
        reason="Frozen V4 retrieval with configured top_k",
        before="RETRIEVAL",
        after="VERIFY",
        source_case_ids=[case.case_id for case in retrieved_cases],
        latency_ms=_elapsed_ms(retrieve_start),
    )

    initial_report, initial_chain = _run_frozen_v4_verify(event, retrieved_cases)
    state.current_proposed_nodes = _current_proposed_nodes(
        event,
        initial_chain.affected_nodes,
    )
    state.repair_candidate_pool = [
        node
        for node in state.historical_evidence_nodes
        if node not in set(state.current_proposed_nodes)
    ]
    state.compatible_support = compatible_support_counts(
        event,
        retrieved_cases,
        state.candidate_nodes,
    )

    if not config.enable_node_repair:
        terminal_status = _terminal_status(initial_report)
        _record(
            state,
            action="FINALIZE",
            reason="Node repair disabled; returning frozen V4-equivalent output",
            before="VERIFY",
            after=terminal_status,
        )
        return _result(initial_report, state, config)

    diagnosis_start = perf_counter()
    diagnosis, proposals = diagnose_evidence_state(
        event,
        retrieved_cases,
        state.current_proposed_nodes,
        state.compatible_support,
        config,
    )
    state.diagnosis = diagnosis
    state.repair_proposals = proposals
    state.repaired_candidate_nodes = [
        proposal.proposed_node for proposal in proposals
    ]
    _record(
        state,
        action=f"DIAGNOSE_{diagnosis}",
        reason="Deterministic V5 evidence diagnostic",
        before="VERIFY",
        after="REPAIR" if diagnosis == "NODE_GAP" else "FINAL",
        candidate_nodes_added=[proposal.proposed_node for proposal in proposals],
        source_case_ids=_proposal_case_ids(proposals),
        latency_ms=_elapsed_ms(diagnosis_start),
    )

    final_report = initial_report
    if diagnosis == "NODE_GAP" and state.repair_attempts < config.max_repair_attempts:
        repair_start = perf_counter()
        repaired_cases = repaired_retrieved_cases(retrieved_cases, proposals)
        repaired_nodes = _current_candidate_nodes(event, repaired_cases, [])
        repaired_historical_nodes = historical_evidence_nodes(repaired_cases)
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
        state.current_context_projections = projections
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
        state.repair_proposals = proposals
        repaired_support = compatible_support_counts(
            event,
            repaired_cases,
            repaired_nodes,
            current_context_overrides=projection_overrides,
        )
        support_delta = {
            proposal.proposed_node: (
                repaired_support.get(proposal.proposed_node, 0)
                - state.compatible_support.get(proposal.proposed_node, 0)
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
        state.repair_proposals = proposals
        state.repair_attempts += 1
        state.retrieved_cases = repaired_cases
        state.candidate_nodes = repaired_nodes
        state.historical_evidence_nodes = repaired_historical_nodes
        state.compatible_support = repaired_support
        with _projection_overrides(projection_overrides):
            final_report, final_chain = _run_frozen_v4_verify(event, repaired_cases)
        if config.enable_specificity_recovery:
            final_report, final_chain, proposals = _run_v5_specificity_recovery_verify(
                event,
                repaired_cases,
                final_chain,
                proposals,
                projection_overrides,
                require_grounded_applicability=config.enable_current_event_applicability_gate,
            )
            state.repair_proposals = proposals
        state.current_proposed_nodes = _current_proposed_nodes(
            event,
            final_chain.affected_nodes,
        )
        accepted = set(final_report.transmission_chain.affected_nodes)
        state.unresolved_nodes = [
            proposal.proposed_node
            for proposal in proposals
            if proposal.proposed_node not in accepted
        ]
        _record(
            state,
            action="EXPAND_NODES",
            reason="Added bounded sidecar-derived node proposals, then reran frozen V4 verify",
            before="REPAIR",
            after="FINAL",
            candidate_nodes_added=[proposal.proposed_node for proposal in proposals],
            source_case_ids=_proposal_case_ids(proposals),
            support_delta=support_delta,
            latency_ms=_elapsed_ms(repair_start),
        )

    terminal_status = _terminal_status(final_report)
    state.status = terminal_status  # type: ignore[assignment]
    if terminal_status != "RANKED":
        _record(
            state,
            action="ABSTAIN",
            reason=(
                "No second-order exposure qualified for ranking"
                if terminal_status == "RANKING_ABSTAIN"
                else "Frozen V4 verification produced no mapped evidence results"
            ),
            before="FINAL",
            after=terminal_status,
        )
    return _result(final_report, state, config)


def _run_frozen_v4_verify(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
) -> tuple[FinalReport, TransmissionChain]:
    """Run the unchanged V4 verification, mapping, grading, ranking, and report path."""

    assert_v4_config(V4_CONFIG)
    transmission_chain = build_transmission_chain(
        event,
        retrieved_cases,
        use_mechanism_compatible_support=V4_CONFIG.use_mechanism_compatible_support,
    )
    candidate_assets = map_assets(event, transmission_chain)
    evidence_results = grade_evidence(
        event,
        candidate_assets,
        retrieved_cases,
        transmission_chain,
    )
    evidence_results = rank_assets(
        evidence_results,
        event,
        retrieved_cases,
        transmission_chain,
    )
    return (
        generate_report(
            event,
            retrieved_cases,
            transmission_chain,
            evidence_results,
        ),
        transmission_chain,
    )


def _run_v5_specificity_recovery_verify(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    frozen_chain: TransmissionChain,
    proposals: list[NodeRepairProposal],
    projection_overrides: dict[str, dict[str, str]],
    *,
    require_grounded_applicability: bool = False,
) -> tuple[FinalReport, TransmissionChain, list[NodeRepairProposal]]:
    """Allow eligible repaired candidates past only the default-broad event lock."""

    support_case_ids = compatible_support_case_ids(
        event,
        retrieved_cases,
        [proposal.proposed_node for proposal in proposals],
        current_context_overrides=projection_overrides,
    )
    updated_proposals = [
        _specificity_recovery_proposal(
            event,
            proposal,
            support_case_ids.get(proposal.proposed_node, []),
            require_grounded_applicability=require_grounded_applicability,
        )
        for proposal in proposals
    ]
    eligible_nodes = [
        proposal.proposed_node
        for proposal in updated_proposals
        if proposal.specificity_recovery_eligible
    ]
    if not eligible_nodes:
        return _report_from_chain(event, retrieved_cases, frozen_chain), frozen_chain, updated_proposals

    recovered_chain = _chain_with_specificity_recovered_nodes(
        frozen_chain,
        eligible_nodes,
        support_case_ids,
    )
    final_report = _report_from_chain(event, retrieved_cases, recovered_chain)
    retained = set(recovered_chain.affected_nodes)
    updated_proposals = [
        proposal.model_copy(
            update={
                "event_guardrail_bypassed_for_candidate": proposal.proposed_node in eligible_nodes,
                "downstream_final_status": (
                    "final_retained"
                    if proposal.proposed_node in retained
                    else "rejected"
                ),
                "downstream_final_reason": (
                    "specificity_recovered_then_v4_downstream_qualified"
                    if proposal.proposed_node in retained
                    else "not_retained_after_specificity_recovery_evaluation"
                ),
            }
        )
        for proposal in updated_proposals
    ]
    return final_report, recovered_chain, updated_proposals


def _report_from_chain(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    transmission_chain: TransmissionChain,
) -> FinalReport:
    candidate_assets = map_assets(event, transmission_chain)
    evidence_results = grade_evidence(
        event,
        candidate_assets,
        retrieved_cases,
        transmission_chain,
    )
    evidence_results = rank_assets(
        evidence_results,
        event,
        retrieved_cases,
        transmission_chain,
    )
    return generate_report(
        event,
        retrieved_cases,
        transmission_chain,
        evidence_results,
    )


def _specificity_recovery_proposal(
    event: EventAnalysis,
    proposal: NodeRepairProposal,
    compatible_case_ids: list[str],
    *,
    require_grounded_applicability: bool = False,
) -> NodeRepairProposal:
    event_default_broad = _is_default_broad_event(event)
    candidate_specificity = _candidate_specificity(proposal.proposed_node)
    context_valid = _is_informative_context(proposal.projected_current_context)
    applicability_grounded = proposal.applicability_status == "grounded"
    support_threshold_met = len(compatible_case_ids) >= V4_CONFIG.compatible_support_threshold
    eligible = (
        event_default_broad
        and proposal.candidate_source == "v5_node_repair"
        and candidate_specificity == "specific"
        and context_valid
        and (applicability_grounded or not require_grounded_applicability)
        and support_threshold_met
    )
    failed = []
    if not event_default_broad:
        failed.append("event_not_default_broad")
    if proposal.candidate_source != "v5_node_repair":
        failed.append("candidate_not_from_v5_node_repair")
    if candidate_specificity != "specific":
        failed.append(f"candidate_specificity_{candidate_specificity}")
    if not context_valid:
        failed.append("current_context_not_informative")
    if require_grounded_applicability and not applicability_grounded:
        failed.append(f"current_event_applicability_{proposal.applicability_status}")
    if not support_threshold_met:
        failed.append(
            "compatible_support_below_threshold_"
            f"{len(compatible_case_ids)}_lt_{V4_CONFIG.compatible_support_threshold}"
        )

    reason = (
        "eligible: default broad event plus repaired specific candidate with "
        "informative projection"
        + (
            ", grounded current-event applicability"
            if require_grounded_applicability
            else ""
        )
        + f", and compatible support {len(compatible_case_ids)}"
        if eligible
        else "ineligible: " + ", ".join(failed)
    )
    return proposal.model_copy(
        update={
            "specificity_recovery_evaluated": True,
            "specificity_recovery_eligible": eligible,
            "specificity_recovery_reason": reason,
            "candidate_specificity": candidate_specificity,
            "event_default_broad": event_default_broad,
            "event_guardrail_bypassed_for_candidate": False,
            "downstream_final_status": "pending" if eligible else "rejected",
            "downstream_final_reason": (
                "pending_v4_downstream_qualification"
                if eligible
                else "specificity_recovery_ineligible"
            ),
        }
    )


def _chain_with_specificity_recovered_nodes(
    chain: TransmissionChain,
    eligible_nodes: list[str],
    support_case_ids: dict[str, list[str]],
) -> TransmissionChain:
    node_supporting_case_ids = dict(chain.node_supporting_case_ids)
    node_evidence_levels = dict(chain.node_evidence_levels)
    affected_nodes = _dedupe([*chain.affected_nodes, *eligible_nodes])
    for node in eligible_nodes:
        node_supporting_case_ids[node] = support_case_ids.get(node, [])
        node_evidence_levels[node] = "case_grounded"
    supporting_case_ids = _dedupe(
        [
            *chain.supporting_case_ids,
            *[
                case_id
                for node in eligible_nodes
                for case_id in support_case_ids.get(node, [])
            ],
        ]
    )
    return chain.model_copy(
        update={
            "affected_nodes": affected_nodes,
            "node_supporting_case_ids": node_supporting_case_ids,
            "node_evidence_levels": node_evidence_levels,
            "supporting_case_ids": supporting_case_ids,
            "chain_steps": _dedupe([*chain.chain_steps, *eligible_nodes]),
            "channels": _dedupe([*chain.channels, *eligible_nodes]),
            "rationale": (
                f"{chain.rationale} V5 specificity recovery added only eligible "
                "repaired specific candidates after independent mechanism "
                "verification; the original event-level broad fallback was not "
                "globally reclassified."
            ),
        }
    )


def _is_default_broad_event(event: EventAnalysis) -> bool:
    return (
        event.event_type == "geopolitical_risk_event"
        and event.supply_chain_nodes == ["broad_etf"]
    )


def _candidate_specificity(node: str) -> str:
    canonical = nodes.normalize_node(node)
    if canonical is None:
        return "unknown"
    spec = nodes.NODE_REGISTRY.get(canonical)
    if spec is None:
        return "unknown"
    return "broad" if spec.category == nodes.Channel.BROAD else "specific"


def _is_informative_context(context: dict[str, str] | None) -> bool:
    if not context:
        return False
    return all(
        context.get(field) not in {"", "unknown", "unavailable", None}
        for field in [
            "shock_type",
            "constraint_type",
            "upstream_driver",
            "target_node_role",
            "canonical_context",
        ]
    )


def _record(
    state: AnalysisState,
    *,
    action: str,
    reason: str,
    before: str,
    after: str,
    candidate_nodes_added: list[str] | None = None,
    source_case_ids: list[str] | None = None,
    support_delta: dict[str, int] | None = None,
    latency_ms: int = 0,
) -> None:
    state.status = after  # type: ignore[assignment]
    state.trajectory.append(
        AgentAction(
            action=action,
            reason=reason,
            status_before=before,  # type: ignore[arg-type]
            status_after=after,  # type: ignore[arg-type]
            candidate_nodes_added=candidate_nodes_added or [],
            source_case_ids=source_case_ids or [],
            support_delta=support_delta or {},
            latency_ms=latency_ms,
        )
    )


def _result(
    final_report: FinalReport,
    state: AnalysisState,
    config: V5DiscoveryConfig,
) -> V5AnalysisResult:
    return V5AnalysisResult(
        final_report=final_report,
        architecture_version=config.architecture_version,
        repair_policy_version=config.repair_policy_version,
        repair_enabled=config.enable_node_repair,
        state=state,
    )


def _current_candidate_nodes(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    affected_nodes: list[str],
) -> list[str]:
    return _dedupe(
        [
            *event.supply_chain_nodes,
            *affected_nodes,
            *[
                node
                for case in retrieved_cases
                for node in case.supply_chain_nodes
            ],
        ]
    )


def _current_proposed_nodes(
    event: EventAnalysis,
    affected_nodes: list[str],
) -> list[str]:
    """Return nodes actually proposed for current-event verification."""

    return _dedupe([*event.supply_chain_nodes, *affected_nodes])


@contextmanager
def _projection_overrides(
    current_context_overrides: dict[str, dict[str, str]],
) -> Iterator[None]:
    """Temporarily expose V5 repaired-node contexts to frozen V4 verification."""

    if not current_context_overrides:
        yield
        return

    import src.agents.transmission_builder as transmission_builder

    original = transmission_builder.project_current_event_context

    def projected_context(event: EventAnalysis, node: str) -> dict[str, str] | None:
        return current_context_overrides.get(node) or original(event, node)

    transmission_builder.project_current_event_context = projected_context
    try:
        yield
    finally:
        transmission_builder.project_current_event_context = original


def _proposal_case_ids(proposals: list) -> list[str]:
    return _dedupe([case_id for proposal in proposals for case_id in proposal.source_case_ids])


def _elapsed_ms(start: float) -> int:
    return max(0, round((perf_counter() - start) * 1000))


def _terminal_status(final_report: FinalReport) -> str:
    """Classify a completed run by whether second-order ranking was emitted."""

    if any(
        result.ranking_scope == "ranked_second_order"
        for result in final_report.evidence_results
    ):
        return "RANKED"
    if final_report.evidence_results:
        return "RANKING_ABSTAIN"
    return "FULL_ABSTAIN"


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
