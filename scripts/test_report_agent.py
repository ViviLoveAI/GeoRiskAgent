"""End-to-end smoke test for structured report generation."""

from src.agents.case_retriever import retrieve_cases
from src.agents.event_analyst import analyze_event
from src.agents.evidence_agent import grade_evidence
from src.agents.market_mapper import map_assets
from src.agents.report_agent import generate_report
from src.agents.transmission_builder import build_transmission_chain


NEWS_TEXT = "Red Sea shipping routes face disruption due to escalating regional conflict."


def main() -> None:
    """Run the MVP workflow and print the final report."""

    event = analyze_event(NEWS_TEXT)
    retrieved_cases = retrieve_cases(NEWS_TEXT, event, top_k=3)
    transmission_chain = build_transmission_chain(event, retrieved_cases)
    candidate_assets = map_assets(event, transmission_chain)
    evidence_results = grade_evidence(
        event,
        candidate_assets,
        retrieved_cases,
        transmission_chain,
    )
    report = generate_report(
        event,
        retrieved_cases,
        transmission_chain,
        evidence_results,
    )

    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
