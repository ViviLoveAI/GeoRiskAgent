"""Historical case retrieval agent placeholder."""

from src.vector_store import query_cases
from src.schemas import EventAnalysis, RetrievedCase


def retrieve_cases(
    news_text: str,
    event: EventAnalysis,
    top_k: int = 5,
) -> list[RetrievedCase]:
    """Retrieve historical cases relevant to the event.

    The retrieval query combines the raw news text with normalized event
    attributes. Retrieved cases are historical risk references only, not
    investment advice or price predictions.
    """

    query_parts = [
        news_text,
        event.event_type or "",
        " ".join(event.regions),
        " ".join(event.industries),
        " ".join(event.supply_chain_nodes),
        event.shock_direction or "",
    ]
    query_text = " ".join(part for part in query_parts if part.strip())

    return query_cases(query_text, top_k)
