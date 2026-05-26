"""Semantic retrieval over historical geopolitical risk cases.

Historical cases are loaded from ``data/historical_cases.json`` and indexed
with ChromaDB using the ``retrieval_text`` field as document text. Retrieved
cases are risk-analysis references only; this module does not provide
investment advice or price predictions.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import warnings
from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer
from transformers import logging as transformers_logging

from src.config import HISTORICAL_CASES_PATH, PROJECT_ROOT
from src.schemas import RetrievedCase


COLLECTION_NAME = "georisk_historical_cases"
MODEL_NAME = "all-MiniLM-L6-v2"
CHROMA_DB_DIR = PROJECT_ROOT / "chroma_db"

_embedding_model: SentenceTransformer | None = None


def build_index(force_rebuild: bool = False) -> None:
    """Create or refresh the persistent ChromaDB historical-case index.

    The index stores each case's ``retrieval_text`` as the searchable document
    and keeps core case attributes in metadata for later inspection.
    """

    cases = _load_historical_cases()
    client = _get_client()

    if force_rebuild:
        if COLLECTION_NAME in _collection_names(client):
            client.delete_collection(COLLECTION_NAME)

    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    if not cases:
        return

    documents = [case["retrieval_text"] for case in cases]
    ids = [case["event_id"] for case in cases]
    embeddings = _embed_texts(documents)
    metadatas = [_case_metadata(case) for case in cases]

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def query_cases(query_text: str, top_k: int = 5) -> list[RetrievedCase]:
    """Return the most semantically similar historical cases for a query."""

    if not query_text.strip():
        raise ValueError("query_text must not be empty.")
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    cases_by_id = {case["event_id"]: case for case in _load_historical_cases()}
    collection = _get_client().get_or_create_collection(name=COLLECTION_NAME)

    if collection.count() == 0:
        build_index()
        collection = _get_client().get_or_create_collection(name=COLLECTION_NAME)

    query_embedding = _embed_texts([query_text])[0]
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, max(1, collection.count())),
        include=["distances", "metadatas"],
    )

    retrieved: list[RetrievedCase] = []
    result_ids = results.get("ids", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for event_id, distance in zip(result_ids, distances, strict=False):
        case = cases_by_id.get(event_id)
        if case is None:
            continue

        retrieved.append(
            RetrievedCase(
                case_id=case["event_id"],
                title=case["event_name"],
                summary=case["summary"],
                event_type=case.get("event_type"),
                transmission_chain=case.get("transmission_chain", []),
                relevance=f"semantic_distance={distance:.4f}",
            )
        )

    return retrieved


def _get_client() -> chromadb.PersistentClient:
    """Return the persistent local ChromaDB client."""

    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DB_DIR))


def _collection_names(client: chromadb.PersistentClient) -> set[str]:
    """Return collection names across supported ChromaDB versions."""

    names: set[str] = set()
    for collection in client.list_collections():
        if isinstance(collection, str):
            names.add(collection)
        else:
            names.add(collection.name)
    return names


def _get_embedding_model() -> SentenceTransformer:
    """Load the sentence-transformers model lazily."""

    global _embedding_model
    if _embedding_model is None:
        _embedding_model = _load_sentence_transformer_quietly()
    return _embedding_model


def _load_sentence_transformer_quietly() -> SentenceTransformer:
    """Load the embedding model while hiding non-fatal model-load chatter."""

    noisy_loggers = [
        "sentence_transformers",
        "transformers",
        "huggingface_hub",
    ]
    previous_levels = {
        logger_name: logging.getLogger(logger_name).level
        for logger_name in noisy_loggers
    }
    previous_transformers_verbosity = transformers_logging.get_verbosity()

    try:
        for logger_name in noisy_loggers:
            logging.getLogger(logger_name).setLevel(logging.ERROR)
        transformers_logging.set_verbosity_error()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", module="sentence_transformers")
                warnings.filterwarnings("ignore", module="transformers")
                warnings.filterwarnings("ignore", message=".*UNEXPECTED.*")
                return SentenceTransformer(MODEL_NAME)
    finally:
        transformers_logging.set_verbosity(previous_transformers_verbosity)
        for logger_name, level in previous_levels.items():
            logging.getLogger(logger_name).setLevel(level)


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts with the configured sentence-transformers model."""

    embeddings = _get_embedding_model().encode(texts, convert_to_numpy=True)
    return embeddings.tolist()


def _load_historical_cases(path: Path = HISTORICAL_CASES_PATH) -> list[dict[str, Any]]:
    """Load historical case records from the project data file."""

    with path.open(encoding="utf-8") as file:
        cases = json.load(file)

    if not isinstance(cases, list):
        raise ValueError("historical_cases.json must contain a list of cases.")

    return cases


def _case_metadata(case: dict[str, Any]) -> dict[str, str]:
    """Return Chroma-compatible scalar metadata for a historical case."""

    return {
        "event_id": str(case["event_id"]),
        "event_name": str(case["event_name"]),
        "event_type": str(case["event_type"]),
        "date": str(case["date"]),
        "regions": json.dumps(case.get("regions", [])),
        "countries": json.dumps(case.get("countries", [])),
        "industries": json.dumps(case.get("industries", [])),
        "supply_chain_nodes": json.dumps(case.get("supply_chain_nodes", [])),
    }
