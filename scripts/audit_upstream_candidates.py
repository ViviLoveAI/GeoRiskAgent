"""Audit upstream second-order candidate generation before V4 ranking.

This diagnostic is read-only with respect to GeoRisk model/data behavior. It
does not change retrieval, transmission, evidence grading, asset mapping,
ranking, CAR, or validation artifacts. It records where second-order nodes and
assets are lost before reaching the V4 ranker.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from src.agents.asset_ranker import RANKED_SCOPE, rank_assets
from src.agents.event_analyst import analyze_event
from src.agents.evidence_agent import grade_evidence
from src.agents.market_mapper import map_assets
from src.agents.transmission_builder import (
    MIN_CASE_SUPPORT_FOR_SECOND_ORDER,
    build_transmission_chain,
)
from src.config import HISTORICAL_CASES_PATH
from src.schemas import RetrievedCase
from src.vector_store import query_cases


DEFAULT_OUTPUT_DIR = Path("data/upstream_audit_v4")
DEFAULT_V3_MANIFEST = Path("data/validation_v3/v3_manifest.json")
DEFAULT_ASSET_MAPPING = Path("data/asset_mapping.csv")
EVALUATION_CASE_FILES = [
    Path("data/evaluation_cases.json"),
    Path("data/hard_evaluation_cases.json"),
]


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description="Audit upstream GeoRisk second-order candidate generation."
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--v3-manifest", default=str(DEFAULT_V3_MANIFEST))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = _load_json(HISTORICAL_CASES_PATH)
    cases_by_id = {case["event_id"]: case for case in cases}
    node_to_kb_cases = _node_to_kb_cases(cases)
    mapping = pd.read_csv(DEFAULT_ASSET_MAPPING)
    mapped_nodes = set(mapping["supply_chain_node"].astype(str))

    eval_events = _load_evaluation_events()
    v3_events = _load_v3_events(Path(args.v3_manifest))
    events = [*eval_events, *v3_events]

    event_rows: list[dict[str, Any]] = []
    retrieval_rows: list[dict[str, Any]] = []
    node_rows: list[dict[str, Any]] = []
    exposure_rows: list[dict[str, Any]] = []
    evidence_downgrade_rows: list[dict[str, Any]] = []

    for event_record in events:
        audit = _audit_event(
            event_record=event_record,
            top_k=args.top_k,
            cases_by_id=cases_by_id,
            node_to_kb_cases=node_to_kb_cases,
            mapped_nodes=mapped_nodes,
        )
        event_rows.append(audit["event_row"])
        retrieval_rows.extend(audit["retrieval_rows"])
        node_rows.extend(audit["node_rows"])
        exposure_rows.extend(audit["exposure_rows"])
        evidence_downgrade_rows.extend(audit["evidence_downgrade_rows"])

    retrieval_metrics = _retrieval_metrics(retrieval_rows, eval_events, top_k=args.top_k)
    funnel_summary = _funnel_summary(event_rows, node_rows, exposure_rows)
    bottleneck_summary = _bottleneck_summary(node_rows, evidence_downgrade_rows)
    implementation_summary = _implementation_summary()

    _write_csv(output_dir / "event_funnel.csv", event_rows)
    _write_csv(output_dir / "retrieval_audit.csv", retrieval_rows)
    _write_csv(output_dir / "second_order_node_audit.csv", node_rows)
    _write_csv(output_dir / "second_order_exposure_audit.csv", exposure_rows)
    _write_csv(output_dir / "evidence_downgrade_audit.csv", evidence_downgrade_rows)
    _write_json(output_dir / "retrieval_metrics.json", retrieval_metrics)
    _write_json(output_dir / "funnel_summary.json", funnel_summary)
    _write_json(output_dir / "bottleneck_summary.json", bottleneck_summary)
    _write_json(output_dir / "implementation_summary.json", implementation_summary)
    _write_markdown_report(
        output_dir / "UPSTREAM_CANDIDATE_AUDIT.md",
        implementation_summary,
        retrieval_metrics,
        funnel_summary,
        bottleneck_summary,
        event_rows,
        node_rows,
        evidence_downgrade_rows,
    )

    print(json.dumps({
        "output_dir": str(output_dir),
        "events_audited": len(events),
        "evaluation_events": len(eval_events),
        "v3_events": len(v3_events),
        "raw_second_order_nodes": funnel_summary["raw_second_order_nodes"],
        "accepted_second_order_nodes": funnel_summary["accepted_second_order_nodes"],
        "unmapped_accepted_second_order_nodes": funnel_summary["unmapped_accepted_second_order_nodes"],
        "second_order_assets": funnel_summary["second_order_assets"],
        "possible_false_downgrades": bottleneck_summary["evidence_rule"]["possible_false_downgrades"],
    }, indent=2))


def _audit_event(
    event_record: dict[str, Any],
    top_k: int,
    cases_by_id: dict[str, dict[str, Any]],
    node_to_kb_cases: dict[str, list[str]],
    mapped_nodes: set[str],
) -> dict[str, list[dict[str, Any]] | dict[str, Any]]:
    """Run current pipeline stages and collect diagnostic rows for one event."""

    news_text = event_record["news"]
    event = analyze_event(news_text)
    retrieved_cases = query_cases(_retrieval_query(news_text, event), top_k=top_k)
    chain = build_transmission_chain(event, retrieved_cases)
    assets = map_assets(event, chain)
    evidence = grade_evidence(event, assets, retrieved_cases, chain)
    ranked = rank_assets(evidence, event, retrieved_cases, chain)

    retrieved_ids = [case.case_id for case in retrieved_cases]
    retrieval_rows = [
        _retrieval_row(event_record, case, rank, cases_by_id)
        for rank, case in enumerate(retrieved_cases, start=1)
    ]

    node_support = _node_support_from_retrieved(retrieved_cases)
    event_nodes = set(event.supply_chain_nodes)
    accepted_second_nodes = {
        node
        for node, level in chain.node_evidence_levels.items()
        if level == "case_grounded"
    }
    raw_second_nodes = sorted(node for node in node_support if node not in event_nodes)
    mapped_accepted_nodes = {
        node for node in accepted_second_nodes if node in mapped_nodes
    }
    second_order_results = [
        result for result in ranked if result.transmission_order == "second_order"
    ]

    node_rows = [
        _node_row(
            event_record=event_record,
            node=node,
            support_ids=node_support.get(node, []),
            accepted=node in accepted_second_nodes,
            mapped=node in mapped_nodes,
            kb_case_ids=node_to_kb_cases.get(node, []),
            retrieved_ids=retrieved_ids,
            mapped_asset_count=sum(1 for asset in assets if asset.supply_chain_node == node),
        )
        for node in raw_second_nodes
    ]

    exposure_rows = [
        _exposure_row(event_record, result)
        for result in second_order_results
    ]

    evidence_downgrade_rows = [
        _evidence_downgrade_row(event_record, result, cases_by_id)
        for result in second_order_results
        if result.evidence_level == "sector_proxy"
    ]

    event_row = {
        "event_source": event_record["event_source"],
        "event_id": event_record["event_id"],
        "event_name": event_record["event_name"],
        "event_type": event.event_type,
        "expected_historical_cases": ";".join(event_record.get("expected_historical_cases", [])),
        "retrieved_case_count": len(retrieved_cases),
        "retrieved_case_ids": ";".join(retrieved_ids),
        "raw_second_order_nodes": len(raw_second_nodes),
        "accepted_second_order_nodes": len(accepted_second_nodes),
        "dropped_by_support_requirement": sum(
            1 for row in node_rows if not row["accepted"]
        ),
        "mapped_second_order_nodes": len(mapped_accepted_nodes),
        "unmapped_accepted_second_order_nodes": sum(
            1 for row in node_rows if row["accepted"] and not row["mapped"]
        ),
        "second_order_assets": len(second_order_results),
        "second_order_ranked_assets": sum(
            1 for result in second_order_results if result.ranking_scope == RANKED_SCOPE
        ),
        "historical_supported_second_order": sum(
            1 for result in second_order_results if result.evidence_level == "historical_supported"
        ),
        "sector_proxy_second_order": sum(
            1 for result in second_order_results if result.evidence_level == "sector_proxy"
        ),
        "inference_only_second_order": sum(
            1 for result in second_order_results if result.evidence_level == "inference_only"
        ),
    }

    return {
        "event_row": event_row,
        "retrieval_rows": retrieval_rows,
        "node_rows": node_rows,
        "exposure_rows": exposure_rows,
        "evidence_downgrade_rows": evidence_downgrade_rows,
    }


def _retrieval_query(news_text: str, event: Any) -> str:
    """Mirror the current case retriever query construction."""

    query_parts = [
        news_text,
        event.event_type or "",
        " ".join(event.regions),
        " ".join(event.industries),
        " ".join(event.supply_chain_nodes),
        event.shock_direction or "",
    ]
    return " ".join(part for part in query_parts if part.strip())


def _retrieval_row(
    event_record: dict[str, Any],
    case: RetrievedCase,
    rank: int,
    cases_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Create one retrieval diagnostic row."""

    full_case = cases_by_id.get(case.case_id, {})
    return {
        "event_source": event_record["event_source"],
        "event_id": event_record["event_id"],
        "event_name": event_record["event_name"],
        "expected_case": case.case_id in event_record.get("expected_historical_cases", []),
        "retrieval_rank": rank,
        "retrieved_case_id": case.case_id,
        "retrieval_relevance": case.relevance,
        "retrieved_case_event_type": case.event_type,
        "retrieved_case_nodes": ";".join(case.supply_chain_nodes),
        "retrieved_case_asset_types": ";".join(full_case.get("affected_asset_types", [])),
        "retrieved_case_assets": ";".join(full_case.get("affected_assets", [])),
    }


def _node_row(
    event_record: dict[str, Any],
    node: str,
    support_ids: list[str],
    accepted: bool,
    mapped: bool,
    kb_case_ids: list[str],
    retrieved_ids: list[str],
    mapped_asset_count: int,
) -> dict[str, Any]:
    """Create one second-order node diagnostic row."""

    outside_top_k = [case_id for case_id in kb_case_ids if case_id not in retrieved_ids]
    return {
        "event_source": event_record["event_source"],
        "event_id": event_record["event_id"],
        "event_name": event_record["event_name"],
        "node": node,
        "retrieved_supporting_case_count": len(support_ids),
        "retrieved_supporting_case_ids": ";".join(support_ids),
        "required_support": MIN_CASE_SUPPORT_FOR_SECOND_ORDER,
        "accepted": accepted,
        "mapped": mapped,
        "mapped_asset_count": mapped_asset_count,
        "kb_case_count_for_node": len(kb_case_ids),
        "kb_case_ids_for_node": ";".join(kb_case_ids),
        "kb_cases_outside_top_k_count": len(outside_top_k),
        "kb_cases_outside_top_k": ";".join(outside_top_k),
        "potential_retrieval_bottleneck": (
            not accepted
            and len(support_ids) < MIN_CASE_SUPPORT_FOR_SECOND_ORDER
            and len(kb_case_ids) >= MIN_CASE_SUPPORT_FOR_SECOND_ORDER
        ),
        "potential_mapping_bottleneck": accepted and not mapped,
        "closest_mapping_labels": "",
    }


def _exposure_row(event_record: dict[str, Any], result: Any) -> dict[str, Any]:
    """Create one second-order exposure diagnostic row."""

    return {
        "event_source": event_record["event_source"],
        "event_id": event_record["event_id"],
        "event_name": event_record["event_name"],
        "ticker": result.ticker,
        "asset_name": result.asset_name,
        "node": result.asset.supply_chain_node,
        "asset_type": result.asset.asset_type,
        "linkage_tier": result.linkage_tier,
        "evidence_level": result.evidence_level,
        "confidence": result.confidence,
        "supporting_case_ids": ";".join(result.supporting_case_ids),
        "ranking_scope": result.ranking_scope,
        "rank_within_order": result.rank_within_order,
        "ranking_key": json.dumps(result.ranking_key, sort_keys=True),
    }


def _evidence_downgrade_row(
    event_record: dict[str, Any],
    result: Any,
    cases_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Inspect sector_proxy second-order exposures for possible missed direct support."""

    supporting_cases = [
        cases_by_id[case_id]
        for case_id in result.supporting_case_ids
        if case_id in cases_by_id
    ]
    case_asset_types = _dedupe(
        [
            item
            for case in supporting_cases
            for item in case.get("affected_asset_types", [])
        ]
    )
    case_assets = _dedupe(
        [
            item
            for case in supporting_cases
            for item in case.get("affected_assets", [])
        ]
    )
    trigger = _diagnostic_close_match(result, case_asset_types, case_assets)
    possible_direct = _possible_unrecognized_support(result, case_asset_types, case_assets)
    if trigger:
        classification = "recognized_by_current_close_rule"
    elif possible_direct:
        classification = "possible_false_downgrade"
    elif case_asset_types or case_assets:
        classification = "clearly_proxy_or_uncertain"
    else:
        classification = "uncertain_no_asset_fields"

    return {
        "event_source": event_record["event_source"],
        "event_id": event_record["event_id"],
        "event_name": event_record["event_name"],
        "ticker": result.ticker,
        "asset_name": result.asset_name,
        "node": result.asset.supply_chain_node,
        "current_evidence_level": result.evidence_level,
        "supporting_case_ids": ";".join(result.supporting_case_ids),
        "historical_case_asset_types": ";".join(case_asset_types),
        "historical_case_assets": ";".join(case_assets),
        "close_match_rule_triggered": trigger,
        "possible_unrecognized_direct_support": possible_direct,
        "classification": classification,
        "reason": _downgrade_reason(result, possible_direct),
    }


def _diagnostic_close_match(
    result: Any,
    case_asset_types: list[str],
    case_assets: list[str],
) -> bool:
    """Mirror the current close-match categories for diagnostics."""

    combined_case_text = " ".join([*case_asset_types, *case_assets]).lower()
    candidate_text = " ".join(
        [
            result.asset.supply_chain_node or "",
            result.asset.asset_type or "",
            result.asset.sector or result.asset.category or "",
            result.asset.notes or "",
        ]
    ).lower()
    rules = [
        (
            ["maritime_chokepoint", "container_shipping", "container", "shipping etf"],
            ["shipping equities", "container carriers", "container shipping operators"],
        ),
        (
            ["oil_shipping", "tanker", "crude tanker"],
            ["tanker operators", "oil tankers", "tanker fleets"],
        ),
        (
            ["lng_shipping", "lng"],
            ["lng cargoes", "lng carriers", "lng infrastructure"],
        ),
        (
            ["semiconductor_equipment", "semiconductor equipment", "chip equipment"],
            ["semiconductor equipment companies", "wafer fabrication equipment"],
        ),
        (
            ["refining", "refiner"],
            ["refiners", "refining margins", "refinery feedstocks"],
        ),
    ]
    return any(
        any(term in candidate_text for term in candidate_terms)
        and any(term in combined_case_text for term in exposure_terms)
        for candidate_terms, exposure_terms in rules
    )


def _possible_unrecognized_support(
    result: Any,
    case_asset_types: list[str],
    case_assets: list[str],
) -> bool:
    """Heuristic flag for possible direct support not recognized by current rules."""

    text = " ".join([*case_asset_types, *case_assets]).lower()
    node_tokens = set(_tokens(result.asset.supply_chain_node or ""))
    sector_tokens = set(_tokens(result.asset.sector or result.asset.category or ""))
    note_tokens = set(_tokens(result.asset.notes or ""))
    name_tokens = set(_tokens(result.asset_name))
    informative = {
        token
        for token in node_tokens | sector_tokens | note_tokens | name_tokens
        if len(token) >= 5 and token not in {"stock", "global", "company", "exposure"}
    }
    return any(token in text for token in informative)


def _downgrade_reason(result: Any, possible_direct: bool) -> str:
    if possible_direct:
        return (
            "Supporting cases contain asset-type/category text overlapping the "
            "asset/node metadata, but the current direct historical support "
            "rules did not upgrade this exposure."
        )
    return (
        "Current evidence rule treats this as sector_proxy because supporting "
        "cases support the node/channel but do not directly name the exact "
        "asset or a recognized close-match category."
    )


def _node_support_from_retrieved(retrieved_cases: list[RetrievedCase]) -> dict[str, list[str]]:
    """Replicate transmission node support counting without changing behavior."""

    support: dict[str, list[str]] = {}
    for case in retrieved_cases:
        seen: set[str] = set()
        for node in case.supply_chain_nodes:
            if not node or node in seen:
                continue
            seen.add(node)
            support.setdefault(node, []).append(case.case_id)
    return support


def _load_evaluation_events() -> list[dict[str, Any]]:
    """Load existing explicit evaluation cases with expected analogs when present."""

    records: list[dict[str, Any]] = []
    for path in EVALUATION_CASE_FILES:
        if not path.exists():
            continue
        for item in _load_json(path):
            records.append(
                {
                    "event_source": path.stem,
                    "event_id": item.get("case_id"),
                    "event_name": item.get("case_id"),
                    "news": item.get("news", ""),
                    "expected_historical_cases": item.get("expected_historical_cases", []),
                }
            )
    return records


def _load_v3_events(path: Path) -> list[dict[str, Any]]:
    """Load frozen V3 held-out events for inspection-only diagnostics."""

    if not path.exists():
        return []
    manifest = _load_json(path)
    return [
        {
            "event_source": "validation_v3",
            "event_id": event["event_id"],
            "event_name": event.get("headline") or event["event_id"],
            "news": event["event_description"],
            "expected_historical_cases": [],
        }
        for event in manifest.get("events", [])
    ]


def _retrieval_metrics(
    retrieval_rows: list[dict[str, Any]],
    eval_events: list[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    """Compute retrieval metrics only where expected analog IDs already exist."""

    expected_events = [
        event for event in eval_events if event.get("expected_historical_cases")
    ]
    rows_by_event: dict[str, list[dict[str, Any]]] = {}
    for row in retrieval_rows:
        rows_by_event.setdefault(row["event_id"], []).append(row)

    hit1 = hit3 = hitk = 0
    reciprocal_ranks: list[float] = []
    failures: list[dict[str, Any]] = []
    for event in expected_events:
        expected = set(event["expected_historical_cases"])
        rows = sorted(rows_by_event.get(event["event_id"], []), key=lambda row: int(row["retrieval_rank"]))
        ranks = [
            int(row["retrieval_rank"])
            for row in rows
            if row["retrieved_case_id"] in expected
        ]
        if ranks:
            best = min(ranks)
            reciprocal_ranks.append(1 / best)
            hit1 += best <= 1
            hit3 += best <= 3
            hitk += best <= top_k
        else:
            reciprocal_ranks.append(0.0)
            failures.append(
                {
                    "event_id": event["event_id"],
                    "expected_historical_cases": event["expected_historical_cases"],
                    "retrieved_case_ids": [row["retrieved_case_id"] for row in rows],
                }
            )

    denominator = len(expected_events)
    return {
        "events_with_expected_analogs": denominator,
        "recall_at_1": hit1 / denominator if denominator else None,
        "recall_at_3": hit3 / denominator if denominator else None,
        f"recall_at_{top_k}": hitk / denominator if denominator else None,
        "mrr": sum(reciprocal_ranks) / denominator if denominator else None,
        "misses": failures,
        "inspection_only_events": len([event for event in retrieval_rows if event.get("event_source") == "validation_v3"]),
    }


def _funnel_summary(
    event_rows: list[dict[str, Any]],
    node_rows: list[dict[str, Any]],
    exposure_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate candidate funnel counts."""

    evidence_counts = Counter(row["evidence_level"] for row in exposure_rows)
    unique_nodes = {row["node"] for row in node_rows}
    mapped_nodes = {row["node"] for row in node_rows if row["accepted"] and row["mapped"]}
    unmapped_nodes = {row["node"] for row in node_rows if row["accepted"] and not row["mapped"]}
    return {
        "events_evaluated": len(event_rows),
        "raw_second_order_nodes": len(node_rows),
        "unique_raw_second_order_nodes": len(unique_nodes),
        "accepted_second_order_nodes": sum(1 for row in node_rows if row["accepted"]),
        "dropped_by_support_requirement": sum(1 for row in node_rows if not row["accepted"]),
        "supported_nodes_sent_to_market_mapper": sum(1 for row in node_rows if row["accepted"]),
        "mapped_second_order_nodes": sum(1 for row in node_rows if row["accepted"] and row["mapped"]),
        "unique_mapped_second_order_nodes": len(mapped_nodes),
        "unmapped_accepted_second_order_nodes": sum(1 for row in node_rows if row["accepted"] and not row["mapped"]),
        "unique_unmapped_accepted_second_order_nodes": len(unmapped_nodes),
        "node_mapping_coverage": (
            len(mapped_nodes) / (len(mapped_nodes) + len(unmapped_nodes))
            if (mapped_nodes or unmapped_nodes)
            else None
        ),
        "second_order_assets": len(exposure_rows),
        "evidence_grading": dict(evidence_counts),
        "v4_ranked_second_order_candidates": sum(
            1 for row in exposure_rows if row["ranking_scope"] == RANKED_SCOPE
        ),
    }


def _bottleneck_summary(
    node_rows: list[dict[str, Any]],
    evidence_downgrade_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize suspected bottleneck counts."""

    retrieval_rows = [row for row in node_rows if row["potential_retrieval_bottleneck"]]
    mapping_rows = [row for row in node_rows if row["potential_mapping_bottleneck"]]
    downgrade_counts = Counter(row["classification"] for row in evidence_downgrade_rows)
    return {
        "retrieval": {
            "potential_bottleneck_nodes": len(retrieval_rows),
            "affected_events": len({row["event_id"] for row in retrieval_rows}),
            "examples": retrieval_rows[:10],
        },
        "mapping": {
            "unmapped_accepted_nodes": len(mapping_rows),
            "affected_events": len({row["event_id"] for row in mapping_rows}),
            "examples": mapping_rows[:10],
        },
        "evidence_rule": {
            "sector_proxy_inspected": len(evidence_downgrade_rows),
            "possible_false_downgrades": downgrade_counts.get("possible_false_downgrade", 0),
            "recognized_by_current_close_rule": downgrade_counts.get("recognized_by_current_close_rule", 0),
            "clearly_proxy_or_uncertain": downgrade_counts.get("clearly_proxy_or_uncertain", 0),
            "uncertain_no_asset_fields": downgrade_counts.get("uncertain_no_asset_fields", 0),
            "examples": [
                row
                for row in evidence_downgrade_rows
                if row["classification"] == "possible_false_downgrade"
            ][:10],
        },
    }


def _implementation_summary() -> dict[str, Any]:
    """Summarize inspected implementation details."""

    return {
        "retriever": {
            "embedding_model": "all-MiniLM-L6-v2",
            "vector_store": "ChromaDB PersistentClient",
            "index_document_field": "historical_cases[].retrieval_text",
            "query_fields": [
                "raw news text",
                "event_type",
                "regions",
                "industries",
                "supply_chain_nodes",
                "shock_direction",
            ],
            "result_metadata": "semantic_distance=<distance>",
            "top_k_default_in_pipeline": 3,
            "explicit_relevance_threshold": False,
            "explicit_vector_normalization": False,
        },
        "transmission_builder": {
            "second_order_support_threshold": MIN_CASE_SUPPORT_FOR_SECOND_ORDER,
            "second_order_source": "nodes in retrieved cases not already event nodes",
            "support_counting": "distinct retrieved cases per node",
        },
        "evidence_agent": {
            "historical_supported": [
                "ticker appears as distinct token in full historical case text, except generic LNG",
                "asset_name/name substring appears in case text",
                "close exposure match fires for five hard-coded categories",
            ],
            "sector_proxy": "node has supporting retrieved case IDs but exact/direct match did not fire",
            "inference_only": "mapped node lacks retrieved-case support",
            "close_match_rule_count": 5,
            "close_match_categories": [
                "shipping/container",
                "oil tanker shipping",
                "LNG transport",
                "semiconductor equipment",
                "refining",
            ],
        },
        "market_mapper": {
            "matching": "exact string membership via asset_mapping['supply_chain_node'].isin(nodes)",
            "candidate_universe": "data/asset_mapping.csv",
            "dedupe": "first ticker wins across matched rows",
            "fuzzy_or_alias_matching": False,
        },
    }


def _write_markdown_report(
    path: Path,
    implementation: dict[str, Any],
    retrieval_metrics: dict[str, Any],
    funnel: dict[str, Any],
    bottlenecks: dict[str, Any],
    event_rows: list[dict[str, Any]],
    node_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> None:
    """Write a compact human-readable audit report."""

    lines = [
        "# Upstream Candidate Generation Audit",
        "",
        "This diagnostic is read-only and uses existing GeoRisk pipeline logic.",
        "",
        "## Implementation Summary",
        "",
        f"- Retriever: {implementation['retriever']['embedding_model']} with {implementation['retriever']['vector_store']}.",
        f"- Transmission support threshold: {implementation['transmission_builder']['second_order_support_threshold']} retrieved cases per second-order node.",
        f"- Market mapping: {implementation['market_mapper']['matching']}.",
        f"- Evidence close-match categories: {', '.join(implementation['evidence_agent']['close_match_categories'])}.",
        "",
        "## Retrieval Metrics",
        "",
        json.dumps(retrieval_metrics, indent=2, sort_keys=True),
        "",
        "## Candidate Funnel",
        "",
        json.dumps(funnel, indent=2, sort_keys=True),
        "",
        "## Bottleneck Summary",
        "",
        json.dumps(bottlenecks, indent=2, sort_keys=True),
        "",
        "## Top Retrieval Bottleneck Examples",
        "",
    ]
    for row in bottlenecks["retrieval"]["examples"][:5]:
        lines.append(
            f"- {row['event_id']} node={row['node']} retrieved_support={row['retrieved_supporting_case_count']} "
            f"KB_cases={row['kb_case_count_for_node']} outside_top_k={row['kb_cases_outside_top_k_count']}"
        )
    lines.extend(["", "## Top Evidence Downgrade Examples", ""])
    for row in bottlenecks["evidence_rule"]["examples"][:5]:
        lines.append(
            f"- {row['event_id']} {row['ticker']} node={row['node']} reason={row['reason']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _node_to_kb_cases(cases: list[dict[str, Any]]) -> dict[str, list[str]]:
    support: dict[str, list[str]] = {}
    for case in cases:
        for node in _dedupe(case.get("supply_chain_nodes", [])):
            support.setdefault(node, []).append(case["event_id"])
    return support


def _tokens(text: str) -> list[str]:
    return [token for token in text.lower().replace("_", " ").replace("-", " ").split() if token]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
