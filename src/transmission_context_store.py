"""Load and project V4 node-level transmission contexts.

The production-candidate V4 mechanism support path reads historical node
contexts from a versioned sidecar artifact rather than mutating the historical
knowledge base. Current-event contexts are projected deterministically from the
already-produced ``EventAnalysis`` and the target node.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.config import TRANSMISSION_CONTEXT_V1_PATH
from src.mechanism_context import TRANSMISSION_CONTEXT_VERSION
from src.schemas import EventAnalysis


def load_historical_contexts(
    path: Path = TRANSMISSION_CONTEXT_V1_PATH,
) -> dict[tuple[str, str], dict[str, str]]:
    """Load versioned historical case/node contexts keyed by case id and node."""

    return _load_historical_contexts_cached(str(path))


@lru_cache(maxsize=4)
def _load_historical_contexts_cached(path_str: str) -> dict[tuple[str, str], dict[str, str]]:
    path = Path(path_str)
    if not path.exists():
        return {}

    payload = json.loads(path.read_text())
    if payload.get("transmission_context_version") != TRANSMISSION_CONTEXT_VERSION:
        raise ValueError(
            "transmission context artifact version mismatch: "
            f"{payload.get('transmission_context_version')}"
        )

    contexts: dict[tuple[str, str], dict[str, str]] = {}
    for case in payload.get("cases", []):
        case_id = str(case.get("case_id", ""))
        for context in case.get("transmission_contexts", []):
            node = str(context.get("node", ""))
            if case_id and node:
                contexts[(case_id, node)] = _context_payload(context)
    return contexts


def project_current_event_context(
    event: EventAnalysis,
    node: str,
) -> dict[str, str] | None:
    """Project a node-specific TransmissionContext v1 for a current event.

    Projection is intentionally conservative. It returns ``None`` when the
    current event and node semantics do not provide a stable context.
    """

    text = _event_text(event)
    if node in {"grain_exports", "food_export_controls"} and _has(text, "export"):
        return _ctx(
            node,
            "export_restriction",
            "trade_access_restriction",
            "food_export_restriction",
            "direct_disruption_target",
            "food_export_trade_constraint",
        )
    if node == "agriculture" and _has(text, "export") and _has_any(text, ["food", "grain", "wheat", "rice"]):
        return _ctx(
            node,
            "export_restriction",
            "trade_access_restriction",
            "food_export_restriction",
            "downstream_exposure",
            "agricultural_export_trade_constraint",
        )
    if node == "energy" and _has_any(text, ["sanction", "export", "oil", "energy"]):
        return _ctx(
            node,
            "sanctions" if _has(text, "sanction") else "export_restriction",
            "trade_access_restriction",
            "restricted_energy_exports",
            "downstream_exposure",
            "energy_trade_access_constraint",
        )
    if node == "financial_sanctions" and _has(text, "sanction"):
        return _ctx(
            node,
            "sanctions",
            "financing_constraint",
            "financial_access_restriction",
            "direct_disruption_target",
            "financial_sanctions_trade_finance_constraint",
        )
    if node in {"container_shipping", "maritime_chokepoint"} and _has_any(text, ["shipping", "route", "sea", "canal"]):
        return _ctx(
            node,
            "military_escalation" if _has_any(text, ["attack", "conflict", "military"]) else "physical_disruption",
            "route_disruption",
            "maritime_route_disruption",
            "direct_disruption_target",
            "maritime_route_security_constraint",
        )
    if node == "marine_insurance" and _has_any(text, ["insurance", "shipping", "sanction"]):
        return _ctx(
            node,
            "sanctions" if _has(text, "sanction") else "military_escalation",
            "insurance_constraint",
            "shipping_insurance_constraint",
            "financing_or_insurance_channel",
            "energy_shipping_insurance_constraint"
            if _has_any(text, ["energy", "lng", "oil"])
            else "maritime_route_security_constraint",
        )
    if node == "oil_shipping" and _has_any(text, ["oil", "tanker", "shipping"]):
        return _ctx(
            node,
            "sanctions" if _has(text, "sanction") else "military_escalation",
            "route_disruption",
            "oil_shipping_compliance_or_security_risk",
            "transmission_channel",
            "oil_shipping_security_constraint",
        )
    if node == "lng_shipping" and _has_any(text, ["lng", "gas", "shipping"]):
        return _ctx(
            node,
            "sanctions" if _has(text, "sanction") else "physical_disruption",
            "route_disruption",
            "lng_shipping_restriction",
            "direct_disruption_target",
            "energy_shipping_sanctions_route_constraint",
        )
    if node in {"battery_materials", "critical_minerals"} and _has_any(text, ["graphite", "lithium", "nickel", "cobalt", "mineral"]):
        return _ctx(
            node,
            "export_restriction",
            "input_access_restriction",
            "critical_material_export_controls",
            "upstream_input",
            "critical_material_input_constraint"
            if node == "critical_minerals"
            else "battery_material_input_constraint",
        )
    if node == "semiconductor_equipment" and _has_any(text, ["semiconductor", "chip"]):
        return _ctx(
            node,
            "export_restriction",
            "trade_access_restriction",
            "advanced_tool_export_controls",
            "direct_disruption_target",
            "semiconductor_export_control_constraint",
        )
    if node == "defense" and _has_any(text, ["semiconductor", "chip"]):
        return _ctx(
            node,
            "export_restriction",
            "input_access_restriction",
            "advanced_chip_export_controls",
            "downstream_strategic_exposure",
            "semiconductor_strategic_downstream_exposure",
        )
    if node in {"customs", "trade_lanes"} and _has_any(text, ["tariff", "customs"]):
        return _ctx(
            node,
            "tariff",
            "compliance_constraint" if node == "customs" else "trade_access_restriction",
            "tariff_and_customs_review",
            "compliance_channel",
            "tariff_customs_compliance_constraint"
            if node == "customs"
            else "tariff_trade_compliance_constraint",
        )
    if node in {"ports", "logistics"} and _has_any(text, ["port", "cyber"]):
        return _ctx(
            node,
            "cyber_disruption",
            "capacity_reduction",
            "port_operational_shutdown",
            "direct_disruption_target" if node == "ports" else "transmission_channel",
            "port_cyber_capacity_constraint"
            if node == "ports"
            else "logistics_cyber_capacity_constraint",
        )

    return None


def missing_context(node: str) -> dict[str, str]:
    """Return an explicit unresolved node-level context."""

    return _ctx(node, "unknown", "unknown", "unknown", "unknown", "unknown")


def _context_payload(context: dict[str, Any]) -> dict[str, str]:
    return {
        "node": str(context.get("node", "")),
        "shock_type": str(context.get("shock_type", "unknown")),
        "constraint_type": str(context.get("constraint_type", "unknown")),
        "upstream_driver": str(context.get("upstream_driver", "unknown")),
        "target_node_role": str(context.get("target_node_role", "unknown")),
        "canonical_context": str(context.get("canonical_context", "unknown")),
    }


def _ctx(
    node: str,
    shock_type: str,
    constraint_type: str,
    upstream_driver: str,
    target_node_role: str,
    canonical_context: str,
) -> dict[str, str]:
    return {
        "node": node,
        "shock_type": shock_type,
        "constraint_type": constraint_type,
        "upstream_driver": upstream_driver,
        "target_node_role": target_node_role,
        "canonical_context": canonical_context,
    }


def _event_text(event: EventAnalysis) -> str:
    parts = [
        event.title,
        event.summary,
        event.event_type,
        event.shock_direction,
        *event.industries,
        *event.supply_chain_nodes,
        *event.risk_factors,
    ]
    return " ".join(part.lower() for part in parts if part)


def _has(text: str, needle: str) -> bool:
    """Return true when a keyword appears as a lexical token or phrase."""

    if not needle:
        return False

    escaped = re.escape(needle.lower())
    suffix = "" if needle.lower().endswith("s") else "(?:s|ed|ing)?"
    pattern = rf"(?<![a-z0-9]){escaped}{suffix}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _has_any(text: str, needles: list[str]) -> bool:
    return any(_has(text, needle) for needle in needles)
