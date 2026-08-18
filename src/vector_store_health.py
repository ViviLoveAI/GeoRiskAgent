"""Health checks for the derived Chroma historical-case retrieval index."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

import chromadb

from src.config import HISTORICAL_CASES_PATH
from src.vector_store import CHROMA_DB_DIR, COLLECTION_NAME, build_index, _collection_names


class VectorStoreUnavailableError(RuntimeError):
    """Raised when the derived Chroma retrieval index is unavailable."""


@dataclass(frozen=True)
class VectorStoreHealth:
    """Lightweight health summary for the Chroma retrieval index."""

    chroma_version: str
    persistence_path: str
    collection_name: str
    collection_count: int | None
    healthy: bool
    message: str


def validate_vector_store(*, require_non_empty: bool = True) -> VectorStoreHealth:
    """Validate the derived Chroma retrieval index without rebuilding it."""

    sqlite_path = CHROMA_DB_DIR / "chroma.sqlite3"
    if not CHROMA_DB_DIR.exists():
        return _health(None, False, "Persistence directory does not exist.")
    if sqlite_path.exists() and sqlite_path.stat().st_size == 0:
        return _health(
            None,
            False,
            "Chroma SQLite file is empty; index is invalid or partially initialized.",
        )

    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
        names = _collection_names(client)
        if COLLECTION_NAME not in names:
            return _health(None, False, "Expected collection is missing.")
        collection = client.get_collection(COLLECTION_NAME)
        count = collection.count()
        if require_non_empty and count == 0:
            return _health(count, False, "Expected collection is empty.")
        return _health(count, True, "OK")
    except Exception as exc:
        return _health(None, False, f"{type(exc).__name__}: {exc}")


def assert_vector_store_ready() -> VectorStoreHealth:
    """Return health details or raise when retrieval index is unavailable."""

    health = validate_vector_store()
    if not health.healthy:
        raise VectorStoreUnavailableError(health.message)
    return health


def _health(collection_count: int | None, healthy: bool, message: str) -> VectorStoreHealth:
    """Build a health record with consistent index identity fields."""

    return VectorStoreHealth(
        chroma_version=chromadb.__version__,
        persistence_path=str(CHROMA_DB_DIR),
        collection_name=COLLECTION_NAME,
        collection_count=collection_count,
        healthy=healthy,
        message=message,
    )


def _source_case_count() -> int:
    """Return the authoritative historical-case source count."""

    cases = json.loads(HISTORICAL_CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("historical_cases.json must contain a list of cases.")
    return len(cases)


def main() -> None:
    """CLI utility for Chroma index health and rebuild operations."""

    parser = argparse.ArgumentParser(description="Inspect or rebuild the GeoRisk Chroma index.")
    parser.add_argument("--health", action="store_true", help="Print vector-store health.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the Chroma index.")
    args = parser.parse_args()

    if args.rebuild:
        source_count = _source_case_count()
        build_index(force_rebuild=True)
        health = validate_vector_store()
        print(f"source_case_count: {source_count}")
        print(f"indexed_document_count: {health.collection_count}")
        print(f"collection_name: {health.collection_name}")
        print(f"persistence_path: {health.persistence_path}")
        if not health.healthy:
            raise SystemExit(f"Health: ERROR ({health.message})")
        print("Health: OK")
        return

    health = validate_vector_store()
    print(f"Chroma version: {health.chroma_version}")
    print(f"Persistence path: {health.persistence_path}")
    print(f"Collection: {health.collection_name}")
    print(f"Collection count: {health.collection_count}")
    print(f"Health: {'OK' if health.healthy else 'ERROR'}")
    if not health.healthy:
        print(f"Message: {health.message}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
