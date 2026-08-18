"""Versioned node-level mechanism-context compatibility for GeoRisk V4.

The helpers in this module compare current-event node contexts with historical
case/node contexts. They produce analytical support diagnostics only; they do
not forecast prices and do not provide investment advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TRANSMISSION_CONTEXT_VERSION = "transmission_context_v1"
CANONICAL_FAMILY_VERSION = "canonical_family_v1"
MECHANISM_COMPATIBILITY_VERSION = "mechanism_compatibility_candidate_v1"

COMPATIBLE_SUPPORT_THRESHOLD = 2

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
INSUFFICIENT_CONTEXT = "insufficient_context"

REQUIRED_CONTEXT_FIELDS = [
    "shock_type",
    "constraint_type",
    "upstream_driver",
    "target_node_role",
    "canonical_context",
]

ACTIVE_ROLES = {
    "direct_disruption_target",
    "transmission_channel",
    "upstream_input",
    "downstream_exposure",
    "downstream_strategic_exposure",
    "compliance_channel",
    "financing_or_insurance_channel",
}

BACKGROUND_ROLE = "contextual_background"
UNKNOWN_VALUES = {"", "unknown", "unavailable", None}

CANONICAL_CONTEXT_FAMILIES = {
    "critical_material_input_constraint": "critical_material_constraint",
    "critical_material_compliance_constraint": "critical_material_constraint",
    "critical_material_cost_constraint": "critical_material_constraint",
    "energy_trade_access_constraint": "energy_trade_constraint",
    "energy_trade_finance_constraint": "energy_trade_constraint",
    "maritime_route_capacity_constraint": "maritime_route_disruption",
    "maritime_route_security_constraint": "maritime_route_disruption",
    "oil_shipping_security_constraint": "maritime_route_disruption",
    "energy_chokepoint_security_constraint": "maritime_route_disruption",
    "energy_shipping_sanctions_route_constraint": "maritime_route_disruption",
    "semiconductor_input_access_constraint": "strategic_technology_downstream_exposure",
    "semiconductor_strategic_downstream_exposure": "strategic_technology_downstream_exposure",
}

# Backward-compatible aliases retained for development diagnostics.
REVIEW_CANONICAL_CONTEXT_FAMILIES = CANONICAL_CONTEXT_FAMILIES


@dataclass(frozen=True)
class CompatibilityDecision:
    """Three-state mechanism compatibility decision for one support case."""

    status: str
    reason: str
    match_type: str = "incompatible"


def canonical_family(canonical_context: str | None) -> str:
    """Return the v1 family for a fine-grained canonical context."""

    if _unknown(canonical_context):
        return "unknown"
    return CANONICAL_CONTEXT_FAMILIES.get(str(canonical_context), str(canonical_context))


def mechanism_compatibility(
    current_context: dict[str, Any] | None,
    supporting_context: dict[str, Any] | None,
) -> CompatibilityDecision:
    """Compare current event/node context with one historical node context.

    The v1 rule is deterministic and conservative:

    - Missing required context returns ``insufficient_context``.
    - A contextual-background current or supporting node is incompatible.
    - Exact canonical context match is compatible.
    - Shared canonical mechanism family is compatible.
    - Same active role family and same constraint type is compatible.
    - Same affected node alone is never sufficient.
    """

    if not current_context or not supporting_context:
        return CompatibilityDecision(
            INSUFFICIENT_CONTEXT,
            "missing current or supporting transmission context",
            "insufficient_context",
        )

    missing = [
        field
        for field in ("canonical_context", "constraint_type", "target_node_role")
        if _unknown(current_context.get(field)) or _unknown(supporting_context.get(field))
    ]
    if missing:
        return CompatibilityDecision(
            INSUFFICIENT_CONTEXT,
            f"missing required fields: {', '.join(missing)}",
            "insufficient_context",
        )

    current_role = str(current_context.get("target_node_role"))
    support_role = str(supporting_context.get("target_node_role"))
    if support_role == BACKGROUND_ROLE:
        return CompatibilityDecision(
            INCOMPATIBLE,
            "supporting node is contextual background, not a mechanism vote",
            "background",
        )
    if current_role == BACKGROUND_ROLE:
        return CompatibilityDecision(
            INCOMPATIBLE,
            "current node is contextual background, not a support target",
            "background",
        )
    if current_role not in ACTIVE_ROLES or support_role not in ACTIVE_ROLES:
        return CompatibilityDecision(
            INSUFFICIENT_CONTEXT,
            "target node role is not in the controlled active-role vocabulary",
            "insufficient_context",
        )

    current_canonical = str(current_context.get("canonical_context"))
    support_canonical = str(supporting_context.get("canonical_context"))
    if current_canonical == support_canonical:
        return CompatibilityDecision(
            COMPATIBLE,
            "same canonical transmission context",
            "exact",
        )

    if canonical_family(current_canonical) == canonical_family(support_canonical):
        return CompatibilityDecision(
            COMPATIBLE,
            "same canonical transmission-context family",
            "canonical_family",
        )

    if (
        current_context.get("constraint_type") == supporting_context.get("constraint_type")
        and _active_role_family(current_role) == _active_role_family(support_role)
    ):
        return CompatibilityDecision(
            COMPATIBLE,
            "same constraint type and compatible active node-role family",
            "role_constraint",
        )

    return CompatibilityDecision(
        INCOMPATIBLE,
        "canonical context, role families, and constraints do not match",
        "incompatible",
    )


def support_diagnostics(
    current_context: dict[str, Any] | None,
    supporting_contexts: list[dict[str, Any]],
    minimum_support: int = COMPATIBLE_SUPPORT_THRESHOLD,
) -> dict[str, Any]:
    """Summarize mechanism-compatible support for one event/node instance."""

    decisions = [
        {
            "case_id": context.get("case_id", ""),
            "status": (decision := mechanism_compatibility(current_context, context)).status,
            "reason": decision.reason,
            "match_type": decision.match_type,
        }
        for context in supporting_contexts
    ]
    compatible = [row for row in decisions if row["status"] == COMPATIBLE]
    incompatible = [row for row in decisions if row["status"] == INCOMPATIBLE]
    insufficient = [
        row for row in decisions if row["status"] == INSUFFICIENT_CONTEXT
    ]

    exact = [row["case_id"] for row in compatible if row["match_type"] == "exact"]
    family = [
        row["case_id"] for row in compatible
        if row["match_type"] == "canonical_family"
    ]

    return {
        "raw_support_count": len({context.get("case_id", "") for context in supporting_contexts}),
        "compatible_support_count": len({row["case_id"] for row in compatible}),
        "incompatible_support_count": len({row["case_id"] for row in incompatible}),
        "insufficient_context_count": len({row["case_id"] for row in insufficient}),
        "exact_support_count": len(set(exact)),
        "canonical_family_support_count": len(set(family)),
        "compatible_case_ids": sorted({row["case_id"] for row in compatible}),
        "incompatible_case_ids": sorted({row["case_id"] for row in incompatible}),
        "insufficient_context_case_ids": sorted({row["case_id"] for row in insufficient}),
        "candidate_under_raw_rule": len({context.get("case_id", "") for context in supporting_contexts}) >= minimum_support,
        "candidate_under_structured_rule": len({row["case_id"] for row in compatible}) >= minimum_support,
        "case_decisions": decisions,
    }


def mechanism_compatibility_with_family_review(
    current_context: dict[str, Any] | None,
    supporting_context: dict[str, Any] | None,
) -> CompatibilityDecision:
    """Backward-compatible name for the v1 compatibility rule."""

    return mechanism_compatibility(current_context, supporting_context)


def support_diagnostics_with_family_review(
    current_context: dict[str, Any] | None,
    supporting_contexts: list[dict[str, Any]],
    minimum_support: int = COMPATIBLE_SUPPORT_THRESHOLD,
) -> dict[str, Any]:
    """Backward-compatible name for v1 support diagnostics."""

    return support_diagnostics(current_context, supporting_contexts, minimum_support)


def _active_role_family(role: str) -> str:
    if role in ACTIVE_ROLES:
        return "active"
    return role


def _unknown(value: Any) -> bool:
    return value in UNKNOWN_VALUES
