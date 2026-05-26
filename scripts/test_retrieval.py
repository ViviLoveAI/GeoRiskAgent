"""Smoke test for semantic historical case retrieval."""

from __future__ import annotations

import json

from src.vector_store import (
    COLLECTION_NAME,
    _embed_texts,
    _get_client,
    build_index,
)


QUERY_TEXT = "Red Sea shipping routes face disruption due to escalating regional conflict."


def main() -> None:
    """Build or load the index and print the top retrieved cases."""

    build_index()
    collection = _get_client().get_collection(COLLECTION_NAME)
    query_embedding = _embed_texts([QUERY_TEXT])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5,
        include=["distances", "metadatas"],
    )

    ids = results.get("ids", [[]])[0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    for rank, (case_id, distance, metadata) in enumerate(
        zip(ids, distances, metadatas, strict=False),
        start=1,
    ):
        similarity_score = 1 / (1 + distance)
        print(f"{rank}. case_id: {case_id}")
        print(f"   similarity_score: {similarity_score:.4f}")
        print(f"   event_name: {metadata.get('event_name', 'n/a')}")
        print(f"   event_type: {metadata.get('event_type', 'n/a')}")
        print(f"   matched_metadata: {_format_metadata(metadata)}")


def _format_metadata(metadata: dict) -> str:
    """Format useful metadata fields for display."""

    fields = {
        "date": metadata.get("date"),
        "regions": _parse_json_list(metadata.get("regions")),
        "countries": _parse_json_list(metadata.get("countries")),
        "industries": _parse_json_list(metadata.get("industries")),
        "supply_chain_nodes": _parse_json_list(metadata.get("supply_chain_nodes")),
    }
    return json.dumps(fields, ensure_ascii=True)


def _parse_json_list(value: str | None) -> list[str]:
    """Parse metadata lists stored as JSON strings."""

    if value is None:
        return []
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        return []
    return parsed


if __name__ == "__main__":
    main()
