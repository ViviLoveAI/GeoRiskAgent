"""Create and audit the versioned TransmissionContext v1 sidecar artifact.

This migration is conservative: it preserves explicitly enriched development
contexts and adds only deterministic proposals that can be justified from the
existing historical case fields using the frozen TransmissionContext v1
vocabulary. It does not mutate ``data/historical_cases.json`` and does not
change retrieval text, transmission chains, CAR logic, or held-out artifacts.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.validate_mechanism_freeze_candidate import EXPANDED_CASE_CONTEXTS
from src.config import HISTORICAL_CASES_PATH, TRANSMISSION_CONTEXT_V1_PATH
from src.mechanism_context import (
    CANONICAL_FAMILY_VERSION,
    MECHANISM_COMPATIBILITY_VERSION,
    REQUIRED_CONTEXT_FIELDS,
    TRANSMISSION_CONTEXT_VERSION,
    UNKNOWN_VALUES,
)

OUTPUT_DIR = Path("data/topk_sensitivity_v4")
AUDIT_OUTPUT = OUTPUT_DIR / "full_kb_context_migration_audit.csv"
SUMMARY_OUTPUT = OUTPUT_DIR / "full_kb_context_migration_audit_summary.json"
QUALITY_OUTPUT = OUTPUT_DIR / "full_kb_context_quality_review.csv"

MIGRATION_METHOD = "full_kb_conservative_rule_migration_v1"
VOCAB_GAP = "vocabulary_gap_candidate"
AMBIGUOUS = "ambiguous"
INSUFFICIENT = "insufficient_source_evidence"
RESOLVABLE = "resolvable"
ALREADY = "already_migrated"


def main() -> None:
    cases = _load_json(HISTORICAL_CASES_PATH)
    audit_rows = build_migration_audit(cases)
    artifact = build_transmission_context_artifact(cases, audit_rows)
    TRANSMISSION_CONTEXT_V1_PATH.write_text(json.dumps(artifact, indent=2, sort_keys=True))
    _write_csv(AUDIT_OUTPUT, audit_rows)
    quality_rows = _quality_review_rows(audit_rows)
    _write_csv(QUALITY_OUTPUT, quality_rows)
    summary = {
        **artifact["coverage_summary"],
        "migration_status_counts": dict(Counter(row["migration_status"] for row in audit_rows)),
        "coverage_by_node": _coverage_by(audit_rows, "node"),
        "coverage_by_event_type": _coverage_by(audit_rows, "event_type"),
        "quality_review_rows": len(quality_rows),
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(artifact["coverage_summary"], indent=2, sort_keys=True))


def build_migration_audit(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one migration audit row per historical case/node."""

    rows: list[dict[str, Any]] = []
    for case in cases:
        for node in case.get("supply_chain_nodes", []):
            if not node:
                continue
            existing = EXPANDED_CASE_CONTEXTS.get((case["event_id"], node))
            if existing:
                proposed = dict(existing)
                status = ALREADY
                evidence_basis = "existing development-enriched node context"
                confidence = "high"
                notes = "Preserved without modification."
            else:
                proposal = _propose_context(case, node)
                proposed = proposal["context"]
                status = proposal["status"]
                evidence_basis = proposal["evidence_basis"]
                confidence = proposal["confidence"]
                notes = proposal["notes"]

            rows.append({
                "case_id": case["event_id"],
                "event_type": case.get("event_type", ""),
                "node": node,
                "migration_status": status,
                "existing_context": json.dumps(existing or {}, sort_keys=True),
                "proposed_context": json.dumps(proposed or {}, sort_keys=True),
                "missing_fields": ";".join(_missing_fields(proposed)),
                "evidence_basis": evidence_basis,
                "confidence": confidence,
                "notes": notes,
            })
    return rows


def build_transmission_context_artifact(
    cases: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the sidecar artifact payload from explicit enriched contexts."""

    if audit_rows is None:
        audit_rows = build_migration_audit(cases)

    contexts_by_case: dict[str, list[dict[str, Any]]] = {}
    for row in audit_rows:
        if row["migration_status"] not in {ALREADY, RESOLVABLE}:
            continue
        context = json.loads(row["proposed_context"])
        if not _informative(context):
            continue
        case_id = row["case_id"]
        contexts_by_case.setdefault(case_id, []).append({
            **context,
            "transmission_context_version": TRANSMISSION_CONTEXT_VERSION,
            "migration_method": "expanded_development_enrichment"
            if row["migration_status"] == ALREADY
            else MIGRATION_METHOD,
            "evidence_basis": row["evidence_basis"],
        })

    all_case_nodes = {
        (case["event_id"], node)
        for case in cases
        for node in case.get("supply_chain_nodes", [])
        if node
    }
    covered_nodes = {
        (case_id, context["node"])
        for case_id, contexts in contexts_by_case.items()
        for context in contexts
        if _informative(context)
    }

    return {
        "diagnostic_only": False,
        "artifact_role": "production_candidate_sidecar",
        "transmission_context_version": TRANSMISSION_CONTEXT_VERSION,
        "canonical_family_version": CANONICAL_FAMILY_VERSION,
        "mechanism_compatibility_version": MECHANISM_COMPATIBILITY_VERSION,
        "source_historical_cases_path": str(HISTORICAL_CASES_PATH),
        "migration_policy": (
            "Explicit development-enriched contexts are preserved. Additional "
            "case/node contexts are migrated only when existing historical "
            "case fields support a frozen-vocabulary TransmissionContext v1. "
            "Unresolved, ambiguous, and vocabulary-gap nodes are not filled."
        ),
        "coverage_summary": {
            "historical_cases_total": len(cases),
            "historical_case_nodes_total": len(all_case_nodes),
            "migrated_cases": len(contexts_by_case),
            "migrated_case_nodes": len(covered_nodes),
            "historical_case_node_coverage": round(len(covered_nodes) / len(all_case_nodes), 6)
            if all_case_nodes else 0.0,
            "field_coverage": _field_coverage(contexts_by_case),
            "top_unmigrated_nodes": _top_unmigrated_nodes(cases, covered_nodes),
            "migration_status_counts": dict(Counter(row["migration_status"] for row in audit_rows)),
        },
        "cases": [
            {
                "case_id": case_id,
                "transmission_contexts": sorted(contexts, key=lambda row: row["node"]),
            }
            for case_id, contexts in sorted(contexts_by_case.items())
        ],
    }


def _propose_context(case: dict[str, Any], node: str) -> dict[str, Any]:
    text = _case_text(case)
    event_type = str(case.get("event_type", "")).lower()
    chain = " ".join(case.get("transmission_chain", [])).lower()
    basis = "event_type, supply_chain_nodes, affected_asset_types, affected_assets, transmission_chain, summary"

    if _has_any(text, ["sanction", "swift", "payment", "financial"]) and node in {"financial_sanctions", "payment_networks"}:
        return _proposal(node, "sanctions", "financing_constraint", _driver(case, "financial_access_restriction"), "direct_disruption_target", "financial_sanctions_trade_finance_constraint", basis)

    if node == "energy" and _has(text, "sanction") and _has_any(text, ["oil", "gas", "energy", "export"]):
        constraint = "financing_constraint" if _has_any(text, ["swift", "payment", "finance"]) else "trade_access_restriction"
        canonical = "energy_trade_finance_constraint" if constraint == "financing_constraint" else "energy_trade_access_constraint"
        return _proposal(node, "sanctions", constraint, _driver(case, "energy_trade_restriction"), "downstream_exposure", canonical, basis)

    if node in {"oil_shipping", "lng_shipping"} and _has_any(text, ["sanction", "shipping", "tanker", "lng", "oil"]):
        canonical = "energy_shipping_sanctions_route_constraint" if node == "lng_shipping" else "oil_shipping_security_constraint"
        shock = "sanctions" if _has(text, "sanction") else "military_escalation"
        return _proposal(node, shock, "route_disruption", _driver(case, f"{node}_restriction"), "direct_disruption_target", canonical, basis)

    if node == "marine_insurance" and _has_any(text, ["insurance", "tanker", "shipping", "price-cap", "sanction"]):
        canonical = "energy_shipping_insurance_constraint" if _has_any(text, ["oil", "lng", "energy"]) else "food_shipping_insurance_constraint"
        shock = "sanctions" if _has(text, "sanction") else "military_escalation"
        return _proposal(node, shock, "insurance_constraint", _driver(case, "shipping_insurance_constraint"), "financing_or_insurance_channel", canonical, basis)

    if node in {"maritime_chokepoint", "container_shipping", "panama_canal"} and _has_any(text, ["shipping", "canal", "chokepoint", "maritime", "port", "route", "airspace"]):
        shock = "physical_disruption" if _has_any(text, ["blockage", "drought", "closure", "strike"]) else "military_escalation"
        canonical = "maritime_route_capacity_constraint" if _has_any(text, ["blockage", "drought", "capacity", "closure"]) else "maritime_route_security_constraint"
        return _proposal(node, shock, "route_disruption", _driver(case, "maritime_route_disruption"), "direct_disruption_target", canonical, basis)

    if node in {"logistics", "freight_routes", "ports", "trade_lanes"}:
        if _has_any(text, ["cyber", "ransomware"]) and node in {"logistics", "ports"}:
            role = "direct_disruption_target" if node == "ports" else "transmission_channel"
            canonical = "port_cyber_capacity_constraint" if node == "ports" else "logistics_cyber_capacity_constraint"
            return _proposal(node, "cyber_disruption", "capacity_reduction", _driver(case, "cyber_operational_disruption"), role, canonical, basis)
        if _has_any(text, ["tariff", "customs", "carbon border"]) and node == "trade_lanes":
            return _proposal(node, "tariff" if _has(text, "tariff") else "regulatory_restriction", "trade_access_restriction", _driver(case, "trade_compliance_constraint"), "compliance_channel", "tariff_trade_compliance_constraint", basis)
        if _has_any(text, ["shipping", "canal", "chokepoint", "maritime", "route", "port", "airspace"]):
            canonical = "maritime_route_capacity_constraint" if _has_any(text, ["blockage", "drought", "capacity", "closure", "strike"]) else "maritime_route_security_constraint"
            shock = "physical_disruption" if _has_any(text, ["blockage", "drought", "closure", "strike"]) else "military_escalation"
            return _proposal(node, shock, "route_disruption", _driver(case, "route_logistics_disruption"), "transmission_channel", canonical, basis)

    if node == "customs" and _has_any(text, ["tariff", "customs", "export control", "carbon border", "restriction"]):
        shock = "tariff" if _has(text, "tariff") else "regulatory_restriction"
        return _proposal(node, shock, "compliance_constraint", _driver(case, "customs_compliance_constraint"), "compliance_channel", "tariff_customs_compliance_constraint", basis)

    if node in {"critical_minerals", "rare_earths", "gallium_germanium_graphite", "graphite"} and _has_any(text, ["mineral", "rare earth", "graphite", "gallium", "germanium", "nickel", "cobalt", "lithium", "uranium"]):
        canonical = "critical_material_compliance_constraint" if _has_any(text, ["license", "licensing", "compliance"]) else "critical_material_input_constraint"
        return _proposal(node, "export_restriction", "input_access_restriction", _driver(case, "critical_material_access_constraint"), "upstream_input", canonical, basis)

    if node in {"battery_materials", "fertilizer"} and _has_any(text, ["fertilizer", "potash", "lithium", "nickel", "cobalt", "graphite"]):
        canonical = "agricultural_input_constraint" if node == "fertilizer" else "battery_material_input_constraint"
        constraint = "input_shortage" if node == "fertilizer" else "input_access_restriction"
        return _proposal(node, "export_restriction", constraint, _driver(case, f"{node}_input_constraint"), "upstream_input", canonical, basis)

    if node == "agriculture" and _has_any(text, ["fertilizer", "potash", "crop input"]):
        return _proposal(node, "export_restriction" if _has(text, "export") else "sanctions", "input_shortage", _driver(case, "agricultural_input_constraint"), "downstream_exposure", "agricultural_input_constraint", basis)
    if node in {"grain_exports", "food_export_controls", "agriculture"} and _has_any(text, ["wheat", "rice", "grain", "food export", "export ban"]):
        canonical = "food_export_trade_constraint" if node in {"grain_exports", "food_export_controls"} else "agricultural_export_trade_constraint"
        return _proposal(node, "export_restriction", "trade_access_restriction", _driver(case, "food_export_restriction"), "direct_disruption_target" if node != "agriculture" else "downstream_exposure", canonical, basis)

    if node in {"semiconductor_equipment", "ai_chips", "foundry", "eda_software", "taiwan_semiconductor_supply"} and _has_any(text, ["semiconductor", "chip", "asml", "lithography", "foundry"]):
        canonical = "semiconductor_export_control_constraint"
        role = "direct_disruption_target" if node in {"semiconductor_equipment", "ai_chips", "eda_software"} else "transmission_channel"
        return _proposal(node, "export_restriction", "trade_access_restriction", _driver(case, "semiconductor_export_control"), role, canonical, basis)

    if node in {"defense", "aerospace_supply_chain", "aviation"}:
        if _has_any(text, ["semiconductor", "chip", "taiwan"]):
            return _proposal(node, "military_escalation" if _has(text, "taiwan") else "export_restriction", "security_risk" if _has(text, "taiwan") else "input_access_restriction", _driver(case, "strategic_technology_dependency"), "downstream_strategic_exposure", "semiconductor_strategic_downstream_exposure", basis)
        if _has_any(text, ["defense", "aerospace", "airspace", "missile", "military"]):
            canonical = "airspace_route_disruption" if node == "aviation" and _has(text, "airspace") else "aerospace_defense_procurement_constraint"
            constraint = "route_disruption" if canonical == "airspace_route_disruption" else "security_risk"
            return _proposal(node, "military_escalation", constraint, _driver(case, f"{node}_security_constraint"), "direct_disruption_target" if node == "aviation" else "downstream_exposure", canonical, basis)

    if node in {"refining", "petrochemicals"} and _has_any(text, ["oil", "gas", "feedstock", "refin"]):
        canonical = "refining_feedstock_constraint" if node == "refining" else "petrochemical_feedstock_constraint"
        return _proposal(node, "sanctions" if _has(text, "sanction") else "physical_disruption", "input_shortage", _driver(case, f"{node}_feedstock_constraint"), "downstream_exposure", canonical, basis)

    if node == "pipeline_infrastructure" and _has_any(text, ["pipeline", "nord stream", "colonial"]):
        return _proposal(node, "cyber_disruption" if _has_any(text, ["cyber", "ransomware"]) else "physical_disruption", "capacity_reduction", _driver(case, "pipeline_capacity_disruption"), "direct_disruption_target", "energy_distribution_cyber_capacity_constraint", basis)

    if node in {"data_centers", "cyber_infrastructure"} and _has_any(text, ["cyber", "data center", "power"]):
        return _proposal(node, "cyber_disruption", "capacity_reduction", _driver(case, "cyber_infrastructure_disruption"), "direct_disruption_target", "logistics_cyber_capacity_constraint", basis)

    if node in {"manufacturing_inputs", "nuclear_fuel", "uranium"}:
        return _unresolved(VOCAB_GAP, "No frozen canonical_context precisely represents this node's mechanism.", "medium")

    if not chain and not event_type:
        return _unresolved(INSUFFICIENT, "Historical case lacks enough structured evidence for this node.", "low")

    return _unresolved(AMBIGUOUS, "Existing frozen vocabulary and raw case fields do not support a precise node-level context.", "low")


def _proposal(
    node: str,
    shock_type: str,
    constraint_type: str,
    upstream_driver: str,
    target_node_role: str,
    canonical_context: str,
    evidence_basis: str,
) -> dict[str, Any]:
    return {
        "status": RESOLVABLE,
        "context": {
            "node": node,
            "shock_type": shock_type,
            "constraint_type": constraint_type,
            "upstream_driver": upstream_driver,
            "target_node_role": target_node_role,
            "canonical_context": canonical_context,
        },
        "evidence_basis": evidence_basis,
        "confidence": "medium",
        "notes": "Conservative frozen-vocabulary proposal from existing historical fields.",
    }


def _unresolved(status: str, notes: str, confidence: str) -> dict[str, Any]:
    return {
        "status": status,
        "context": {},
        "evidence_basis": "",
        "confidence": confidence,
        "notes": notes,
    }


def _informative(context: dict[str, Any]) -> bool:
    return all(context.get(field) not in UNKNOWN_VALUES for field in REQUIRED_CONTEXT_FIELDS)


def _field_coverage(contexts_by_case: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    contexts = [
        context
        for contexts in contexts_by_case.values()
        for context in contexts
    ]
    return {
        field: {
            "informative": sum(context.get(field) not in UNKNOWN_VALUES for context in contexts),
            "total": len(contexts),
            "coverage": round(
                sum(context.get(field) not in UNKNOWN_VALUES for context in contexts) / len(contexts),
                6,
            )
            if contexts else 0.0,
        }
        for field in REQUIRED_CONTEXT_FIELDS
    }


def _top_unmigrated_nodes(
    cases: list[dict[str, Any]],
    covered_nodes: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for case in cases:
        for node in case.get("supply_chain_nodes", []):
            if (case["event_id"], node) not in covered_nodes:
                counter[node] += 1
    return [
        {"node": node, "missing_case_nodes": count}
        for node, count in counter.most_common(20)
    ]


def _coverage_by(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[field]), []).append(row)
    result = {}
    for key, group in sorted(groups.items()):
        informative = sum(row["migration_status"] in {ALREADY, RESOLVABLE} for row in group)
        result[key] = {
            "total": len(group),
            "informative": informative,
            "coverage": round(informative / len(group), 6) if group else 0.0,
            "status_counts": dict(Counter(row["migration_status"] for row in group)),
        }
    return result


def _quality_review_rows(audit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_nodes = {
        "energy",
        "logistics",
        "trade_lanes",
        "manufacturing_inputs",
        "customs",
        "freight_routes",
    }
    rows: list[dict[str, Any]] = []
    for node in sorted(priority_nodes):
        node_rows = [
            row for row in audit_rows
            if row["node"] == node and row["migration_status"] in {ALREADY, RESOLVABLE}
        ][:6]
        for row in node_rows:
            context = json.loads(row["proposed_context"])
            rows.append({
                "case_id": row["case_id"],
                "node": node,
                "migration_status": row["migration_status"],
                "canonical_context": context.get("canonical_context", ""),
                "constraint_type": context.get("constraint_type", ""),
                "upstream_driver": context.get("upstream_driver", ""),
                "target_node_role": context.get("target_node_role", ""),
                "quality_check": _quality_check(context),
                "notes": (
                    "Sampled priority-node context. Review checks frozen-vocabulary "
                    "fit and whether context is node-specific rather than copied."
                ),
            })
        unresolved = [
            row for row in audit_rows
            if row["node"] == node and row["migration_status"] not in {ALREADY, RESOLVABLE}
        ][:3]
        for row in unresolved:
            rows.append({
                "case_id": row["case_id"],
                "node": node,
                "migration_status": row["migration_status"],
                "canonical_context": "",
                "constraint_type": "",
                "upstream_driver": "",
                "target_node_role": "",
                "quality_check": "unresolved_preserved",
                "notes": row["notes"],
            })
    return rows


def _quality_check(context: dict[str, Any]) -> str:
    if not _informative(context):
        return "non_informative"
    return "plausible_node_specific_context"


def _missing_fields(context: dict[str, Any] | None) -> list[str]:
    if not context:
        return REQUIRED_CONTEXT_FIELDS
    return [
        field for field in REQUIRED_CONTEXT_FIELDS
        if context.get(field) in UNKNOWN_VALUES
    ]


def _case_text(case: dict[str, Any]) -> str:
    fields = [
        case.get("event_id", ""),
        case.get("event_name", ""),
        case.get("event_type", ""),
        case.get("summary", ""),
        *case.get("industries", []),
        *case.get("supply_chain_nodes", []),
        *case.get("affected_asset_types", []),
        *case.get("affected_assets", []),
        *case.get("transmission_chain", []),
    ]
    return " ".join(str(field).lower() for field in fields)


def _driver(case: dict[str, Any], fallback: str) -> str:
    chain = case.get("transmission_chain", [])
    if chain:
        return _slug(str(chain[0]))[:80]
    return _slug(str(case.get("event_type", fallback)))[:80] or fallback


def _slug(value: str) -> str:
    result = []
    previous = ""
    for char in value.lower():
        if char.isalnum():
            result.append(char)
            previous = char
        elif previous != "_":
            result.append("_")
            previous = "_"
    return "".join(result).strip("_")


def _has(text: str, needle: str) -> bool:
    return needle in text


def _has_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        import csv

        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


if __name__ == "__main__":
    main()
