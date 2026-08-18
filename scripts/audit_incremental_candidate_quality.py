"""Ex-ante quality audit for k=5 -> k=10 incremental second-order candidates.

This diagnostic reads existing Top-K sensitivity artifacts and historical
knowledge-base metadata. It does not use CAR, returns, prices, hit labels, or
any other market outcome data.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any


DEFAULT_INPUT = Path("data/topk_sensitivity_v4/incremental_candidates.csv")
DEFAULT_OUTPUT = Path("data/topk_sensitivity_v4/incremental_candidate_quality_audit.csv")
DEFAULT_MANUAL_REVIEW = Path("data/topk_sensitivity_v4/manual_review_candidates.csv")
DEFAULT_SUMMARY = Path("data/topk_sensitivity_v4/incremental_candidate_quality_summary.json")
DEFAULT_REPORT = Path("data/topk_sensitivity_v4/INCREMENTAL_CANDIDATE_QUALITY_AUDIT.md")
DEFAULT_CASES = Path("data/historical_cases.json")
DEFAULT_MAPPING = Path("data/asset_mapping.csv")
DEFAULT_EVENT_FUNNEL_K10 = Path("data/topk_sensitivity_v4/event_funnel_k10.csv")

GENERIC_NODE_TERMS = {
    "agriculture",
    "aviation",
    "customs",
    "defense",
    "energy",
    "financial_sanctions",
    "freight_routes",
    "logistics",
    "manufacturing_inputs",
    "marine_insurance",
    "maritime_chokepoint",
    "payment_networks",
    "trade_lanes",
}


def main() -> None:
    """Run the incremental candidate quality audit."""

    parser = argparse.ArgumentParser(
        description="Audit k=5 -> k=10 incremental second-order candidate quality."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--manual-review-output", default=str(DEFAULT_MANUAL_REVIEW))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--report-output", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    candidates = [
        row for row in _read_csv(Path(args.input))
        if row.get("comparison") == "k5_to_k10"
    ]
    cases = _load_json(DEFAULT_CASES)
    cases_by_id = {case["event_id"]: case for case in cases}
    mapping_rows = _read_csv(DEFAULT_MAPPING)
    mapping_by_node = _group_by(mapping_rows, "supply_chain_node")
    mapping_by_node_ticker = {
        (row["supply_chain_node"], row["ticker"]): row
        for row in mapping_rows
    }
    event_types = {
        row["event_id"]: row.get("event_type", "")
        for row in _read_csv(DEFAULT_EVENT_FUNNEL_K10)
    }
    retrieval_ranks = _retrieval_rank_lookup()

    audit_rows = [
        _audit_candidate(
            row=row,
            cases_by_id=cases_by_id,
            mapping_by_node=mapping_by_node,
            mapping_by_node_ticker=mapping_by_node_ticker,
            event_type=event_types.get(row["event_id"], ""),
            retrieval_ranks=retrieval_ranks.get(row["event_id"], {}),
        )
        for row in candidates
    ]
    summary = _build_summary(audit_rows)
    manual_review_rows = _manual_review_rows(audit_rows)

    _write_csv(Path(args.output), audit_rows)
    _write_csv(Path(args.manual_review_output), manual_review_rows)
    _write_json(Path(args.summary_output), summary)
    _write_report(Path(args.report_output), summary)

    print(json.dumps(summary["headline"], indent=2, sort_keys=True))


def _audit_candidate(
    row: dict[str, str],
    cases_by_id: dict[str, dict[str, Any]],
    mapping_by_node: dict[str, list[dict[str, str]]],
    mapping_by_node_ticker: dict[tuple[str, str], dict[str, str]],
    event_type: str,
    retrieval_ranks: dict[str, int],
) -> dict[str, Any]:
    node = row["node"]
    ticker = row["ticker"]
    supporting_ids = _split(row.get("node_retrieved_supporting_case_ids") or row.get("supporting_case_ids", ""))
    supporting_cases = [cases_by_id[case_id] for case_id in supporting_ids if case_id in cases_by_id]
    mapping = mapping_by_node_ticker.get((node, ticker), {})
    node_mappings = mapping_by_node.get(node, [])

    node_specificity, node_specificity_reason = _classify_node_specificity(
        node, node_mappings
    )
    mechanism, mechanism_reason = _classify_mechanism_consistency(
        node, event_type, supporting_cases
    )
    mapping_quality, mapping_reason = _classify_mapping_quality(
        node, mapping, node_mappings, node_specificity
    )
    quality, quality_reason, noise_sources = _classify_candidate_quality(
        node_specificity, mechanism, mapping_quality
    )

    ranks = [
        retrieval_ranks[case_id]
        for case_id in supporting_ids
        if case_id in retrieval_ranks
    ]
    case_event_types = [case.get("event_type", "") for case in supporting_cases]
    case_nodes = sorted({node for case in supporting_cases for node in case.get("supply_chain_nodes", [])})
    case_assets = sorted({asset for case in supporting_cases for asset in case.get("affected_assets", [])})
    case_asset_types = sorted({asset_type for case in supporting_cases for asset_type in case.get("affected_asset_types", [])})

    return {
        "event_id": row["event_id"],
        "event_name": row.get("event_name", ""),
        "event_type": event_type,
        "node": node,
        "ticker": ticker,
        "asset_name": row["asset_name"],
        "evidence_level": row["evidence_level"],
        "supporting_case_count": len(supporting_ids),
        "supporting_case_ids": ";".join(supporting_ids),
        "supporting_case_event_types": ";".join(case_event_types),
        "supporting_case_nodes": ";".join(case_nodes),
        "supporting_case_affected_assets": ";".join(case_assets),
        "supporting_case_affected_asset_types": ";".join(case_asset_types),
        "mapping_node": node,
        "mapping_asset_type": mapping.get("asset_type", row.get("asset_type", "")),
        "linkage_tier": row.get("linkage_tier", mapping.get("linkage_tier", "")),
        "linkage_rationale": mapping.get("linkage_rationale", ""),
        "retrieval_ranks_of_supporting_cases": ";".join(str(rank) for rank in ranks),
        "max_retrieval_rank_of_supporting_cases": max(ranks) if ranks else "",
        "node_specificity": node_specificity,
        "node_specificity_reason": node_specificity_reason,
        "mechanism_consistency": mechanism,
        "mechanism_consistency_reason": mechanism_reason,
        "mapping_quality": mapping_quality,
        "mapping_quality_reason": mapping_reason,
        "candidate_quality": quality,
        "candidate_quality_reason": quality_reason,
        "noise_sources": ";".join(noise_sources),
    }


def _classify_node_specificity(
    node: str,
    mappings: list[dict[str, str]],
) -> tuple[str, str]:
    tiers = Counter(row.get("linkage_tier", "") for row in mappings)
    asset_types = Counter(row.get("asset_type", "") for row in mappings)
    direct = tiers.get("direct_exposure", 0)
    broad = tiers.get("broad_proxy", 0)
    related = tiers.get("related_exposure", 0)

    if node in GENERIC_NODE_TERMS:
        return (
            "potentially_broad",
            "Node label represents a broad function, sector, or channel in the current mapping vocabulary.",
        )
    if broad == len(mappings) and mappings:
        return (
            "potentially_broad",
            "All mapped assets for this node are broad proxies, suggesting category-level rather than mechanism-specific exposure.",
        )
    if related == len(mappings) and mappings:
        return (
            "potentially_broad",
            "All mapped assets are related_exposure, indicating meaningful but indirect node specificity.",
        )
    if direct >= 1 and len(asset_types) <= 2:
        return (
            "specific",
            "Node maps to operating-company/direct exposures in a concentrated asset vocabulary.",
        )
    return (
        "unclear",
        "Existing mapping metadata is insufficient to determine node specificity confidently.",
    )


def _classify_mechanism_consistency(
    node: str,
    event_type: str,
    supporting_cases: list[dict[str, Any]],
) -> tuple[str, str]:
    if len(supporting_cases) < 2:
        return "unclear", "Fewer than two supporting cases were available for mechanism comparison."

    event_type_sets = [_tokens(case.get("event_type", "")) for case in supporting_cases]
    node_sets = [set(case.get("supply_chain_nodes", [])) for case in supporting_cases]
    asset_type_sets = [
        set(_normalize_asset_type(value) for value in case.get("affected_asset_types", []))
        for case in supporting_cases
    ]

    event_type_overlap = _mean_pairwise_jaccard(event_type_sets)
    node_overlap = _mean_pairwise_jaccard(node_sets)
    asset_type_overlap = _mean_pairwise_jaccard(asset_type_sets)
    event_case_alignment = max(
        (_jaccard(_tokens(event_type), _tokens(case.get("event_type", ""))) for case in supporting_cases),
        default=0.0,
    )

    if node in GENERIC_NODE_TERMS and event_type_overlap < 0.15 and asset_type_overlap < 0.12:
        return (
            "weak_cooccurrence",
            "Supporting cases share a broad node but have low event-type and affected-asset-type overlap.",
        )
    if event_type_overlap >= 0.25 or asset_type_overlap >= 0.25:
        return (
            "consistent",
            "Supporting cases show overlapping event mechanisms or affected asset-type vocabulary.",
        )
    if node_overlap >= 0.35 and event_case_alignment >= 0.10:
        return (
            "mixed",
            "Supporting cases share related node context, but event mechanisms are only partially aligned.",
        )
    if node in GENERIC_NODE_TERMS:
        return (
            "weak_cooccurrence",
            "The shared support is mainly a common broad node across otherwise different cases.",
        )
    return (
        "mixed",
        "Cases share the node but available structured metadata indicates mixed transmission context.",
    )


def _classify_mapping_quality(
    node: str,
    mapping: dict[str, str],
    node_mappings: list[dict[str, str]],
    node_specificity: str,
) -> tuple[str, str]:
    tier = mapping.get("linkage_tier", "")
    asset_type = mapping.get("asset_type", "")
    node_asset_types = {row.get("asset_type", "") for row in node_mappings}

    if tier == "direct_exposure" and node_specificity == "specific":
        return "specific", "Mapped ticker has direct_exposure metadata for a specific node."
    if tier == "direct_exposure":
        return (
            "specific",
            "Mapped ticker is direct_exposure, though the node itself may be broad.",
        )
    if tier == "related_exposure" and node_specificity == "specific":
        return (
            "broad",
            "Mapped ticker is related_exposure rather than direct exposure for an otherwise specific node.",
        )
    if tier == "related_exposure":
        return (
            "broad",
            "Mapping is economically related but indirect/diversified according to asset_mapping metadata.",
        )
    if tier == "broad_proxy":
        return (
            "broad",
            "Mapped ticker is a broad_proxy instrument or ETF/basket exposure.",
        )
    if len(node_asset_types) > 2 or asset_type == "ETF":
        return (
            "questionable",
            "Node maps across multiple asset types or ETF-like exposure without clear linkage metadata.",
        )
    return "unclear", "Mapping row lacks enough linkage metadata to determine specificity."


def _classify_candidate_quality(
    node_specificity: str,
    mechanism: str,
    mapping_quality: str,
) -> tuple[str, str, list[str]]:
    noise_sources: list[str] = []
    if node_specificity == "potentially_broad":
        noise_sources.append("broad_node")
    if mechanism == "weak_cooccurrence":
        noise_sources.append("weak_supporting_case_consistency")
    if mapping_quality in {"broad", "questionable"}:
        noise_sources.append("broad_asset_mapping")

    if (
        node_specificity == "specific"
        and mechanism == "consistent"
        and mapping_quality == "specific"
    ):
        return (
            "likely_useful",
            "Specific node, consistent supporting cases, and specific asset mapping.",
            noise_sources,
        )
    if mechanism == "weak_cooccurrence" and (
        node_specificity == "potentially_broad" or mapping_quality in {"broad", "questionable"}
    ):
        return (
            "likely_noise",
            "Weak cross-case mechanism support combined with broad node or broad/questionable mapping.",
            noise_sources,
        )
    if node_specificity == "unclear" or mechanism == "unclear" or mapping_quality == "unclear":
        return (
            "unclear",
            "Available structured metadata is insufficient for a confident quality label.",
            noise_sources,
        )
    return (
        "borderline",
        "Candidate has some ex-ante support, but at least one dimension is broad or mixed.",
        noise_sources,
    )


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    quality_counts = Counter(row["candidate_quality"] for row in rows)
    evidence_quality = _nested_counts(rows, "evidence_level", "candidate_quality")
    mechanism_counts = Counter(row["mechanism_consistency"] for row in rows)
    specificity_counts = Counter(row["node_specificity"] for row in rows)
    mapping_counts = Counter(row["mapping_quality"] for row in rows)
    node_rows = _aggregate(rows, "node")
    event_rows = _aggregate(rows, "event_id")
    noise_sources = Counter(
        source
        for row in rows
        if row["candidate_quality"] in {"borderline", "likely_noise"}
        for source in _split(row["noise_sources"])
    )
    reviewed_total = len(rows) - quality_counts.get("unclear", 0)
    useful_rate = (
        quality_counts.get("likely_useful", 0) / reviewed_total
        if reviewed_total else None
    )
    useful_or_borderline_rate = (
        (quality_counts.get("likely_useful", 0) + quality_counts.get("borderline", 0))
        / len(rows)
        if rows else None
    )

    return {
        "headline": {
            "incremental_candidates_audited": len(rows),
            "likely_useful": quality_counts.get("likely_useful", 0),
            "borderline": quality_counts.get("borderline", 0),
            "likely_noise": quality_counts.get("likely_noise", 0),
            "unclear": quality_counts.get("unclear", 0),
            "incremental_useful_rate_excluding_unclear": useful_rate,
            "likely_useful_plus_borderline_share": useful_or_borderline_rate,
        },
        "candidate_quality_counts": dict(quality_counts),
        "candidate_quality_percentages": _percentages(quality_counts, len(rows)),
        "by_evidence_level": evidence_quality,
        "mechanism_consistency_counts": dict(mechanism_counts),
        "node_specificity_counts": dict(specificity_counts),
        "mapping_quality_counts": dict(mapping_counts),
        "by_node": node_rows,
        "by_event": event_rows,
        "noise_source_counts": dict(noise_sources),
        "historical_supported_rank_summary": _historical_supported_rank_summary(rows),
    }


def _aggregate(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    result = []
    for value, items in grouped.items():
        counts = Counter(item["candidate_quality"] for item in items)
        result.append(
            {
                key: value,
                "incremental_asset_count": len(items),
                "likely_useful": counts.get("likely_useful", 0),
                "borderline": counts.get("borderline", 0),
                "likely_noise": counts.get("likely_noise", 0),
                "unclear": counts.get("unclear", 0),
            }
        )
    return sorted(
        result,
        key=lambda item: (-item["incremental_asset_count"], item[key]),
    )


def _manual_review_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    high_volume_nodes = {
        row["node"]
        for row in _aggregate(rows, "node")[:8]
    }
    selected = [
        row for row in rows
        if row["candidate_quality"] in {"unclear", "borderline"}
        or row["node"] in high_volume_nodes
    ]
    return sorted(
        selected,
        key=lambda row: (
            row["candidate_quality"],
            row["node"],
            row["event_id"],
            row["ticker"],
        ),
    )


def _retrieval_rank_lookup() -> dict[str, dict[str, int]]:
    lookup: dict[str, dict[str, int]] = {}
    for row in _read_csv(DEFAULT_EVENT_FUNNEL_K10):
        event_lookup: dict[str, int] = {}
        for index, case_id in enumerate(_split(row.get("retrieved_case_ids", "")), start=1):
            event_lookup[case_id] = index
        lookup[row["event_id"]] = event_lookup
    return lookup


def _historical_supported_rank_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hist_rows = [row for row in rows if row["evidence_level"] == "historical_supported"]
    max_ranks = [
        int(row["max_retrieval_rank_of_supporting_cases"])
        for row in hist_rows
        if str(row["max_retrieval_rank_of_supporting_cases"]).isdigit()
    ]
    return {
        "count": len(hist_rows),
        "max_support_rank_counts": dict(Counter(max_ranks)),
        "mean_max_support_rank": mean(max_ranks) if max_ranks else None,
        "required_case_beyond_rank_5": sum(1 for rank in max_ranks if rank > 5),
    }


def _nested_counts(
    rows: list[dict[str, Any]],
    group_key: str,
    count_key: str,
) -> dict[str, dict[str, int]]:
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        groups[row[group_key]][row[count_key]] += 1
    return {key: dict(counts) for key, counts in groups.items()}


def _mean_pairwise_jaccard(sets: list[set[str]]) -> float:
    if len(sets) < 2:
        return 0.0
    scores = [_jaccard(left, right) for left, right in combinations(sets, 2)]
    return mean(scores) if scores else 0.0


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _tokens(text: str) -> set[str]:
    stop = {"and", "or", "the", "of", "risk", "shock", "event"}
    return {
        token
        for token in text.lower().replace("_", " ").replace("-", " ").split()
        if len(token) >= 3 and token not in stop
    }


def _normalize_asset_type(value: str) -> str:
    return value.lower().replace("-", " ").replace("_", " ").strip()


def _group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return groups


def _percentages(counts: Counter[str], total: int) -> dict[str, float]:
    return {key: value / total for key, value in counts.items()} if total else {}


def _split(value: str) -> list[str]:
    return [item for item in str(value).split(";") if item]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Incremental Candidate Quality Audit",
        "",
        "This is an ex-ante structural audit of k=5 -> k=10 second-order candidates.",
        "",
        "```json",
        json.dumps(summary, indent=2, sort_keys=True),
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
