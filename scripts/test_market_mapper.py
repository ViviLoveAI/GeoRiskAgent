"""Smoke test for market exposure mapping."""

from src.agents.case_retriever import retrieve_cases
from src.agents.event_analyst import analyze_event
from src.agents.market_mapper import map_assets
from src.agents.transmission_builder import build_transmission_chain


NEWS_TEXT = "Red Sea shipping routes face disruption due to escalating regional conflict."


def main() -> None:
    """Analyze, retrieve, build a chain, and print mapped candidate assets."""

    event = analyze_event(NEWS_TEXT)
    retrieved_cases = retrieve_cases(NEWS_TEXT, event, top_k=3)
    transmission_chain = build_transmission_chain(event, retrieved_cases)
    candidate_assets = map_assets(event, transmission_chain)

    for asset in candidate_assets:
        print(f"ticker: {asset.ticker}")
        print(f"asset_name: {asset.asset_name}")
        print(f"asset_type: {asset.asset_type}")
        print(f"supply_chain_node: {asset.supply_chain_node}")
        print(f"notes: {asset.notes}")
        print()


if __name__ == "__main__":
    main()
