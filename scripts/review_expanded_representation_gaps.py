"""Review representation gaps from expanded mechanism validation.

Diagnostic-only. This script reads existing expanded-validation artifacts and
raw historical cases, classifies the 7 insufficient-context rows and 2 false
rejections, and writes audit artifacts without changing production behavior.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.validate_mechanism_freeze_candidate import (
    EXPANDED_CASE_CONTEXTS,
    EXPANDED_CURRENT_CONTEXTS,
    EXPANDED_INSTANCES,
    _missing_context,
)
from scripts.prototype_mechanism_compatible_support import _write_csv, _write_json


VALIDATION_ERRORS = Path("data/topk_sensitivity_v4/mechanism_freeze_candidate_validation_errors.csv")
VALIDATION_ROWS = Path("data/topk_sensitivity_v4/mechanism_freeze_candidate_validation.csv")
HISTORICAL_CASES = Path("data/historical_cases.json")
OUTPUT_CSV = Path("data/topk_sensitivity_v4/expanded_representation_gap_review.csv")
OUTPUT_SUMMARY = Path("data/topk_sensitivity_v4/expanded_representation_gap_review_summary.json")

REQUIRED_CONTEXT_FIELDS = [
    "shock_type",
    "constraint_type",
    "upstream_driver",
    "target_node_role",
    "canonical_context",
]


FAILURE_REVIEW = {
    ("dev_red_sea_shipping_disruption", "defense"): {
        "primary_root_cause": "missing_enrichment",
        "secondary_root_cause": "current_event_projection_gap",
        "problem_type": "coverage_gap",
        "audit_target_review": "confirmed",
        "current_schema_sufficient_if_enriched": True,
        "counterfactual_evaluable": True,
        "counterfactual_category": "resolvable_with_current_schema",
        "brief_diagnosis": (
            "South China Sea defense context is missing; raw case fields show defense "
            "appears in maritime security context. Current event marks defense as "
            "contextual_background, so complete enrichment should still reject it."
        ),
    },
    ("dev_energy_sanctions_oil_shipping", "energy"): {
        "primary_root_cause": "canonical_family_too_narrow",
        "secondary_root_cause": "role_vocabulary_too_coarse",
        "problem_type": "schema_gap",
        "audit_target_review": "confirmed",
        "current_schema_sufficient_if_enriched": False,
        "counterfactual_evaluable": True,
        "counterfactual_category": "requires_schema_or_vocabulary_change",
        "brief_diagnosis": (
            "Both contexts are populated, but energy trade-access and trade-finance "
            "channels do not share a higher-level energy sanctions/trade family."
        ),
    },
    ("dev_food_export_restriction", "agriculture"): {
        "primary_root_cause": "audit_target_problem",
        "secondary_root_cause": "role_vocabulary_too_coarse",
        "problem_type": "ambiguous",
        "audit_target_review": "questionable",
        "current_schema_sufficient_if_enriched": False,
        "counterfactual_evaluable": True,
        "counterfactual_category": "genuinely_ambiguous",
        "brief_diagnosis": (
            "Food export restriction and fertilizer/input shortage both affect "
            "agriculture, but they operate through different parts of the chain; "
            "the expected-compatible target may be too broad."
        ),
    },
    ("dev_cyber_port_disruption", "energy"): {
        "primary_root_cause": "current_event_projection_gap",
        "secondary_root_cause": "missing_enrichment",
        "problem_type": "coverage_gap",
        "audit_target_review": "confirmed",
        "current_schema_sufficient_if_enriched": True,
        "counterfactual_evaluable": True,
        "counterfactual_category": "resolvable_with_current_schema",
        "brief_diagnosis": (
            "Current event lacks an energy node context and Colonial Pipeline energy "
            "context is missing; raw fields are sufficient to classify energy as a "
            "different fuel-distribution mechanism from fertilizer feedstock."
        ),
    },
    ("dev_graphite_export_controls", "logistics"): {
        "primary_root_cause": "current_event_projection_gap",
        "secondary_root_cause": "missing_enrichment",
        "problem_type": "coverage_gap",
        "audit_target_review": "confirmed",
        "current_schema_sufficient_if_enriched": True,
        "counterfactual_evaluable": True,
        "counterfactual_category": "resolvable_with_current_schema",
        "brief_diagnosis": (
            "Graphite controls do not establish an active logistics mechanism, while "
            "Myanmar coup and port strike logistics contexts are both populatable from "
            "raw chains. This is primarily incomplete projection/enrichment."
        ),
    },
    ("dev_semiconductor_export_controls", "aviation"): {
        "primary_root_cause": "current_event_projection_gap",
        "secondary_root_cause": "missing_enrichment",
        "problem_type": "coverage_gap",
        "audit_target_review": "confirmed",
        "current_schema_sufficient_if_enriched": True,
        "counterfactual_evaluable": True,
        "counterfactual_category": "resolvable_with_current_schema",
        "brief_diagnosis": (
            "Semiconductor export controls do not supply an active aviation context; "
            "airspace-closure support cases are classifiable with existing schema."
        ),
    },
    ("dev_food_export_restriction", "financial_sanctions"): {
        "primary_root_cause": "current_event_projection_gap",
        "secondary_root_cause": "missing_enrichment",
        "problem_type": "coverage_gap",
        "audit_target_review": "confirmed",
        "current_schema_sufficient_if_enriched": True,
        "counterfactual_evaluable": True,
        "counterfactual_category": "resolvable_with_current_schema",
        "brief_diagnosis": (
            "Food export restriction does not establish active financial sanctions; "
            "Crimea/Russia finance contexts can be represented with the current schema."
        ),
    },
    ("dev_lng_shipping_sanctions", "trade_lanes"): {
        "primary_root_cause": "genuinely_insufficient_source_evidence",
        "secondary_root_cause": "current_event_projection_gap",
        "problem_type": "ambiguous",
        "audit_target_review": "ambiguous",
        "current_schema_sufficient_if_enriched": None,
        "counterfactual_evaluable": False,
        "counterfactual_category": "genuinely_ambiguous",
        "brief_diagnosis": (
            "The trade_lanes target is ambiguous: Arctic LNG sanctions and US-China "
            "tariffs both involve trade access, but raw evidence does not clearly "
            "establish the same target-node mechanism."
        ),
    },
    ("dev_trade_tariff_customs", "energy"): {
        "primary_root_cause": "current_event_projection_gap",
        "secondary_root_cause": "missing_enrichment",
        "problem_type": "coverage_gap",
        "audit_target_review": "confirmed",
        "current_schema_sufficient_if_enriched": True,
        "counterfactual_evaluable": True,
        "counterfactual_category": "resolvable_with_current_schema",
        "brief_diagnosis": (
            "Tariff/customs event does not establish an active energy mechanism; "
            "supporting energy contexts can be enriched as distinct CBAM/fertilizer "
            "mechanisms with the existing fields."
        ),
    },
}


DOWNSTREAM_REVIEW = [
    {
        "event_id": "dev_energy_sanctions_oil_shipping",
        "node": "energy",
        "mechanism_family": "energy_trade_access_constraint;energy_trade_finance_constraint",
        "constraint_type": "financing_constraint;trade_access_restriction",
        "false_rejection_status": "false_rejection",
        "possible_semantic_subtype": "downstream_energy_trade_access_vs_finance_exposure",
    },
    {
        "event_id": "dev_food_export_restriction",
        "node": "agriculture",
        "mechanism_family": "agricultural_export_trade_constraint;agricultural_input_constraint",
        "constraint_type": "input_shortage;trade_access_restriction",
        "false_rejection_status": "false_rejection_or_target_questionable",
        "possible_semantic_subtype": "downstream_agriculture_export_vs_input_exposure",
    },
    {
        "event_id": "dev_lng_shipping_sanctions",
        "node": "lng_shipping",
        "mechanism_family": "maritime_route_disruption",
        "constraint_type": "route_disruption;supplier_substitution",
        "false_rejection_status": "retained",
        "possible_semantic_subtype": "downstream_energy_shipping_substitution_exposure",
    },
]


def main() -> None:
    historical_by_id = {
        case["event_id"]: case for case in _load_json(HISTORICAL_CASES)
    }
    validation_rows = _read_csv(VALIDATION_ROWS)
    errors = _read_csv(VALIDATION_ERRORS)
    reviewed = [_review_error(row, historical_by_id) for row in errors]
    coverage = _coverage(validation_rows)
    summary = _summary(reviewed, coverage)

    _write_csv(OUTPUT_CSV, reviewed)
    _write_json(OUTPUT_SUMMARY, summary)
    print(json.dumps(summary["root_cause_counts"], indent=2, sort_keys=True))


def _review_error(row: dict[str, str], historical_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = (row["event_id"], row["node"])
    review = FAILURE_REVIEW[key]
    support_ids = _split(row["supporting_case_ids"])
    current_context = EXPANDED_CURRENT_CONTEXTS.get(key, _missing_context(row["node"]))
    historical_contexts = [
        {
            "case_id": case_id,
            **EXPANDED_CASE_CONTEXTS.get((case_id, row["node"]), _missing_context(row["node"])),
        }
        for case_id in support_ids
    ]
    raw_cases = [
        _raw_case_payload(historical_by_id.get(case_id, {}))
        for case_id in support_ids
    ]
    missing_fields = _missing_fields(current_context, historical_contexts)
    return {
        **row,
        **review,
        "missing_fields": ";".join(missing_fields),
        "current_event_context_json": json.dumps(current_context, sort_keys=True),
        "historical_node_contexts_json": json.dumps(historical_contexts, sort_keys=True),
        "raw_supporting_cases_json": json.dumps(raw_cases, sort_keys=True),
    }


def _coverage(validation_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    contexts = []
    for instance in EXPANDED_INSTANCES:
        event_id = instance["event_id"]
        node = instance["node"]
        contexts.append(("current_event", event_id, node, EXPANDED_CURRENT_CONTEXTS.get((event_id, node), _missing_context(node))))
        for case_id in instance["supporting_case_ids"]:
            contexts.append(("historical_case", case_id, node, EXPANDED_CASE_CONTEXTS.get((case_id, node), _missing_context(node))))

    rows = []
    for field in REQUIRED_CONTEXT_FIELDS:
        populated = sum(1 for _, _, _, context in contexts if not _unknown(context.get(field)))
        rows.append({
            "field": field,
            "required_instances": len(contexts),
            "populated": populated,
            "coverage": round(populated / len(contexts), 6) if contexts else 0.0,
        })
    return rows


def _summary(reviewed: list[dict[str, Any]], coverage: list[dict[str, Any]]) -> dict[str, Any]:
    insufficient = [row for row in reviewed if row["error_type"] == "insufficient_context"]
    false_rejects = [row for row in reviewed if row["error_type"] == "false_rejection"]
    return {
        "diagnostic_only": True,
        "review_scope": {
            "failures_reviewed": len(reviewed),
            "false_rejections": len(false_rejects),
            "insufficient_context": len(insufficient),
        },
        "root_cause_counts": dict(Counter(row["primary_root_cause"] for row in reviewed)),
        "problem_type_counts": dict(Counter(row["problem_type"] for row in reviewed)),
        "audit_target_review_counts": dict(Counter(row["audit_target_review"] for row in reviewed)),
        "counterfactual_coverage": {
            "resolvable_with_current_schema_better_enrichment": sum(
                row["counterfactual_category"] == "resolvable_with_current_schema"
                for row in insufficient
            ),
            "still_requires_schema_or_vocabulary_change": sum(
                row["counterfactual_category"] == "requires_schema_or_vocabulary_change"
                for row in insufficient
            ),
            "genuinely_ambiguous": sum(
                row["counterfactual_category"] == "genuinely_ambiguous"
                for row in insufficient
            ),
        },
        "field_coverage": coverage,
        "downstream_exposure_review": DOWNSTREAM_REVIEW,
        "potential_vocabulary_refinements": [
            {
                "proposed_concept": "energy_sanctions_trade_constraint family",
                "errors_it_would_explain": ["dev_energy_sanctions_oil_shipping / energy"],
                "clean_cases_it_also_applies_to": ["financial_sanctions and oil_shipping sanctions controls"],
                "risk_of_over_generalization": (
                    "Medium: could merge trade access and financing channels when one is only contextual."
                ),
            },
            {
                "proposed_concept": "split downstream_exposure into export-market, input-cost, and strategic-technology subtypes",
                "errors_it_would_explain": [
                    "dev_energy_sanctions_oil_shipping / energy",
                    "dev_food_export_restriction / agriculture",
                ],
                "clean_cases_it_also_applies_to": ["lng_shipping downstream substitution", "defense downstream strategic exposure"],
                "risk_of_over_generalization": (
                    "Medium-high unless backed by consistent raw transmission-chain evidence."
                ),
            },
        ],
    }


def _raw_case_payload(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case.get("event_id", ""),
        "event_type": case.get("event_type", ""),
        "industries": case.get("industries", []),
        "supply_chain_nodes": case.get("supply_chain_nodes", []),
        "affected_asset_types": case.get("affected_asset_types", []),
        "transmission_chain": case.get("transmission_chain", []),
        "summary": case.get("summary", ""),
    }


def _missing_fields(
    current_context: dict[str, Any],
    historical_contexts: list[dict[str, Any]],
) -> list[str]:
    missing = []
    for field in REQUIRED_CONTEXT_FIELDS:
        if _unknown(current_context.get(field)):
            missing.append(f"current.{field}")
        for context in historical_contexts:
            if _unknown(context.get(field)):
                missing.append(f"{context.get('case_id', 'unknown')}.{field}")
    return missing


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def _split(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def _unknown(value: Any) -> bool:
    return value in {"", "unknown", "unavailable", None}


if __name__ == "__main__":
    main()
