"""Deterministic analyst-priority ranking for GeoRisk exposure candidates.

Ranking v1 is intentionally rank-based, not score-based: exposures are ordered
by a fixed lexicographic key built only from ex-ante evidence signals, with no
tunable weights. The ranker never removes candidates and never changes
evidence/confidence/linkage/transmission labels.

Scope: only second-order exposures are ranked. First-order exposures are kept
as a separate direct-exposure reference list, ordered by evidence strength for
readability only and excluded from Top-K, because they are named directly by
the event and serve as the control against which second-order discovery is
measured.

Ranking key for second-order exposures, compared in order:
1. evidence_level: historical_supported > sector_proxy > inference_only
2. supporting case count: more independent analogs first, saturated at 3
3. retrieval support: mean 1 / retrieval_rank across supporting cases
4. symbol: alphabetical deterministic final tiebreak

``linkage_tier`` and ``transmission_order`` are deliberately not ranking-key
features. Linkage is retained as display metadata, and every ranked exposure is
second-order, so transmission order has no within-group information.

Ranks are relative review-priority signals only. They are not price
predictions, probabilities of market movement, or investment advice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.schemas import EventAnalysis, EvidenceResult, RetrievedCase, TransmissionChain


RANKING_VERSION = "ranking_v1"

FIRST_ORDER = "first_order"
SECOND_ORDER = "second_order"
RANKED_SCOPE = "ranked_second_order"
REFERENCE_SCOPE = "reference_first_order"
UNMAPPED_SCOPE = "unmapped_transmission_order"
VALID_PRIORITY_TIERS = {
    "high_priority",
    "medium_priority",
    "exploratory",
    "reference",
    "unmapped",
}


@dataclass(frozen=True)
class RankingConfig:
    """Versioned, inspectable configuration for Asset Relevance Ranking v1."""

    ranking_version: str = RANKING_VERSION
    evidence_order: dict[str, int] = field(
        default_factory=lambda: {
            "historical_supported": 3,
            "sector_proxy": 2,
            "inference_only": 1,
        }
    )
    evidence_tier: dict[str, str] = field(
        default_factory=lambda: {
            "historical_supported": "high_priority",
            "sector_proxy": "medium_priority",
            "inference_only": "exploratory",
        }
    )
    support_saturation: int = 3


DEFAULT_RANKING_CONFIG = RankingConfig()


def rank_assets(
    evidence_results: list[EvidenceResult],
    event: EventAnalysis,
    retrieved_cases: list[RetrievedCase],
    transmission_chain: TransmissionChain | None = None,
    config: RankingConfig = DEFAULT_RANKING_CONFIG,
) -> list[EvidenceResult]:
    """Annotate exposures with ranking metadata without removing candidates.

    Second-order exposures receive a deterministic Top-K rank. First-order
    exposures are returned as a direct-exposure reference list and are not part
    of the ranked second-order Top-K set. Unknown or unmapped transmission
    orders are preserved separately so they do not contaminate the first-order
    control group.
    """

    case_lookup = _retrieved_case_lookup(retrieved_cases)

    second_order = [
        result for result in evidence_results if result.transmission_order == SECOND_ORDER
    ]
    first_order = [
        result for result in evidence_results if result.transmission_order == FIRST_ORDER
    ]
    unmapped = [
        result
        for result in evidence_results
        if result.transmission_order not in {FIRST_ORDER, SECOND_ORDER}
    ]

    ranked_second = _rank_second_order(second_order, case_lookup, config)
    reference_first = _annotate_reference(first_order, config)
    unmapped_reference = _annotate_unmapped(unmapped, config)

    return ranked_second + reference_first + unmapped_reference


def _rank_second_order(
    results: list[EvidenceResult],
    case_lookup: dict[str, dict[str, Any]],
    config: RankingConfig,
) -> list[EvidenceResult]:
    """Order second-order exposures by the lexicographic ranking key."""

    def sort_key(result: EvidenceResult) -> tuple[int, int, float, str]:
        return (
            -_evidence_rank(result, config),
            -_support_count(result, config),
            -_retrieval_support(result, case_lookup),
            _symbol(result),
        )

    ordered = sorted(results, key=sort_key)
    annotated: list[EvidenceResult] = []
    for rank, result in enumerate(ordered, start=1):
        ranking_key = _key_components(result, case_lookup, config)
        annotated.append(
            result.model_copy(
                update={
                    "ranking_version": config.ranking_version,
                    "ranking_scope": RANKED_SCOPE,
                    "rank_within_order": rank,
                    "priority_tier": config.evidence_tier.get(
                        result.evidence_level,
                        "exploratory",
                    ),
                    "ranking_key": ranking_key,
                    "supporting_case_count": ranking_key["supporting_case_count"],
                    "supporting_case_details": _supporting_case_details(
                        result.supporting_case_ids,
                        case_lookup,
                    ),
                    "ranking_rationale": _ranking_rationale(result, rank, ranking_key),
                }
            )
        )
    return annotated


def _annotate_reference(
    results: list[EvidenceResult],
    config: RankingConfig,
) -> list[EvidenceResult]:
    """Order first-order exposures by evidence strength for readability only."""

    ordered = sorted(results, key=lambda result: (-_evidence_rank(result, config), _symbol(result)))
    annotated: list[EvidenceResult] = []
    for position, result in enumerate(ordered, start=1):
        annotated.append(
            result.model_copy(
                update={
                    "ranking_version": config.ranking_version,
                    "ranking_scope": REFERENCE_SCOPE,
                    "rank_within_order": position,
                    "priority_tier": "reference",
                    "ranking_key": None,
                    "supporting_case_count": len(set(result.supporting_case_ids)),
                    "supporting_case_details": [],
                    "ranking_rationale": (
                        f"Direct-exposure reference: {_symbol(result).upper()} is a "
                        "first-order exposure named directly by the event "
                        f"({result.evidence_level} evidence). Kept as a control for "
                        "second-order discovery; not ranked and not part of Top-K."
                    ),
                }
            )
        )
    return annotated


def _annotate_unmapped(
    results: list[EvidenceResult],
    config: RankingConfig,
) -> list[EvidenceResult]:
    """Preserve unknown/unmapped transmission-order exposures separately."""

    ordered = sorted(results, key=lambda result: (-_evidence_rank(result, config), _symbol(result)))
    annotated: list[EvidenceResult] = []
    for position, result in enumerate(ordered, start=1):
        annotated.append(
            result.model_copy(
                update={
                    "ranking_version": config.ranking_version,
                    "ranking_scope": UNMAPPED_SCOPE,
                    "rank_within_order": position,
                    "priority_tier": "unmapped",
                    "ranking_key": None,
                    "supporting_case_count": len(set(result.supporting_case_ids)),
                    "supporting_case_details": [],
                    "ranking_rationale": (
                        f"Unmapped transmission-order reference: {_symbol(result).upper()} "
                        "is preserved for auditability but is excluded from the "
                        "first-order direct-exposure control group and from the "
                        "ranked second-order Top-K set."
                    ),
                }
            )
        )
    return annotated


def _evidence_rank(result: EvidenceResult, config: RankingConfig) -> int:
    """Ordinal for evidence strength; unknown labels sort last."""

    return config.evidence_order.get(result.evidence_level, 0)


def _support_count(result: EvidenceResult, config: RankingConfig) -> int:
    """Independent supporting-case count, saturated per config."""

    return min(len(set(result.supporting_case_ids)), config.support_saturation)


def _retrieval_support(
    result: EvidenceResult,
    case_lookup: dict[str, dict[str, Any]],
) -> float:
    """Mean 1 / retrieval_rank across this exposure's supporting cases."""

    scores = [
        1.0 / case_lookup[case_id]["retrieval_rank"]
        for case_id in set(result.supporting_case_ids)
        if case_id in case_lookup and case_lookup[case_id]["retrieval_rank"] > 0
    ]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 6)


def _symbol(result: EvidenceResult) -> str:
    """Lowercased symbol for stable alphabetical tiebreaking."""

    return str(result.ticker or result.asset.asset_id or "").lower()


def _key_components(
    result: EvidenceResult,
    case_lookup: dict[str, dict[str, Any]],
    config: RankingConfig,
) -> dict[str, Any]:
    """Expose exact lexicographic key values used for ranking provenance."""

    return {
        "evidence_level": result.evidence_level,
        "evidence_rank": _evidence_rank(result, config),
        "supporting_case_count": len(set(result.supporting_case_ids)),
        "qualification_case_count": len(set(result.qualification_case_ids)),
        "supporting_case_count_saturated": _support_count(result, config),
        "retrieval_support": _retrieval_support(result, case_lookup),
        "symbol": _symbol(result),
    }


def _retrieved_case_lookup(
    retrieved_cases: list[RetrievedCase],
) -> dict[str, dict[str, Any]]:
    """Index retrieved cases with 1-based rank and raw retrieval metadata."""

    lookup: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(retrieved_cases, start=1):
        metadata = _parse_relevance(case.relevance)
        lookup[case.case_id] = {
            "case_id": case.case_id,
            "retrieval_rank": index,
            "retrieval_relevance": case.relevance,
            **metadata,
        }
    return lookup


def _supporting_case_details(
    supporting_case_ids: list[str],
    case_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return ordered retrieval provenance for supporting cases."""

    details = [
        case_lookup[case_id]
        for case_id in supporting_case_ids
        if case_id in case_lookup
    ]
    details.sort(key=lambda item: int(item["retrieval_rank"]))
    return details


def _parse_relevance(relevance: str | None) -> dict[str, float]:
    """Extract raw retriever score fields without changing their semantics."""

    if not relevance:
        return {}
    distance_match = re.search(r"(?:semantic_)?distance=([0-9.]+)", relevance)
    if distance_match:
        return {"retrieval_distance": float(distance_match.group(1))}
    similarity_match = re.search(r"similarity=([0-9.]+)", relevance)
    if similarity_match:
        return {"retrieval_similarity": float(similarity_match.group(1))}
    return {}


def _ranking_rationale(
    result: EvidenceResult,
    rank: int,
    ranking_key: dict[str, Any],
) -> str:
    """Build deterministic, human-readable ranking rationale text."""

    support = ranking_key["supporting_case_count"]
    support_phrase = (
        f"{support} independent supporting case(s)"
        if support
        else "no independent retrieved-case support"
    )
    qualification_support = ranking_key.get("qualification_case_count", 0)
    qualification_phrase = ""
    if qualification_support and qualification_support != support:
        qualification_phrase = (
            f" Node qualified with {qualification_support} mechanism-compatible "
            "historical case(s); the supporting-case count shown here is "
            "asset-level evidence."
        )
    return (
        f"Second-order rank {rank}: {_symbol(result).upper()} ordered by "
        f"{result.evidence_level} evidence, {support_phrase}, retrieval support "
        f"{ranking_key['retrieval_support']:.3f}.{qualification_phrase} "
        "Relative review priority only; "
        "linkage tier and transmission order are not used for ranking. This is "
        "not a probability of price movement."
    )
