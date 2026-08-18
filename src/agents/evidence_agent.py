"""Deterministic evidence grading for mapped risk exposure candidates.

Evidence grading is driven by the transmission layer, not re-derived here. The
transmission builder has already decided, per supply-chain node, whether the
node is first-order (directly implicated by the event) or a second-order target
corroborated across multiple historical analogs, and which cases support it.
This module propagates that node-level conclusion onto the assets mapped from
each node, and only *upgrades* an asset to ``historical_supported`` when the
exact asset is directly named in a retrieved case. The direct-name string match
is therefore an upgrade signal, not the primary basis for grading.

Two orthogonal labels are produced per asset:
- ``transmission_order``: first_order vs second_order (where the node came from)
- ``evidence_level``: historical_supported / sector_proxy / inference_only
  (how strongly retrieved cases support the exposure)

Results describe potential exposure candidates and risk watchlist items only.
They do not predict stock prices or provide investment advice.
"""

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

# Transmission-order labels (from the transmission node tier).
FIRST_ORDER = "first_order"
SECOND_ORDER = "second_order"
UNMAPPED = "unmapped"

NODE_TIER_TO_ORDER = {
    "event_node": FIRST_ORDER,
    "case_grounded": SECOND_ORDER,
}

# Confidence per evidence band (see README confidence bands). Confidence tracks
# the evidence level only; transmission order is a separate axis.
CONFIDENCE_BY_LEVEL = {
    "historical_supported": 0.82,
    "sector_proxy": 0.64,
    "inference_only": 0.35,
}


def grade_evidence(
    event: EventAnalysis,
    candidate_assets: list[CandidateAsset],
    retrieved_cases: list[RetrievedCase],
    transmission_chain: TransmissionChain,
) -> list[EvidenceResult]:
    """Grade evidence for candidate assets using deterministic rules.

    Results describe potential exposure candidates and risk watchlist items
    only. They do not predict stock prices or provide investment advice.
    """

    historical_cases = _load_cases_by_id()
    enriched_cases = [
        historical_cases.get(case.case_id, _case_from_retrieved(case))
        for case in retrieved_cases
    ]

    return [
        _grade_asset(asset, enriched_cases, transmission_chain)
        for asset in candidate_assets
    ]


def _grade_asset(
    asset: CandidateAsset,
    cases: list[dict[str, Any]],
    transmission_chain: TransmissionChain,
) -> EvidenceResult:
    """Grade one asset by inheriting its node's transmission-layer conclusion.

    Base level comes from whether the asset's supply-chain node is corroborated
    by retrieved cases (channel support). The level is upgraded to
    ``historical_supported`` only when the exact asset is directly named in a
    retrieved case.
    """

    node = asset.supply_chain_node
    node_tier = transmission_chain.node_evidence_levels.get(node) if node else None
    node_case_ids = (
        transmission_chain.node_supporting_case_ids.get(node, []) if node else []
    )
    transmission_order = NODE_TIER_TO_ORDER.get(node_tier, UNMAPPED)
    order_phrase = _order_phrase(transmission_order)

    # --- Upgrade signal: is the exact asset directly named in a case? ---------
    direct_matches = [
        (case["event_id"], match_reason)
        for case in cases
        if (match_reason := _direct_historical_match(asset, case))
    ]

    if direct_matches:
        evidence_level = "historical_supported"
        supporting_case_ids = _dedupe([case_id for case_id, _ in direct_matches])
        match_details = _dedupe([detail for _, detail in direct_matches])
        reason = (
            f"Historical support from {', '.join(match_details)}. The "
            f"transmission node '{node or 'unknown'}' is {order_phrase}, and "
            f"{_asset_label(asset)} is directly named in the supporting "
            "case(s). Potential exposure candidate and risk watchlist item, "
            "not a trading signal. This does not predict price movement."
        )
    elif node_case_ids:
        # Inherit channel-level support from the transmission node itself.
        evidence_level = "sector_proxy"
        supporting_case_ids = list(node_case_ids)
        reason = (
            f"Channel support inherited from transmission node '{node}', which "
            f"is {order_phrase} corroborated by {len(node_case_ids)} retrieved "
            f"case(s). {_asset_label(asset)} maps to this supported channel but "
            "is not individually named. Risk watchlist candidate, not a "
            "trading signal. This does not predict price movement."
        )
    else:
        evidence_level = "inference_only"
        supporting_case_ids = []
        reason = (
            f"{_asset_label(asset)} is mapped from asset_mapping.csv via node "
            f"'{node or 'unknown'}' ({order_phrase}), but retrieved cases do "
            "not corroborate this channel. Inference-only risk watchlist "
            "candidate, not a trading signal. This does not predict price "
            "movement."
        )

    return EvidenceResult(
        asset=asset,
        evidence_grade=evidence_level,
        rationale=reason,
        supporting_case_ids=supporting_case_ids,
        qualification_case_ids=list(node_case_ids),
        qualification_case_count=len(set(node_case_ids)),
        ticker=asset.ticker or asset.asset_id,
        asset_name=asset.asset_name or asset.name,
        evidence_level=evidence_level,
        confidence=CONFIDENCE_BY_LEVEL[evidence_level],
        reason=reason,
        transmission_order=transmission_order,
        linkage_tier=asset.linkage_tier,
        linkage_rationale=asset.linkage_rationale,
    )


def _order_phrase(transmission_order: str) -> str:
    """Human-readable phrase for a transmission-order label."""

    return {
        FIRST_ORDER: "a first-order (directly implicated) node",
        SECOND_ORDER: "a second-order (analog-corroborated) node",
        UNMAPPED: "an unmapped node",
    }.get(transmission_order, "an unmapped node")


def _direct_historical_match(asset: CandidateAsset, case: dict[str, Any]) -> str | None:
    """Return direct historical support detail when the asset is named.

    This is the upgrade signal: a match here promotes the asset to
    ``historical_supported`` regardless of the inherited channel level.
    """

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


def _contains(haystack: str, value: str | None) -> bool:
    """Return whether a non-empty candidate value appears in text."""

    return bool(value) and str(value).lower() in haystack


def _contains_ticker(haystack: str, ticker: str | None) -> bool:
    """Return whether a ticker appears as a distinct token in text."""

    if not ticker or ticker.upper() in GENERIC_TICKER_TERMS:
        return False

    pattern = rf"(?<![a-z0-9.]){re.escape(ticker.lower())}(?![a-z0-9.])"
    return re.search(pattern, haystack) is not None


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
