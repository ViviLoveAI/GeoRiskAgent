"""Required local dependency checks and an optional LLM reachability probe."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pandas as pd

from src.agents.market_mapper import validate_asset_mapping_schema
from src.config import (
    ASSET_MAPPING_PATH,
    HISTORICAL_CASES_PATH,
    LLM_EVENT_ANALYST_MAX_RETRIES,
    LLM_EVENT_ANALYST_MODEL,
    LLM_EVENT_ANALYST_TIMEOUT_SECONDS,
)


REQUIRED_CASE_FIELDS = {
    "event_id",
    "date",
    "event_name",
    "event_type",
    "regions",
    "industries",
    "supply_chain_nodes",
    "summary",
    "transmission_chain",
    "retrieval_text",
}
CASE_LIST_FIELDS = {
    "regions",
    "industries",
    "supply_chain_nodes",
    "transmission_chain",
}


@dataclass(frozen=True)
class DependencyHealth:
    """Safe health result for one required or optional dependency."""

    name: str
    status: str
    healthy: bool
    required: bool
    records: int | None = None
    message: str | None = None


def validate_historical_cases() -> DependencyHealth:
    """Validate the authoritative historical-case JSON schema and contents."""

    try:
        payload = json.loads(HISTORICAL_CASES_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not payload:
            raise ValueError("historical_cases.json must contain a non-empty list.")
        seen_ids: set[str] = set()
        for index, case in enumerate(payload):
            if not isinstance(case, dict):
                raise ValueError(f"case at index {index} must be an object.")
            missing = REQUIRED_CASE_FIELDS - set(case)
            if missing:
                raise ValueError(
                    f"case at index {index} is missing fields: {sorted(missing)}"
                )
            event_id = case["event_id"]
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError(f"case at index {index} has an invalid event_id.")
            if event_id in seen_ids:
                raise ValueError(f"duplicate event_id: {event_id}")
            seen_ids.add(event_id)
            invalid_lists = [field for field in CASE_LIST_FIELDS if not isinstance(case[field], list)]
            if invalid_lists:
                raise ValueError(
                    f"case {event_id} has non-list fields: {sorted(invalid_lists)}"
                )
        return DependencyHealth(
            name="historical_case_kb",
            status="ready",
            healthy=True,
            required=True,
            records=len(payload),
        )
    except Exception as exc:
        return DependencyHealth(
            name="historical_case_kb",
            status="unavailable",
            healthy=False,
            required=True,
            message=f"{type(exc).__name__}: {exc}",
        )


def validate_asset_mapping() -> DependencyHealth:
    """Validate the authoritative asset-mapping CSV and controlled schema."""

    try:
        mapping = pd.read_csv(ASSET_MAPPING_PATH)
        if mapping.empty:
            raise ValueError("asset_mapping.csv must not be empty.")
        validate_asset_mapping_schema(mapping)
        return DependencyHealth(
            name="asset_mapping",
            status="ready",
            healthy=True,
            required=True,
            records=len(mapping),
        )
    except Exception as exc:
        return DependencyHealth(
            name="asset_mapping",
            status="unavailable",
            healthy=False,
            required=True,
            message=f"{type(exc).__name__}: {exc}",
        )


def llm_configuration_health() -> DependencyHealth:
    """Report optional LLM configuration without making a network request."""

    if not os.getenv("OPENAI_API_KEY"):
        return DependencyHealth(
            name="llm_event_analyst",
            status="disabled",
            healthy=True,
            required=False,
            message="OPENAI_API_KEY is not configured; deterministic fallback remains available.",
        )
    return DependencyHealth(
        name="llm_event_analyst",
        status="configured_unprobed",
        healthy=True,
        required=False,
        message="Use /health/deep for an explicit endpoint reachability probe.",
    )


def probe_llm_endpoint() -> DependencyHealth:
    """Actively verify optional LLM model access without generating tokens."""

    configured = llm_configuration_health()
    if configured.status == "disabled":
        return configured
    try:
        from openai import OpenAI

        client = OpenAI(
            timeout=LLM_EVENT_ANALYST_TIMEOUT_SECONDS,
            max_retries=LLM_EVENT_ANALYST_MAX_RETRIES,
        )
        client.models.retrieve(LLM_EVENT_ANALYST_MODEL)
        return DependencyHealth(
            name="llm_event_analyst",
            status="reachable",
            healthy=True,
            required=False,
        )
    except Exception as exc:
        return DependencyHealth(
            name="llm_event_analyst",
            status="unreachable",
            healthy=False,
            required=False,
            message=f"{type(exc).__name__}: {exc}",
        )
