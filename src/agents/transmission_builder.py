"""Deterministic transmission-chain builder for the MVP."""

from src.schemas import EventAnalysis, RetrievedCase, TransmissionChain


def build_transmission_chain(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
) -> TransmissionChain:
    """Build a simple risk transmission chain from event and case context.

    The result describes potential exposure and watchlist candidates only. It
    does not predict stock prices or provide investment advice.
    """

    chain_steps = _dedupe(
        [
            event.shock_direction,
            *event.supply_chain_nodes,
            *_case_chain_steps(retrieved_cases),
        ]
    )
    supporting_case_ids = [case.case_id for case in retrieved_cases]

    return TransmissionChain(
        chain_steps=chain_steps,
        affected_nodes=list(event.supply_chain_nodes),
        supporting_case_ids=supporting_case_ids,
        rationale=(
            "This deterministic MVP chain links the event shock direction to "
            "normalized supply-chain nodes, then grounds the risk transmission "
            "path in retrieved historical cases. Assets mapped later should be "
            "treated as potential exposure watchlist candidates, not trading "
            "signals."
        ),
        channels=chain_steps,
        assumptions=[
            "The event attributes were produced by deterministic keyword rules.",
            "Retrieved historical cases provide analogs, not proof of identical outcomes.",
        ],
        limitations=[
            "The chain is qualitative and does not forecast prices.",
            "The chain is not investment advice.",
        ],
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
