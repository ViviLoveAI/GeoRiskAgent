"""Run a focused diagnostic for energy canonical-family compatibility.

Development-only. This script validates that energy trade access and energy
trade finance remain distinct canonical contexts while sharing a narrow
diagnostic transmission family. It does not touch production retrieval,
transmission, ranking, market data, or CAR outputs.
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
    _missing_context,
)
from src.validation.transmission_context import (
    ACTIVE_ROLES,
    BACKGROUND_ROLE,
    COMPATIBLE,
    REVIEW_CANONICAL_CONTEXT_FAMILIES,
    UNKNOWN_VALUES,
    mechanism_compatibility_with_family_review,
    support_diagnostics_with_family_review,
)


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
OUTPUT_CSV = OUTPUT_DIR / "energy_canonical_family_experiment.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / "energy_canonical_family_experiment_summary.json"


def main() -> None:
    rows = [_evaluate_case(case) for case in _experiment_cases()]
    target = _energy_target_result()
    summary = _summary(rows, target)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(OUTPUT_CSV, rows)
    OUTPUT_SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary, indent=2, sort_keys=True))


def _experiment_cases() -> list[dict[str, Any]]:
    return [
        _case("exact_access", "energy_trade_access_constraint", "energy_trade_access_constraint", True),
        _case("exact_finance", "energy_trade_finance_constraint", "energy_trade_finance_constraint", True),
        _case("sibling_access_to_finance", "energy_trade_access_constraint", "energy_trade_finance_constraint", True),
        _case("sibling_finance_to_access", "energy_trade_finance_constraint", "energy_trade_access_constraint", True),
        _case("negative_access_to_distribution", "energy_trade_access_constraint", "energy_distribution_cyber_capacity_constraint", False),
        _case("negative_finance_to_feedstock", "energy_trade_finance_constraint", "energy_feedstock_input_constraint", False),
        _case("negative_access_to_shipping", "energy_trade_access_constraint", "oil_shipping_security_constraint", False),
        _case(
            "background_same_family",
            "energy_trade_access_constraint",
            "energy_trade_finance_constraint",
            False,
            support_role=BACKGROUND_ROLE,
        ),
    ]


def _case(
    case_id: str,
    current_mechanism: str,
    historical_mechanism: str,
    expected_compatible: bool,
    *,
    current_role: str = "downstream_exposure",
    support_role: str = "downstream_exposure",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "current_context": _ctx(current_mechanism, current_role),
        "support_context": _ctx(historical_mechanism, support_role),
        "expected_compatible": expected_compatible,
    }


def _ctx(canonical_context: str, role: str) -> dict[str, str]:
    return {
        "node": "energy",
        "shock_type": "sanctions",
        "constraint_type": _constraint_for(canonical_context),
        "upstream_driver": canonical_context,
        "target_node_role": role,
        "canonical_context": canonical_context,
    }


def _constraint_for(canonical_context: str) -> str:
    return {
        "energy_trade_access_constraint": "trade_access_restriction",
        "energy_trade_finance_constraint": "financing_constraint",
        "energy_distribution_cyber_capacity_constraint": "capacity_reduction",
        "energy_feedstock_input_constraint": "input_shortage",
        "oil_shipping_security_constraint": "route_disruption",
    }.get(canonical_context, "unknown")


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    current = case["current_context"]
    support = case["support_context"]
    decision = mechanism_compatibility_with_family_review(current, support)
    match_type = _match_type(current, support, decision.status)
    actual_compatible = decision.status == COMPATIBLE
    return {
        "case_id": case["case_id"],
        "current_mechanism": current["canonical_context"],
        "historical_mechanism": support["canonical_context"],
        "current_family": _family(current["canonical_context"]),
        "historical_family": _family(support["canonical_context"]),
        "same_exact_mechanism": current["canonical_context"] == support["canonical_context"],
        "same_canonical_family": _family(current["canonical_context"]) == _family(support["canonical_context"]),
        "current_role": current["target_node_role"],
        "historical_role": support["target_node_role"],
        "match_type": match_type,
        "expected_compatible": case["expected_compatible"],
        "actual_compatible": actual_compatible,
        "passed": actual_compatible == case["expected_compatible"],
        "notes": decision.reason,
    }


def _energy_target_result() -> dict[str, Any]:
    event_id = "dev_energy_sanctions_oil_shipping"
    node = "energy"
    supporting_case_ids = [
        "case_2019_venezuela_oil_sanctions",
        "case_2022_russia_swift_financial_sanctions",
    ]
    current_context = EXPANDED_CURRENT_CONTEXTS[(event_id, node)]
    support_contexts = [
        {"case_id": case_id, **EXPANDED_CASE_CONTEXTS.get((case_id, node), _missing_context(node))}
        for case_id in supporting_case_ids
    ]
    diagnostics = support_diagnostics_with_family_review(current_context, support_contexts)
    case_match_types = {
        context["case_id"]: _match_type(
            current_context,
            context,
            mechanism_compatibility_with_family_review(current_context, context).status,
        )
        for context in support_contexts
    }
    before = _energy_target_before_family(current_context, support_contexts)
    return {
        "event_id": event_id,
        "node": node,
        "before_family_mapping": before,
        "after_family_mapping": {
            "compatible_support_count": diagnostics["compatible_support_count"],
            "candidate_under_structured_rule": diagnostics["candidate_under_structured_rule"],
            "compatible_case_ids": diagnostics["compatible_case_ids"],
            "incompatible_case_ids": diagnostics["incompatible_case_ids"],
            "case_match_types": case_match_types,
            "case_decisions": diagnostics["case_decisions"],
        },
    }


def _energy_target_before_family(
    current_context: dict[str, Any],
    support_contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    compatible_case_ids = []
    incompatible_case_ids = []
    for context in support_contexts:
        if _compatible_without_energy_family(current_context, context):
            compatible_case_ids.append(context["case_id"])
        else:
            incompatible_case_ids.append(context["case_id"])
    return {
        "compatible_support_count": len(compatible_case_ids),
        "candidate_under_structured_rule": len(compatible_case_ids) >= 2,
        "compatible_case_ids": compatible_case_ids,
        "incompatible_case_ids": incompatible_case_ids,
    }


def _compatible_without_energy_family(
    current_context: dict[str, Any],
    supporting_context: dict[str, Any],
) -> bool:
    required = ("canonical_context", "constraint_type", "target_node_role")
    if any(
        current_context.get(field) in UNKNOWN_VALUES
        or supporting_context.get(field) in UNKNOWN_VALUES
        for field in required
    ):
        return False

    current_role = current_context["target_node_role"]
    support_role = supporting_context["target_node_role"]
    if current_role == BACKGROUND_ROLE or support_role == BACKGROUND_ROLE:
        return False
    if current_role not in ACTIVE_ROLES or support_role not in ACTIVE_ROLES:
        return False

    current_canonical = current_context["canonical_context"]
    support_canonical = supporting_context["canonical_context"]
    if current_canonical == support_canonical:
        return True
    if _family_without_energy(current_canonical) == _family_without_energy(support_canonical):
        return True
    return (
        current_context["constraint_type"] == supporting_context["constraint_type"]
        and current_role in ACTIVE_ROLES
        and support_role in ACTIVE_ROLES
    )


def _match_type(
    current_context: dict[str, Any],
    supporting_context: dict[str, Any],
    status: str,
) -> str:
    if status != COMPATIBLE:
        return "incompatible"
    current_canonical = current_context["canonical_context"]
    support_canonical = supporting_context["canonical_context"]
    if current_canonical == support_canonical:
        return "exact"
    if _family(current_canonical) == _family(support_canonical):
        return "canonical_family"
    return "role_constraint"


def _family(canonical_context: str) -> str:
    return REVIEW_CANONICAL_CONTEXT_FAMILIES.get(canonical_context, canonical_context)


def _family_without_energy(canonical_context: str) -> str:
    if canonical_context in {
        "energy_trade_access_constraint",
        "energy_trade_finance_constraint",
    }:
        return canonical_context
    return REVIEW_CANONICAL_CONTEXT_FAMILIES.get(canonical_context, canonical_context)


def _summary(rows: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any]:
    exact = [row for row in rows if str(row["case_id"]).startswith("exact_")]
    sibling = [row for row in rows if str(row["case_id"]).startswith("sibling_")]
    negative = [row for row in rows if str(row["case_id"]).startswith("negative_")]
    background = [row for row in rows if str(row["case_id"]).startswith("background_")]
    false_positive = [
        row for row in rows
        if not row["expected_compatible"] and row["actual_compatible"]
    ]
    false_negative = [
        row for row in rows
        if row["expected_compatible"] and not row["actual_compatible"]
    ]
    return {
        "diagnostic_only": True,
        "family_mapping": {
            "energy_trade_access_constraint": _family("energy_trade_access_constraint"),
            "energy_trade_finance_constraint": _family("energy_trade_finance_constraint"),
        },
        "focused_matrix": {
            "exact_positive_cases_passed": _passed(exact),
            "sibling_family_positive_cases_passed": _passed(sibling),
            "different_family_negative_cases_rejected": _passed(negative),
            "weak_background_controls_rejected": _passed(background),
            "false_positives": len(false_positive),
            "false_negatives": len(false_negative),
            "match_type_counts": dict(Counter(row["match_type"] for row in rows)),
        },
        "energy_target": target,
    }


def _passed(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {"passed": sum(row["passed"] for row in rows), "total": len(rows)}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
