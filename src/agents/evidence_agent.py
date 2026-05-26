"""Deterministic evidence grading for mapped risk exposure candidates."""

from __future__ import annotations

import json
import re
from typing import Any

from src.config import HISTORICAL_CASES_PATH
from src.schemas import (
    CandidateAsset,
    EventAnalysis,
    EvidenceResult,
    RetrievedCase,
    TransmissionChain,
)


GENERIC_TICKER_TERMS = {"LNG"}


def grade_evidence(
    event: EventAnalysis,
    candidate_assets: list[CandidateAsset],
    retrieved_cases: list[RetrievedCase],
    transmission_chain: TransmissionChain,
) -> list[EvidenceResult]:
    """Grade evidence for candidate assets using deterministic MVP rules.

    Results describe potential exposure candidates and risk watchlist items
    only. They do not predict stock prices or provide investment advice.
    """

    historical_cases = _load_cases_by_id()
    enriched_cases = [
        historical_cases.get(case.case_id, _case_from_retrieved(case))
        for case in retrieved_cases
    ]

    return [
        _grade_asset(asset, event, enriched_cases, transmission_chain)
        for asset in candidate_assets
    ]


def _grade_asset(
    asset: CandidateAsset,
    event: EventAnalysis,
    cases: list[dict[str, Any]],
    transmission_chain: TransmissionChain,
) -> EvidenceResult:
    """Apply MVP evidence rules to one candidate asset."""

    direct_matches = [
        (case["event_id"], match_reason)
        for case in cases
        if (match_reason := _direct_historical_match(asset, case))
    ]

    if direct_matches:
        evidence_level = "historical_supported"
        confidence = 0.82
        supporting_case_ids = [case_id for case_id, _ in direct_matches]
        match_details = _dedupe([detail for _, detail in direct_matches])
        reason = (
            f"Historical support from {', '.join(match_details)}. "
            f"{_asset_label(asset)} is a potential exposure candidate and "
            "risk watchlist item, not a trading signal. This does not predict "
            "price movement."
        )
    else:
        proxy_matches = [
            (case["event_id"], match_reason)
            for case in cases
            if (match_reason := _sector_proxy_match(asset, event, case, transmission_chain))
        ]
        if proxy_matches:
            evidence_level = "sector_proxy"
            confidence = 0.64
            supporting_case_ids = [case_id for case_id, _ in proxy_matches]
            match_details = _dedupe([detail for _, detail in proxy_matches])
            reason = (
                f"Sector proxy support from {', '.join(match_details)}. "
                f"{_asset_label(asset)} maps to a supported supply-chain "
                "channel and is a risk watchlist candidate, not a trading "
                "signal. This does not predict price movement."
            )
        else:
            evidence_level = "inference_only"
            confidence = 0.35
            supporting_case_ids = list(transmission_chain.supporting_case_ids)
            reason = (
                f"{_asset_label(asset)} is mapped from asset_mapping.csv via "
                f"node {asset.supply_chain_node or 'unknown'}, but retrieved "
                "cases only weakly support the channel. Treat it as an "
                "inference-only risk watchlist candidate, not a trading signal. "
                "This does not predict price movement."
            )

    return EvidenceResult(
        asset=asset,
        evidence_grade=evidence_level,
        rationale=reason,
        supporting_case_ids=supporting_case_ids,
        ticker=asset.ticker or asset.asset_id,
        asset_name=asset.asset_name or asset.name,
        evidence_level=evidence_level,
        confidence=confidence,
        reason=reason,
    )


def _direct_historical_match(asset: CandidateAsset, case: dict[str, Any]) -> str | None:
    """Return direct historical support detail when present."""

    haystack = _case_search_text(case)
    if _contains_ticker(haystack, asset.ticker):
        return f"ticker {asset.ticker}"
    if _contains(haystack, asset.asset_name) or _contains(haystack, asset.name):
        return f"asset name {_asset_label(asset)}"

    exposure_text = _case_exposure_text(case)
    close_match = _close_exposure_match(asset, exposure_text)
    if close_match:
        return close_match

    return None


def _sector_proxy_match(
    asset: CandidateAsset,
    event: EventAnalysis,
    case: dict[str, Any],
    transmission_chain: TransmissionChain,
) -> str | None:
    """Return sector proxy support detail when present."""

    node = asset.supply_chain_node
    if not node:
        return None

    affected_nodes = set(event.supply_chain_nodes) | set(transmission_chain.affected_nodes)
    if node not in affected_nodes:
        return None

    channel_text = _case_channel_text(case)
    if node in case.get("supply_chain_nodes", []) or node in channel_text:
        return f"node {node}"

    case_industries = [industry.lower() for industry in case.get("industries", [])]
    event_industries = [industry.lower() for industry in event.industries]
    asset_sector = (asset.sector or asset.category or "").lower()
    related_industries = sorted(set(case_industries) & set(event_industries))

    if related_industries:
        return f"related industry {related_industries[0]}"
    if asset_sector and any(_loose_phrase_match(asset_sector, industry) for industry in case_industries):
        return f"sector {asset_sector}"

    return None


def _close_exposure_match(asset: CandidateAsset, exposure_text: str) -> str | None:
    """Match candidate category against affected assets and affected asset types."""

    node = asset.supply_chain_node or ""
    asset_type = (asset.asset_type or "").lower()
    sector = (asset.sector or asset.category or "").lower()
    notes = (asset.notes or "").lower()
    combined = " ".join([node, asset_type, sector, notes])

    close_match_rules = [
        (
            ["maritime_chokepoint", "container_shipping", "container", "shipping etf"],
            ["shipping equities", "container carriers", "container shipping operators"],
            "shipping exposure matched affected shipping assets",
        ),
        (
            ["oil_shipping", "tanker", "crude tanker"],
            ["tanker operators", "oil tankers", "tanker fleets"],
            "tanker transport matched affected tanker assets",
        ),
        (
            ["lng_shipping", "lng"],
            ["lng cargoes", "lng carriers", "lng infrastructure"],
            "LNG transport matched affected LNG assets",
        ),
        (
            ["semiconductor_equipment", "semiconductor equipment", "chip equipment"],
            ["semiconductor equipment companies", "wafer fabrication equipment"],
            "semiconductor equipment matched affected equipment assets",
        ),
        (
            ["refining", "refiner"],
            ["refiners", "refining margins", "refinery feedstocks"],
            "refining exposure matched affected refining assets",
        ),
    ]

    for candidate_terms, exposure_terms, detail in close_match_rules:
        candidate_match = any(term in combined for term in candidate_terms)
        exposure_match = any(term in exposure_text for term in exposure_terms)
        if candidate_match and exposure_match:
            return detail

    return None


def _case_search_text(case: dict[str, Any]) -> str:
    """Combine fields used for historical support checks."""

    fields = [
        case.get("event_id", ""),
        case.get("event_name", ""),
        case.get("event_type", ""),
        case.get("date", ""),
        case.get("retrieval_text", ""),
        *case.get("regions", []),
        *case.get("countries", []),
        *case.get("industries", []),
        *case.get("supply_chain_nodes", []),
        *case.get("affected_assets", []),
        *case.get("affected_asset_types", []),
        *case.get("transmission_chain", []),
    ]
    return " ".join(str(field).lower() for field in fields)


def _case_exposure_text(case: dict[str, Any]) -> str:
    """Combine case fields that describe affected assets."""

    fields = [
        *case.get("affected_assets", []),
        *case.get("affected_asset_types", []),
    ]
    return " ".join(str(field).lower() for field in fields)


def _case_channel_text(case: dict[str, Any]) -> str:
    """Combine case fields that describe industries and channels."""

    fields = [
        case.get("retrieval_text", ""),
        *case.get("industries", []),
        *case.get("supply_chain_nodes", []),
        *case.get("transmission_chain", []),
    ]
    return " ".join(str(field).lower() for field in fields)


def _contains(haystack: str, value: str | None) -> bool:
    """Return whether a non-empty candidate value appears in text."""

    return bool(value) and str(value).lower() in haystack


def _contains_ticker(haystack: str, ticker: str | None) -> bool:
    """Return whether a ticker appears as a distinct token in text."""

    if not ticker or ticker.upper() in GENERIC_TICKER_TERMS:
        return False

    pattern = rf"(?<![a-z0-9.]){re.escape(ticker.lower())}(?![a-z0-9.])"
    return re.search(pattern, haystack) is not None


def _loose_phrase_match(left: str, right: str) -> bool:
    """Return whether either phrase contains the other."""

    return bool(left and right) and (left in right or right in left)


def _asset_label(asset: CandidateAsset) -> str:
    """Return a stable human-readable asset label."""

    return asset.asset_name or asset.name or asset.ticker or asset.asset_id


def _dedupe(values: list[str]) -> list[str]:
    """Preserve order while removing duplicates."""

    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _load_cases_by_id() -> dict[str, dict[str, Any]]:
    """Load full historical case records keyed by event ID."""

    cases = json.loads(HISTORICAL_CASES_PATH.read_text(encoding="utf-8"))
    return {case["event_id"]: case for case in cases}


def _case_from_retrieved(case: RetrievedCase) -> dict[str, Any]:
    """Fallback shape when a retrieved case is not found in local data."""

    return {
        "event_id": case.case_id,
        "event_name": case.title,
        "event_type": case.event_type or "",
        "summary": case.summary,
        "transmission_chain": case.transmission_chain,
        "industries": [],
        "supply_chain_nodes": [],
        "affected_assets": [],
        "affected_asset_types": [],
        "retrieval_text": case.summary,
    }
