"""Smoke test for event analysis plus historical case retrieval."""

from __future__ import annotations

import json
from pathlib import Path

from src.agents.case_retriever import retrieve_cases
from src.agents.event_analyst import analyze_event


NEWS_TEXT = "Red Sea shipping routes face disruption due to escalating regional conflict."
HISTORICAL_CASES_PATH = Path(__file__).resolve().parents[1] / "data" / "historical_cases.json"


def main() -> None:
    """Analyze a sample event and print the top retrieved historical cases."""

    event = analyze_event(NEWS_TEXT)
    case_metadata = _load_case_metadata()

    print("EventAnalysis:")
    print(event.model_dump_json(indent=2))
    print()

    retrieved_cases = retrieve_cases(NEWS_TEXT, event, top_k=5)
    print("Top retrieved cases:")
    for case in retrieved_cases:
        metadata = case_metadata.get(case.case_id, {})
        print(f"case_id: {case.case_id}")
        print(f"similarity_score: {_similarity_score(case.relevance)}")
        print(f"event_name: {metadata.get('event_name', case.title)}")
        print(f"event_type: {metadata.get('event_type', 'n/a')}")
        print()


def _load_case_metadata() -> dict[str, dict]:
    """Load event names and types by case ID for display."""

    cases = json.loads(HISTORICAL_CASES_PATH.read_text(encoding="utf-8"))
    return {case["event_id"]: case for case in cases}


def _similarity_score(relevance: str | None) -> str:
    """Convert vector-store semantic distance text into a simple score."""

    if not relevance or not relevance.startswith("semantic_distance="):
        return "n/a"

    distance = float(relevance.split("=", maxsplit=1)[1])
    return f"{1 / (1 + distance):.4f}"


if __name__ == "__main__":
    main()
