"""Offline feasibility study for deterministic mechanism-consistency rules.

The script evaluates whether existing structured KB and event-analysis fields
can distinguish broad-node weak co-occurrence from non-weak support. It is
diagnostic-only and does not alter production pipeline behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from scripts.audit_upstream_candidates import (
    DEFAULT_V3_MANIFEST,
    _load_evaluation_events,
    _load_json,
    _load_v3_events,
)
from src.agents.event_analyst import analyze_event


DEFAULT_INPUT = Path("data/topk_sensitivity_v4/incremental_candidate_quality_audit.csv")
DEFAULT_OUTPUT = Path("data/topk_sensitivity_v4/mechanism_consistency_rule_audit.csv")
DEFAULT_SUMMARY = Path("data/topk_sensitivity_v4/mechanism_consistency_rule_summary.json")
DEFAULT_RULES = Path("data/topk_sensitivity_v4/mechanism_consistency_rule_comparison.csv")
DEFAULT_EVENT_STABILITY = Path("data/topk_sensitivity_v4/mechanism_rule_event_stability.csv")
DEFAULT_NODE_STABILITY = Path("data/topk_sensitivity_v4/mechanism_rule_node_stability.csv")
DEFAULT_CASES = Path("data/historical_cases.json")

GENERIC_BROAD_NODES = {
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
    """Run the offline rule feasibility study."""

    parser = argparse.ArgumentParser(
        description="Evaluate deterministic structured-field rules for mechanism consistency."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    args = parser.parse_args()

    input_rows = [
        row for row in _read_csv(Path(args.input))
        if row["node_specificity"] == "potentially_broad"
    ]
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

    instances = _dedupe_instances(input_rows)
    audit_rows = [
        _feature_row(instance, cases_by_id, event_analysis_by_id.get(instance["event_id"]))
        for instance in instances
    ]
    rule_specs = _rule_specs()
    for row in audit_rows:
        for rule_name, fn in rule_specs.items():
            row[rule_name] = fn(row)

    summary = _build_summary(audit_rows, cases, rule_specs)
    rule_rows = _rule_comparison(audit_rows, rule_specs)
    best_rule = "rule_6_support_mechanism_overlap"
    event_stability = _stability_rows(audit_rows, best_rule, "event_id")
    node_stability = _stability_rows(audit_rows, best_rule, "node")

    _write_csv(DEFAULT_OUTPUT, audit_rows)
    _write_csv(DEFAULT_RULES, rule_rows)
    _write_csv(DEFAULT_EVENT_STABILITY, event_stability)
    _write_csv(DEFAULT_NODE_STABILITY, node_stability)
    _write_json(DEFAULT_SUMMARY, summary)

    print(json.dumps({
        "instances": len(audit_rows),
        "asset_rows": len(input_rows),
        "rules": rule_rows,
        "outputs": [
            str(DEFAULT_OUTPUT),
            str(DEFAULT_RULES),
            str(DEFAULT_EVENT_STABILITY),
            str(DEFAULT_NODE_STABILITY),
            str(DEFAULT_SUMMARY),
        ],
    }, indent=2, sort_keys=True))


def _dedupe_instances(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (row["event_id"], row["node"], row["supporting_case_ids"])
        grouped[key].append(row)

    instances = []
    for (event_id, node, supporting_case_ids), items in grouped.items():
        labels = Counter(row["mechanism_consistency"] for row in items)
        instances.append({
            "event_id": event_id,
            "event_name": items[0]["event_name"],
            "node": node,
            "supporting_case_ids": supporting_case_ids,
            "audit_mechanism_label": labels.most_common(1)[0][0],
            "asset_count": len(items),
            "tickers": ";".join(sorted(row["ticker"] for row in items)),
        })
    return sorted(instances, key=lambda row: (row["event_id"], row["node"], row["supporting_case_ids"]))


def _feature_row(
    instance: dict[str, Any],
    cases_by_id: dict[str, dict[str, Any]],
    event_analysis: Any,
) -> dict[str, Any]:
    support_ids = _split(instance["supporting_case_ids"])
    cases = [cases_by_id[case_id] for case_id in support_ids if case_id in cases_by_id]
    target_node = instance["node"]

    current_nodes = set(getattr(event_analysis, "supply_chain_nodes", []) or [])
    current_specific_nodes = {
        node for node in current_nodes
        if node not in GENERIC_BROAD_NODES and node != target_node
    }
    support_node_sets = [
        set(case.get("supply_chain_nodes", [])) - {target_node}
        for case in cases
    ]
    support_specific_node_sets = [
        {node for node in nodes if node not in GENERIC_BROAD_NODES}
        for nodes in support_node_sets
    ]
    support_node_union = set().union(*support_node_sets) if support_node_sets else set()
    support_specific_union = (
        set().union(*support_specific_node_sets) if support_specific_node_sets else set()
    )

    current_event_type_tokens = _tokens(getattr(event_analysis, "event_type", "") or "")
    support_event_type_tokens = [_tokens(case.get("event_type", "")) for case in cases]
    current_industries = {_norm(value) for value in getattr(event_analysis, "industries", []) or []}
    support_industry_sets = [
        {_norm(value) for value in case.get("industries", [])}
        for case in cases
    ]
    support_asset_type_sets = [
        {_norm(value) for value in case.get("affected_asset_types", [])}
        for case in cases
    ]
    support_chain_token_sets = [
        _tokens(" ".join(case.get("transmission_chain", [])))
        for case in cases
    ]
    event_type_sims = [
        _jaccard(current_event_type_tokens, tokens)
        for tokens in support_event_type_tokens
    ]
    support_industry_union = set().union(*support_industry_sets) if support_industry_sets else set()

    same_event_type_fraction = (
        sum(
            1
            for case in cases
            if _norm(case.get("event_type", "")) == _norm(getattr(event_analysis, "event_type", "") or "")
        ) / len(cases)
        if cases else 0.0
    )
    current_support_non_target_node_overlap = current_nodes & support_node_union
    current_support_specific_node_overlap = current_specific_nodes & support_specific_union
    current_support_industry_overlap = current_industries & support_industry_union

    shock_direction_available = False
    shock_direction_agreement = None

    return {
        **instance,
        "weak_mechanism": instance["audit_mechanism_label"] == "weak_cooccurrence",
        "current_event_type": getattr(event_analysis, "event_type", "") or "",
        "current_event_nodes": ";".join(sorted(current_nodes)),
        "current_event_industries": ";".join(sorted(current_industries)),
        "same_event_type_fraction": same_event_type_fraction,
        "max_event_type_token_similarity": max(event_type_sims) if event_type_sims else 0.0,
        "mean_event_type_token_similarity": mean(event_type_sims) if event_type_sims else 0.0,
        "support_pairwise_event_type_jaccard": _mean_pairwise_jaccard(support_event_type_tokens),
        "non_target_node_overlap_count": len(current_support_non_target_node_overlap),
        "non_target_node_overlap": ";".join(sorted(current_support_non_target_node_overlap)),
        "specific_node_overlap_count": len(current_support_specific_node_overlap),
        "specific_node_overlap": ";".join(sorted(current_support_specific_node_overlap)),
        "support_pairwise_non_target_node_jaccard": _mean_pairwise_jaccard(support_node_sets),
        "support_pairwise_specific_node_jaccard": _mean_pairwise_jaccard(support_specific_node_sets),
        "industry_overlap_count": len(current_support_industry_overlap),
        "industry_overlap": ";".join(sorted(current_support_industry_overlap)),
        "support_pairwise_industry_jaccard": _mean_pairwise_jaccard(support_industry_sets),
        "support_pairwise_asset_type_jaccard": _mean_pairwise_jaccard(support_asset_type_sets),
        "shock_direction_available": shock_direction_available,
        "shock_direction_agreement": shock_direction_agreement,
        "support_pairwise_chain_token_jaccard": _mean_pairwise_jaccard(support_chain_token_sets),
        "supporting_case_event_types": ";".join(case.get("event_type", "") for case in cases),
        "supporting_case_nodes": ";".join(sorted(support_node_union | {target_node})),
    }


def _rule_specs() -> dict[str, Callable[[dict[str, Any]], bool]]:
    return {
        "rule_1_event_type_and_node": lambda row: (
            float(row["max_event_type_token_similarity"]) >= 0.20
            and int(row["non_target_node_overlap_count"]) > 0
        ),
        "rule_2_specific_node_or_industry": lambda row: (
            int(row["specific_node_overlap_count"]) > 0
            or int(row["industry_overlap_count"]) > 0
        ),
        "rule_3_support_context_similarity": lambda row: (
            float(row["support_pairwise_asset_type_jaccard"]) >= 0.10
            or float(row["support_pairwise_chain_token_jaccard"]) >= 0.12
        ),
        "rule_4_event_and_asset_context": lambda row: (
            float(row["max_event_type_token_similarity"]) >= 0.20
            and (
                int(row["industry_overlap_count"]) > 0
                or float(row["support_pairwise_asset_type_jaccard"]) >= 0.10
            )
        ),
        "rule_5_node_or_asset_context": lambda row: (
            int(row["specific_node_overlap_count"]) > 0
            or int(row["industry_overlap_count"]) > 0
            or float(row["support_pairwise_asset_type_jaccard"]) >= 0.10
        ),
        "rule_6_support_mechanism_overlap": lambda row: (
            float(row["support_pairwise_event_type_jaccard"]) >= 0.15
            or float(row["support_pairwise_asset_type_jaccard"]) >= 0.12
        ),
    }


def _build_summary(
    rows: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    rule_specs: dict[str, Callable[[dict[str, Any]], bool]],
) -> dict[str, Any]:
    weak = [row for row in rows if row["weak_mechanism"]]
    non_weak = [row for row in rows if not row["weak_mechanism"]]
    fields = [
        "event_type",
        "regions",
        "industries",
        "supply_chain_nodes",
        "shock_direction",
        "affected_assets",
        "affected_asset_types",
        "transmission_chain",
        "retrieval_text",
        "summary",
    ]
    field_audit = []
    for field in fields:
        examples = [case.get(field) for case in cases if case.get(field)]
        field_audit.append({
            "field": field,
            "available": bool(examples),
            "coverage": len(examples) / len(cases) if cases else None,
            "example": examples[0] if examples else None,
        })

    signal_names = [
        "same_event_type_fraction",
        "max_event_type_token_similarity",
        "non_target_node_overlap_count",
        "specific_node_overlap_count",
        "support_pairwise_event_type_jaccard",
        "industry_overlap_count",
        "support_pairwise_industry_jaccard",
        "support_pairwise_asset_type_jaccard",
        "support_pairwise_chain_token_jaccard",
    ]
    signal_summary = {
        name: _signal_stats(name, weak, non_weak)
        for name in signal_names
    }

    return {
        "field_audit": field_audit,
        "mechanism_instances": len(rows),
        "asset_rows_represented": sum(int(row["asset_count"]) for row in rows),
        "label_counts": dict(Counter(row["audit_mechanism_label"] for row in rows)),
        "binary_target_counts": {
            "weak": len(weak),
            "non_weak": len(non_weak),
        },
        "signal_summary": signal_summary,
        "rule_comparison": _rule_comparison(rows, rule_specs),
    }


def _signal_stats(
    name: str,
    weak: list[dict[str, Any]],
    non_weak: list[dict[str, Any]],
) -> dict[str, Any]:
    weak_vals = [float(row[name]) for row in weak if row[name] not in {"", None}]
    non_vals = [float(row[name]) for row in non_weak if row[name] not in {"", None}]
    return {
        "coverage": (len(weak_vals) + len(non_vals)) / (len(weak) + len(non_weak)),
        "weak_mean": mean(weak_vals) if weak_vals else None,
        "weak_median": _median(weak_vals),
        "non_weak_mean": mean(non_vals) if non_vals else None,
        "non_weak_median": _median(non_vals),
        "separation_quality": _separation_quality(weak_vals, non_vals),
    }


def _rule_comparison(
    rows: list[dict[str, Any]],
    rule_specs: dict[str, Callable[[dict[str, Any]], bool]],
) -> list[dict[str, Any]]:
    result = []
    for name in rule_specs:
        kept = [row for row in rows if row[name]]
        removed = [row for row in rows if not row[name]]
        weak = [row for row in rows if row["weak_mechanism"]]
        non_weak = [row for row in rows if not row["weak_mechanism"]]
        weak_rejected = sum(1 for row in weak if not row[name])
        weak_missed = sum(1 for row in weak if row[name])
        non_weak_retained = sum(1 for row in non_weak if row[name])
        non_weak_rejected = sum(1 for row in non_weak if not row[name])
        result.append({
            "rule": name,
            "kept_instances": len(kept),
            "removed_instances": len(removed),
            "weak_cases": len(weak),
            "weak_correctly_rejected": weak_rejected,
            "weak_cases_missed": weak_missed,
            "non_weak_cases": len(non_weak),
            "non_weak_retained": non_weak_retained,
            "non_weak_incorrectly_rejected": non_weak_rejected,
            "weak_rejection_rate": weak_rejected / len(weak) if weak else None,
            "non_weak_retention_rate": non_weak_retained / len(non_weak) if non_weak else None,
            "complexity": _rule_complexity(name),
            "main_failure_mode": _failure_mode(name, weak_missed, non_weak_rejected),
        })
    return result


def _stability_rows(rows: list[dict[str, Any]], rule_name: str, group_key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row[group_key]].append(row)
    output = []
    for value, items in groups.items():
        weak = [row for row in items if row["weak_mechanism"]]
        non_weak = [row for row in items if not row["weak_mechanism"]]
        output.append({
            group_key: value,
            "instances": len(items),
            "weak_cases": len(weak),
            "weak_rejected": sum(1 for row in weak if not row[rule_name]),
            "weak_rejection_rate": (
                sum(1 for row in weak if not row[rule_name]) / len(weak)
                if weak else None
            ),
            "non_weak_cases": len(non_weak),
            "non_weak_retained": sum(1 for row in non_weak if row[rule_name]),
            "non_weak_retention_rate": (
                sum(1 for row in non_weak if row[rule_name]) / len(non_weak)
                if non_weak else None
            ),
        })
    return sorted(output, key=lambda row: (-row["instances"], row[group_key]))


def _rule_complexity(name: str) -> str:
    return {
        "rule_1_event_type_and_node": "medium: event-type token similarity AND node overlap",
        "rule_2_specific_node_or_industry": "low: specific-node overlap OR industry overlap",
        "rule_3_support_context_similarity": "medium: support asset-type OR chain-token similarity",
        "rule_4_event_and_asset_context": "medium: event-type plus industry/asset-type context",
        "rule_5_node_or_asset_context": "medium: specific-node OR industry OR support asset-type context",
        "rule_6_support_mechanism_overlap": "low: supporting-case event-type OR asset-type overlap",
    }[name]


def _failure_mode(name: str, weak_missed: int, non_weak_rejected: int) -> str:
    if weak_missed and non_weak_rejected:
        return "misses some weak cases and rejects some non-weak cases"
    if weak_missed:
        return "too permissive; misses weak cases"
    if non_weak_rejected:
        return "too strict; rejects non-weak cases"
    return "clean separation on current audit set"


def _separation_quality(weak_vals: list[float], non_vals: list[float]) -> str:
    if not weak_vals or not non_vals:
        return "insufficient coverage"
    weak_mean = mean(weak_vals)
    non_mean = mean(non_vals)
    diff = abs(non_mean - weak_mean)
    if diff >= 0.25:
        return "strong"
    if diff >= 0.10:
        return "moderate"
    if diff > 0.03:
        return "weak"
    return "minimal"


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


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2


def _tokens(text: str) -> set[str]:
    stop = {"and", "or", "the", "of", "risk", "shock", "event", "supply", "chain"}
    return {
        token
        for token in _norm(text).replace("_", " ").replace("-", " ").split()
        if len(token) >= 3 and token not in stop
    }


def _norm(value: str) -> str:
    return str(value).lower().strip()


def _split(value: str) -> list[str]:
    return [item for item in str(value).split(";") if item]


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


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    main()
