"""Isolated offline ablation for retrieval widening vs mechanism guardrail.

This diagnostic compares:
- A: top_k=5, mechanism guardrail off
- B: top_k=10, mechanism guardrail off
- C: top_k=10, offline Rule-6 broad-node guardrail on

It reads existing diagnostic artifacts and does not alter production pipeline
configuration or outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.audit_incremental_candidate_quality import _classify_node_specificity
from scripts.audit_mechanism_rule_feasibility import (
    DEFAULT_CASES,
    DEFAULT_V3_MANIFEST,
    _feature_row,
    _load_evaluation_events,
    _load_json,
    _load_v3_events,
    _rule_specs,
)
from src.agents.event_analyst import analyze_event


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
ASSET_MAPPING = Path("data/asset_mapping.csv")


def main() -> None:
    """Run the isolated retrieval-vs-guardrail ablation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    mapping_rows = _read_csv(ASSET_MAPPING)
    mapping_by_node = _group_by(mapping_rows, "supply_chain_node")
    k5_assets = _enrich_specificity(_read_csv(OUTPUT_DIR / "second_order_assets_k5.csv"), mapping_by_node)
    k10_assets = _enrich_specificity(_read_csv(OUTPUT_DIR / "second_order_assets_k10.csv"), mapping_by_node)
    topk_rows = {row["top_k"]: row for row in _read_csv(OUTPUT_DIR / "topk_comparison.csv")}

    rule6_by_instance = _rule6_results_for_assets(k10_assets)
    k10_guardrail_assets = [
        row for row in k10_assets
        if _keep_with_guardrail(row, rule6_by_instance)
    ]

    incremental_quality_rows = _read_csv(OUTPUT_DIR / "incremental_candidate_quality_audit.csv")
    incremental_quality_rows = [
        {**row, "node_specificity": row["node_specificity"]}
        for row in incremental_quality_rows
    ]
    incremental_guardrail = [
        row for row in incremental_quality_rows
        if _keep_with_guardrail(row, rule6_by_instance)
    ]
    incremental_removed = [
        row for row in incremental_quality_rows
        if not _keep_with_guardrail(row, rule6_by_instance)
    ]

    configs = {
        "A_k5_no_guardrail": _config_metrics(k5_assets, topk_rows["5"]),
        "B_k10_no_guardrail": _config_metrics(k10_assets, topk_rows["10"]),
        "C_k10_rule6_guardrail": _config_metrics(k10_guardrail_assets, None),
    }
    comparison_rows = [
        {"configuration": name, **metrics}
        for name, metrics in configs.items()
    ]
    retrieval_effect = _retrieval_effect(k5_assets, k10_assets, topk_rows)
    filter_effect = _filter_effect(
        k10_assets,
        k10_guardrail_assets,
        incremental_quality_rows,
        incremental_guardrail,
        incremental_removed,
    )
    removed_historical = _removed_historical_supported(k10_assets, rule6_by_instance)
    broad_mechanism = _broad_mechanism_removal(incremental_quality_rows, incremental_guardrail)

    summary = {
        "configurations": configs,
        "retrieval_effect_A_to_B": retrieval_effect,
        "filter_effect_B_to_C": filter_effect,
        "broad_mechanism_removal_incremental_only": broad_mechanism,
        "removed_historical_supported": removed_historical,
        "notes": {
            "quality_labels_scope": "candidate_quality labels are available only for the k=5 -> k=10 incremental cohort.",
            "rule6_scope": "Rule-6 is applied offline only to potentially_broad node candidates; specific nodes are retained.",
        },
    }

    _write_json(OUTPUT_DIR / "retrieval_guardrail_ablation_summary.json", summary)
    _write_csv(OUTPUT_DIR / "retrieval_guardrail_ablation_comparison.csv", comparison_rows)
    _write_csv(OUTPUT_DIR / "retrieval_guardrail_removed_candidates.csv", removed_historical)
    _write_csv(
        OUTPUT_DIR / "retrieval_guardrail_incremental_quality_removed.csv",
        incremental_removed,
    )

    print(json.dumps({
        "comparison": comparison_rows,
        "retrieval_effect": retrieval_effect,
        "filter_effect": filter_effect,
        "outputs": [
            str(OUTPUT_DIR / "retrieval_guardrail_ablation_summary.json"),
            str(OUTPUT_DIR / "retrieval_guardrail_ablation_comparison.csv"),
            str(OUTPUT_DIR / "retrieval_guardrail_removed_candidates.csv"),
            str(OUTPUT_DIR / "retrieval_guardrail_incremental_quality_removed.csv"),
        ],
    }, indent=2, sort_keys=True))


def _enrich_specificity(
    rows: list[dict[str, str]],
    mapping_by_node: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    enriched = []
    for row in rows:
        specificity, reason = _classify_node_specificity(
            row["node"], mapping_by_node.get(row["node"], [])
        )
        enriched.append({
            **row,
            "node_specificity": specificity,
            "node_specificity_reason": reason,
        })
    return enriched


def _rule6_results_for_assets(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], bool]:
    broad_instances: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if row["node_specificity"] != "potentially_broad":
            continue
        key = _instance_key(row)
        broad_instances.setdefault(
            key,
            {
                "event_id": row["event_id"],
                "event_name": row.get("event_name", ""),
                "node": row["node"],
                "supporting_case_ids": row.get("supporting_case_ids", ""),
                "audit_mechanism_label": "",
                "asset_count": 0,
                "tickers": "",
            },
        )
        broad_instances[key]["asset_count"] += 1

    cases = _load_json(DEFAULT_CASES)
    cases_by_id = {case["event_id"]: case for case in cases}
    event_records = {
        event["event_id"]: event
        for event in [*_load_evaluation_events(), *_load_v3_events(DEFAULT_V3_MANIFEST)]
    }
    event_analysis_by_id = {
        event_id: analyze_event(record["news"])
        for event_id, record in event_records.items()
    }
    rule6 = _rule_specs()["rule_6_support_mechanism_overlap"]
    result = {}
    for key, instance in broad_instances.items():
        features = _feature_row(
            instance,
            cases_by_id,
            event_analysis_by_id.get(instance["event_id"]),
        )
        result[key] = rule6(features)
    return result


def _keep_with_guardrail(
    row: dict[str, str],
    rule6_by_instance: dict[tuple[str, str, str], bool],
) -> bool:
    if row["node_specificity"] == "specific":
        return True
    return bool(rule6_by_instance.get(_instance_key(row), False))


def _config_metrics(
    rows: list[dict[str, str]],
    topk_row: dict[str, str] | None,
) -> dict[str, Any]:
    evidence = Counter(row["evidence_level"] for row in rows)
    specificity = Counter(row["node_specificity"] for row in rows)
    event_node_pairs = {(row["event_id"], row["node"]) for row in rows}
    metrics = {
        "support_qualified_nodes": (
            int(topk_row["support_qualified_nodes"])
            if topk_row else len(event_node_pairs)
        ),
        "unique_second_order_nodes": len({row["node"] for row in rows}),
        "second_order_assets": len(rows),
        "unique_tickers": len({row["ticker"] for row in rows}),
        "historical_supported": evidence.get("historical_supported", 0),
        "sector_proxy": evidence.get("sector_proxy", 0),
        "inference_only": evidence.get("inference_only", 0),
        "specific_node_assets": specificity.get("specific", 0),
        "broad_node_assets": specificity.get("potentially_broad", 0),
        "likely_useful_incremental_only": None,
        "borderline_incremental_only": None,
        "likely_noise_incremental_only": None,
    }
    return metrics


def _retrieval_effect(
    k5_assets: list[dict[str, str]],
    k10_assets: list[dict[str, str]],
    topk_rows: dict[str, dict[str, str]],
) -> dict[str, Any]:
    k5_keys = {_asset_key(row) for row in k5_assets}
    added = [row for row in k10_assets if _asset_key(row) not in k5_keys]
    evidence = Counter(row["evidence_level"] for row in added)
    specificity = Counter(row["node_specificity"] for row in added)
    hist = [row for row in added if row["evidence_level"] == "historical_supported"]
    hist_specificity = Counter(row["node_specificity"] for row in hist)
    return {
        "added_support_qualified_nodes": (
            int(topk_rows["10"]["support_qualified_nodes"])
            - int(topk_rows["5"]["support_qualified_nodes"])
        ),
        "added_second_order_assets": len(added),
        "added_unique_tickers": len({row["ticker"] for row in added}),
        "added_historical_supported": evidence.get("historical_supported", 0),
        "added_sector_proxy": evidence.get("sector_proxy", 0),
        "added_inference_only": evidence.get("inference_only", 0),
        "added_specific_node_assets": specificity.get("specific", 0),
        "added_broad_node_assets": specificity.get("potentially_broad", 0),
        "added_historical_supported_specific": hist_specificity.get("specific", 0),
        "added_historical_supported_broad": hist_specificity.get("potentially_broad", 0),
        "added_historical_supported_specific_share": (
            hist_specificity.get("specific", 0) / len(hist) if hist else None
        ),
        "added_historical_supported_broad_share": (
            hist_specificity.get("potentially_broad", 0) / len(hist) if hist else None
        ),
    }


def _filter_effect(
    k10_assets: list[dict[str, str]],
    retained: list[dict[str, str]],
    incremental_quality: list[dict[str, str]],
    incremental_retained: list[dict[str, str]],
    incremental_removed: list[dict[str, str]],
) -> dict[str, Any]:
    retained_keys = {_asset_key(row) for row in retained}
    removed = [row for row in k10_assets if _asset_key(row) not in retained_keys]
    evidence_removed = Counter(row["evidence_level"] for row in removed)
    specificity_removed = Counter(row["node_specificity"] for row in removed)
    quality_retained = Counter(row["candidate_quality"] for row in incremental_retained)
    quality_removed = Counter(row["candidate_quality"] for row in incremental_removed)
    return {
        "removed_candidates_full_k10": len(removed),
        "retained_candidates_full_k10": len(retained),
        "removed_specific_node_assets_full_k10": specificity_removed.get("specific", 0),
        "removed_broad_node_assets_full_k10": specificity_removed.get("potentially_broad", 0),
        "removed_historical_supported_full_k10": evidence_removed.get("historical_supported", 0),
        "removed_sector_proxy_full_k10": evidence_removed.get("sector_proxy", 0),
        "incremental_likely_useful_retained": quality_retained.get("likely_useful", 0),
        "incremental_likely_useful_removed": quality_removed.get("likely_useful", 0),
        "incremental_borderline_retained": quality_retained.get("borderline", 0),
        "incremental_borderline_removed": quality_removed.get("borderline", 0),
        "incremental_likely_noise_retained": quality_retained.get("likely_noise", 0),
        "incremental_likely_noise_removed": quality_removed.get("likely_noise", 0),
    }


def _broad_mechanism_removal(
    incremental_quality: list[dict[str, str]],
    incremental_retained: list[dict[str, str]],
) -> dict[str, Any]:
    retained_keys = {_asset_key(row) for row in incremental_retained}
    rows = [
        row for row in incremental_quality
        if row["node_specificity"] == "potentially_broad"
    ]
    result = {}
    for label in ["consistent", "mixed", "weak_cooccurrence"]:
        label_rows = [row for row in rows if row["mechanism_consistency"] == label]
        kept = [row for row in label_rows if _asset_key(row) in retained_keys]
        result[label] = {
            "baseline": len(label_rows),
            "kept": len(kept),
            "removed": len(label_rows) - len(kept),
        }
    return result


def _removed_historical_supported(
    k10_assets: list[dict[str, str]],
    rule6_by_instance: dict[tuple[str, str, str], bool],
) -> list[dict[str, Any]]:
    rows = []
    for row in k10_assets:
        if row["evidence_level"] != "historical_supported":
            continue
        if _keep_with_guardrail(row, rule6_by_instance):
            continue
        rows.append({
            "event_id": row["event_id"],
            "node": row["node"],
            "ticker": row["ticker"],
            "asset_name": row["asset_name"],
            "node_specificity": row["node_specificity"],
            "mechanism_consistency": "",
            "supporting_case_ids": row.get("supporting_case_ids", ""),
            "candidate_quality": "",
            "evidence_level": row["evidence_level"],
        })
    quality_by_key = {
        _asset_key(row): row
        for row in _read_csv(OUTPUT_DIR / "incremental_candidate_quality_audit.csv")
    }
    for row in rows:
        quality = quality_by_key.get(_asset_key(row))
        if quality:
            row["mechanism_consistency"] = quality["mechanism_consistency"]
            row["candidate_quality"] = quality["candidate_quality"]
    return rows


def _asset_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row["event_id"], row["node"], row["ticker"])


def _instance_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row["event_id"], row["node"], row.get("supporting_case_ids", ""))


def _group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return groups


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
