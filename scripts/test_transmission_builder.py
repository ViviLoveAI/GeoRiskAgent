"""Smoke test for deterministic transmission-chain building."""

from src.agents.case_retriever import retrieve_cases
from src.agents.event_analyst import analyze_event
from src.agents.transmission_builder import build_transmission_chain


NEWS_TEXT = "Red Sea shipping routes face disruption due to escalating regional conflict."


def main() -> None:
    """Analyze, retrieve cases, build a chain, and print the key fields."""

    event = analyze_event(NEWS_TEXT)
    retrieved_cases = retrieve_cases(NEWS_TEXT, event, top_k=3)
    transmission_chain = build_transmission_chain(event, retrieved_cases)

    print("chain_steps:")
    for step in transmission_chain.chain_steps:
        print(f"- {step}")

    print("\naffected_nodes:")
    for node in transmission_chain.affected_nodes:
        print(f"- {node}")

    print("\nsupporting_case_ids:")
    for case_id in transmission_chain.supporting_case_ids:
        print(f"- {case_id}")

    print("\nrationale:")
    print(transmission_chain.rationale)


if __name__ == "__main__":
    main()
