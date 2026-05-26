"""Smoke test for deterministic evidence grading."""

from src.agents.case_retriever import retrieve_cases
from src.agents.event_analyst import analyze_event
from src.agents.evidence_agent import grade_evidence
from src.agents.market_mapper import map_assets
from src.agents.transmission_builder import build_transmission_chain


NEWS_TEXT = "Red Sea shipping routes face disruption due to escalating regional conflict."


def main() -> None:
    """Run event analysis through evidence grading and print key fields."""

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

    for result in evidence_results:
        print(f"ticker: {result.ticker}")
        print(f"asset_name: {result.asset_name}")
        print(f"evidence_level: {result.evidence_level}")
        print(f"confidence: {result.confidence:.2f}")
        print(f"supporting_case_ids: {result.supporting_case_ids}")
        print(f"reason: {result.reason}")
        print()


if __name__ == "__main__":
    main()
