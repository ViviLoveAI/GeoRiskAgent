"""Deterministic bounded node discovery repair for GeoRisk V5.

This module proposes missing nodes only from V4 historical mechanism context
already associated with retrieved cases. Proposals are discovery candidates;
they do not approve evidence and they do not generate tickers.
"""

from __future__ import annotations

from collections import defaultdict

from src import nodes
from src.mechanism_context import support_diagnostics
from src.schemas import EventAnalysis, RetrievedCase
from src.transmission_context_store import (
    load_historical_contexts,
    missing_context,
    project_current_event_context,
)
from src.v5_config import V5DiscoveryConfig
from src.v5_models import EvidenceDiagnosis, NodeRepairProposal


def diagnose_evidence_state(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    current_proposed_nodes: list[str],
    compatible_support: dict[str, int],
    config: V5DiscoveryConfig,
) -> tuple[EvidenceDiagnosis, list[NodeRepairProposal]]:
    """Classify the state and return repair proposals for a node gap."""

    if any(count >= 2 for count in compatible_support.values()):
        return "ENOUGH_EVIDENCE", []
    if not retrieved_cases:
        return "INSUFFICIENT_CONTEXT", []

    proposals = propose_node_repairs(
        event,
        retrieved_cases,
        current_proposed_nodes,
        max_candidates=config.max_new_candidate_nodes,
    )
    if proposals:
        return "NODE_GAP", proposals
    return "NO_QUALIFIED_EVIDENCE", []


def propose_node_repairs(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    current_proposed_nodes: list[str],
    *,
    max_candidates: int,
) -> list[NodeRepairProposal]:
    """Propose bounded candidate nodes from retrieved historical contexts."""

    if max_candidates <= 0:
        return []

    already_proposed = {
        normalized
        for node in current_proposed_nodes
        if (normalized := nodes.normalize_node(node))
    }
    contexts_by_node = historical_evidence_contexts_by_node(retrieved_cases)

    proposals: list[NodeRepairProposal] = []
    for node in sorted(
        contexts_by_node,
        key=lambda candidate: (
            -len({context["case_id"] for context in contexts_by_node[candidate]}),
            candidate,
        ),
    ):
        if node in already_proposed:
            continue
        current_context = project_current_event_context(event, node)
        diagnostics = (
            support_diagnostics(current_context, contexts_by_node[node])
            if current_context is not None
            else {
                "compatible_case_ids": [],
                "compatible_support_count": 0,
            }
        )
        source_case_ids = (
            diagnostics["compatible_case_ids"]
            or [context["case_id"] for context in contexts_by_node[node]]
        )
        if not source_case_ids:
            continue

        proposals.append(
            NodeRepairProposal(
                proposed_node=node,
                reason=(
                    "appears in retrieved historical mechanism evidence and is "
                    "missing from the current event proposal"
                ),
                source_case_ids=source_case_ids,
                historical_support_count=len({context["case_id"] for context in contexts_by_node[node]}),
                current_context_available=current_context is not None,
                compatible_support_count=diagnostics["compatible_support_count"],
            )
        )
        if len(proposals) >= max_candidates:
            break

    return proposals


def historical_evidence_nodes(retrieved_cases: list[RetrievedCase]) -> list[str]:
    """Return canonical nodes observed in retrieved payloads or sidecar contexts."""

    return sorted(historical_evidence_contexts_by_node(retrieved_cases))


def historical_evidence_contexts_by_node(
    retrieved_cases: list[RetrievedCase],
) -> dict[str, list[dict[str, str]]]:
    """Collect historical evidence contexts by canonical node for retrieved cases."""

    retrieved_case_ids = {case.case_id for case in retrieved_cases}
    historical_contexts = load_historical_contexts()
    contexts_by_node: dict[str, list[dict[str, str]]] = defaultdict(list)

    for case in retrieved_cases:
        for raw_node in case.supply_chain_nodes:
            node = nodes.normalize_node(raw_node)
            if not node or node == "broad_etf":
                continue
            context = historical_contexts.get((case.case_id, node))
            if not _is_informative_context(context):
                continue
            contexts_by_node[node].append({"case_id": case.case_id, **context})

    for (case_id, raw_node), context in historical_contexts.items():
        if case_id not in retrieved_case_ids:
            continue
        node = nodes.normalize_node(raw_node)
        if not node or node == "broad_etf":
            continue
        if not _is_informative_context(context):
            continue
        existing_case_ids = {row["case_id"] for row in contexts_by_node[node]}
        if case_id not in existing_case_ids:
            contexts_by_node[node].append({"case_id": case_id, **context})

    return dict(contexts_by_node)


def repaired_retrieved_cases(
    retrieved_cases: list[RetrievedCase],
    proposals: list[NodeRepairProposal],
) -> list[RetrievedCase]:
    """Return retrieved cases augmented with proposed nodes and provenance."""

    proposal_by_case: dict[str, list[str]] = defaultdict(list)
    for proposal in proposals:
        for case_id in proposal.source_case_ids:
            proposal_by_case[case_id].append(proposal.proposed_node)

    repaired: list[RetrievedCase] = []
    for case in retrieved_cases:
        added_nodes = proposal_by_case.get(case.case_id, [])
        if not added_nodes:
            repaired.append(case)
            continue
        repaired.append(
            case.model_copy(
                update={
                    "supply_chain_nodes": _dedupe(
                        [*case.supply_chain_nodes, *added_nodes]
                    )
                }
            )
        )
    return repaired


def compatible_support_counts(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    candidate_nodes: list[str],
    current_context_overrides: dict[str, dict[str, str]] | None = None,
) -> dict[str, int]:
    """Return V4-compatible support counts for candidate nodes."""

    return {
        node: len(case_ids)
        for node, case_ids in compatible_support_case_ids(
            event,
            retrieved_cases,
            candidate_nodes,
            current_context_overrides=current_context_overrides,
        ).items()
    }


def compatible_support_case_ids(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    candidate_nodes: list[str],
    current_context_overrides: dict[str, dict[str, str]] | None = None,
) -> dict[str, list[str]]:
    """Return V4-compatible supporting case ids for candidate nodes."""

    historical_contexts = load_historical_contexts()
    current_context_overrides = current_context_overrides or {}
    support: dict[str, list[str]] = {}
    for node in candidate_nodes:
        current_context = current_context_overrides.get(node) or project_current_event_context(event, node)
        if current_context is None:
            support[node] = []
            continue
        case_ids = [
            case.case_id
            for case in retrieved_cases
            if node in case.supply_chain_nodes
        ]
        supporting_contexts = [
            {
                "case_id": case_id,
                **historical_contexts.get((case_id, node), missing_context(node)),
            }
            for case_id in case_ids
        ]
        diagnostics = support_diagnostics(current_context, supporting_contexts)
        support[node] = diagnostics["compatible_case_ids"]
    return support


def _dedupe(values: list[str]) -> list[str]:
    """Preserve order while removing empty strings and duplicates."""

    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _is_informative_context(context: dict[str, str] | None) -> bool:
    """Return true only for sidecar contexts with mechanism fields populated."""

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
