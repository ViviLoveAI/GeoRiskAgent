"""Deterministic transmission-chain builder for the MVP.

The builder starts from the supply-chain nodes attached to the event itself
(first-order / directly implicated nodes) and expands to second-order nodes
only when a node that is absent from the event is corroborated by multiple
independent historical analogs. This keeps single-case coincidences out of the
affected-node set, and keeps the presented transmission narrative scoped to the
same cases that actually support the accepted nodes.
"""

from src.config import USE_MECHANISM_COMPATIBLE_SUPPORT
from src.mechanism_context import support_diagnostics
from src.schemas import EventAnalysis, RetrievedCase, TransmissionChain
from src.transmission_context_store import (
    load_historical_contexts,
    missing_context,
    project_current_event_context,
)


# --- Tunable transmission parameters ---------------------------------------

MIN_CASE_SUPPORT_FOR_SECOND_ORDER = 2
"""Minimum number of independent retrieved cases in which a node must appear
before it is accepted as a second-order transmission target.

Rationale: a node that appears in only a single retrieved case cannot be
distinguished from a coincidence specific to that one historical event.
Requiring the node to recur across at least two independent cases is the
minimum condition for treating it as a repeatable transmission pattern rather
than a one-off. n=2 is a lower bound on "independent corroboration"; it is not
a value that has been shown to be optimal.

This is an empirical default chosen for the current case base (~50 cases). It
should be re-calibrated once CAR-based validation provides ground-truth
feedback on the second-order hit rate versus recall trade-off (see README
limitations). It is exposed as a named constant so that calibration only
touches this value, not the expansion logic.
"""


def build_transmission_chain(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    *,
    use_mechanism_compatible_support: bool | None = None,
) -> TransmissionChain:
    """Build a risk transmission chain from event and case context.

    The result describes potential exposure and watchlist candidates only. It
    does not predict stock prices or provide investment advice.
    """

    if use_mechanism_compatible_support is None:
        use_mechanism_compatible_support = USE_MECHANISM_COMPATIBLE_SUPPORT

    affected_nodes, node_supporting_case_ids, node_evidence_levels = (
        _expanded_affected_nodes(
            event,
            retrieved_cases,
            use_mechanism_compatible_support=use_mechanism_compatible_support,
        )
    )

    # Scope every downstream artifact to the cases that actually share an
    # accepted node. A case whose nodes were all rejected (e.g. single-case
    # nodes below the support threshold) and that shares no event node must not
    # contribute its narrative or its id to the presented transmission, because
    # nothing it offered survived into ``affected_nodes``.
    contributing_cases = _contributing_cases(retrieved_cases, affected_nodes)
    supporting_case_ids = [case.case_id for case in contributing_cases]

    chain_steps = _dedupe(
        [
            event.shock_direction,
            *affected_nodes,
            *_case_chain_steps(contributing_cases),
        ]
    )

    return TransmissionChain(
        chain_steps=chain_steps,
        affected_nodes=affected_nodes,
        node_supporting_case_ids=node_supporting_case_ids,
        node_evidence_levels=node_evidence_levels,
        supporting_case_ids=supporting_case_ids,
        rationale=(
            "This deterministic chain starts from the event's own supply-chain "
            "nodes (first-order) and expands to second-order affected nodes "
            "only when they recur across at least "
            f"{MIN_CASE_SUPPORT_FOR_SECOND_ORDER} independent retrieved "
            "historical analogs, so that single-case co-occurrence is not "
            "treated as sufficient evidence. The transmission narrative and the "
            "supporting-case list are scoped to the cases that actually support "
            "an accepted node, so the presented story matches the nodes that "
            "were accepted. Assets mapped later should be treated as potential "
            "exposure watchlist candidates, not trading signals."
        ),
        channels=chain_steps,
        assumptions=[
            (
                "The event attributes were produced by either the rule-based "
                "analyzer or the optional validated LLM analyzer."
            ),
            "Retrieved historical cases provide analogs, not proof of identical outcomes.",
            (
                "Without retrieval similarity scores, single-case nodes are "
                "excluded from second-order expansion unless they are already "
                "event nodes."
            ),
        ],
        limitations=[
            "The chain is qualitative and does not forecast prices.",
            "The chain is not investment advice.",
            (
                "Second-order expansion is conservative: it may miss valid "
                "transmission targets that happen to appear in only one "
                "retrieved case."
            ),
            (
                "The second-order support threshold is an unvalidated empirical "
                "default and should be calibrated against CAR-based ground "
                "truth."
            ),
            (
                "Future work should pass retrieval similarity or distance into "
                "RetrievedCase to support high-similarity single-case analog "
                "expansion."
            ),
            (
                "Node-level support is captured, but individual chain steps are "
                "not yet grounded step-by-step to specific cases."
            ),
        ],
    )


def _expanded_affected_nodes(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    *,
    use_mechanism_compatible_support: bool = False,
) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    """Expand event nodes using repeated historical-analog support.

    Returns the accepted affected nodes, a per-node map of the case ids that
    support each node, and a per-node evidence level. First-order nodes come
    from the event itself and are labelled ``event_node``; second-order nodes
    are accepted only when supported by at least
    ``MIN_CASE_SUPPORT_FOR_SECOND_ORDER`` distinct cases and are labelled
    ``case_grounded``.
    """

    event_nodes = _dedupe(event.supply_chain_nodes)
    node_support = (
        _mechanism_compatible_node_support(event, retrieved_cases)
        if use_mechanism_compatible_support
        else _node_support_from_cases(retrieved_cases)
    )

    accepted_nodes: list[str] = [*event_nodes]
    support_map: dict[str, list[str]] = {
        node: node_support.get(node, []) for node in event_nodes
    }
    evidence_levels: dict[str, str] = {node: "event_node" for node in event_nodes}

    # For a default limited-support event no specific geopolitical channel was
    # identified, so second-order expansion is not attempted.
    if _is_default_limited_support_event(event):
        return accepted_nodes, support_map, evidence_levels

    event_node_set = set(event_nodes)
    accepted_set = set(accepted_nodes)
    for node, supporting_case_ids in node_support.items():
        if node in event_node_set or node in accepted_set:
            continue
        if len(supporting_case_ids) >= MIN_CASE_SUPPORT_FOR_SECOND_ORDER:
            accepted_nodes.append(node)
            accepted_set.add(node)
            support_map[node] = supporting_case_ids
            evidence_levels[node] = "case_grounded"

    return accepted_nodes, support_map, evidence_levels


def _node_support_from_cases(
    retrieved_cases: list[RetrievedCase],
) -> dict[str, list[str]]:
    """Map each retrieved supply-chain node to the case ids that mention it.

    Each case contributes at most once per node, so the length of a node's list
    is the number of distinct cases supporting it.
    """

    node_support: dict[str, list[str]] = {}
    for case in retrieved_cases:
        seen_case_nodes: set[str] = set()
        for node in case.supply_chain_nodes:
            if not node or node in seen_case_nodes:
                continue
            seen_case_nodes.add(node)
            node_support.setdefault(node, []).append(case.case_id)
    return node_support


def _mechanism_compatible_node_support(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
) -> dict[str, list[str]]:
    """Return per-node support from mechanism-compatible historical contexts."""

    raw_support = _node_support_from_cases(retrieved_cases)
    historical_contexts = load_historical_contexts()
    compatible_support: dict[str, list[str]] = {}

    for node, case_ids in raw_support.items():
        current_context = project_current_event_context(event, node)
        supporting_contexts = [
            {
                "case_id": case_id,
                **historical_contexts.get((case_id, node), missing_context(node)),
            }
            for case_id in case_ids
        ]
        diagnostics = support_diagnostics(current_context, supporting_contexts)
        if diagnostics["compatible_case_ids"]:
            compatible_support[node] = diagnostics["compatible_case_ids"]

    return compatible_support


def _contributing_cases(
    retrieved_cases: list[RetrievedCase],
    affected_nodes: list[str],
) -> list[RetrievedCase]:
    """Return the retrieved cases that share at least one accepted node.

    These are the only cases whose narrative and id belong in the presented
    transmission, because they are the cases that actually support a node that
    survived into ``affected_nodes``.
    """

    accepted = set(affected_nodes)
    return [
        case
        for case in retrieved_cases
        if accepted.intersection(case.supply_chain_nodes)
    ]


def _is_default_limited_support_event(event: EventAnalysis) -> bool:
    """Return true when the analyzer found no specific geopolitical channel."""

    return (
        event.event_type == "geopolitical_risk_event"
        and event.supply_chain_nodes == ["broad_etf"]
    )


def _case_chain_steps(retrieved_cases: list[RetrievedCase]) -> list[str]:
    """Use historical transmission-chain fields when available."""

    steps: list[str] = []
    for case in retrieved_cases:
        if case.transmission_chain:
            steps.extend(case.transmission_chain)
        else:
            steps.append(f"historical analog: {case.title}")
    return steps


def _dedupe(values: list[str]) -> list[str]:
    """Preserve order while removing empty strings and duplicates."""

    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
