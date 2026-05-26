"""Structured final report generator for the MVP."""

from src.schemas import (
    EventAnalysis,
    EvidenceResult,
    FinalReport,
    RetrievedCase,
    TransmissionChain,
)


EVIDENCE_LEVELS = ["historical_supported", "sector_proxy", "inference_only"]


def generate_report(
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    transmission_chain: TransmissionChain,
    evidence_results: list[EvidenceResult],
) -> FinalReport:
    """Generate a structured risk watchlist report.

    The report describes potential exposure and historically supported channels.
    It does not predict stock prices or provide investment advice.
    """

    event_summary = _event_summary(event)
    retrieved_case_summaries = _retrieved_case_summaries(retrieved_cases)
    secondary_asset_watchlist = _group_watchlist(evidence_results)
    risk_notes = _risk_notes(event, transmission_chain, evidence_results)
    disclaimer = (
        "This report is for geopolitical risk watchlist generation only. It "
        "identifies potential exposure candidates and historically supported "
        "channels, but it does not predict stock prices and is not investment "
        "advice."
    )

    return FinalReport(
        event=event,
        retrieved_cases=retrieved_cases,
        transmission_chain=transmission_chain,
        evidence_results=evidence_results,
        summary=event_summary,
        event_summary=event_summary,
        retrieved_case_summaries=retrieved_case_summaries,
        secondary_asset_watchlist=secondary_asset_watchlist,
        risk_notes=risk_notes,
        disclaimer=disclaimer,
        limitations=[
            "Evidence levels are deterministic MVP classifications.",
            "Retrieved historical cases are analogs, not forecasts.",
            "Mapped assets are risk watchlist candidates, not trading signals.",
        ],
    )


def _event_summary(event: EventAnalysis) -> str:
    """Create a concise event summary for the report."""

    regions = ", ".join(event.regions) if event.regions else "unspecified regions"
    nodes = ", ".join(event.supply_chain_nodes) if event.supply_chain_nodes else "unspecified nodes"
    return (
        f"{event.summary} Event type: {event.event_type}. "
        f"Primary regions: {regions}. Potential exposure nodes: {nodes}."
    )


def _retrieved_case_summaries(retrieved_cases: list[RetrievedCase]) -> list[dict[str, str]]:
    """Summarize retrieved historical cases."""

    return [
        {
            "case_id": case.case_id,
            "event_name": case.title,
            "event_type": case.event_type or "unknown",
            "summary": case.summary,
            "relevance": case.relevance or "not scored",
        }
        for case in retrieved_cases
    ]


def _group_watchlist(evidence_results: list[EvidenceResult]) -> dict[str, list[dict[str, object]]]:
    """Group candidate assets by evidence level."""

    grouped: dict[str, list[dict[str, object]]] = {level: [] for level in EVIDENCE_LEVELS}
    for result in evidence_results:
        grouped.setdefault(result.evidence_level, []).append(
            {
                "ticker": result.ticker,
                "asset_name": result.asset_name,
                "asset_type": result.asset.asset_type,
                "supply_chain_node": result.asset.supply_chain_node,
                "confidence": result.confidence,
                "supporting_case_ids": result.supporting_case_ids,
                "reason": result.reason,
            }
        )
    return grouped


def _risk_notes(
    event: EventAnalysis,
    transmission_chain: TransmissionChain,
    evidence_results: list[EvidenceResult],
) -> list[str]:
    """Create high-level qualitative risk notes."""

    strongest_count = sum(
        result.evidence_level == "historical_supported"
        for result in evidence_results
    )
    proxy_count = sum(result.evidence_level == "sector_proxy" for result in evidence_results)

    return [
        (
            "Risk transmission starts from "
            f"{event.shock_direction} and maps to nodes: "
            f"{', '.join(transmission_chain.affected_nodes) or 'none'}."
        ),
        (
            f"{strongest_count} candidates have historically supported channel "
            f"evidence; {proxy_count} are sector-proxy potential exposure items."
        ),
        transmission_chain.rationale,
    ]
