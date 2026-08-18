"""Build a controlled offline transmission-context enrichment prototype.

This script is diagnostic-only. It creates development artifacts under
data/topk_sensitivity_v4 and does not modify production historical cases,
retrieval, transmission building, evidence grading, market mapping, ranking, or
CAR outputs.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.validation.transmission_context import support_diagnostics


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
ERROR_PROTOTYPE = OUTPUT_DIR / "transmission_context_error_case_prototype.json"
RULE_AUDIT = OUTPUT_DIR / "mechanism_consistency_rule_audit.csv"
HISTORICAL_CASES = Path("data/historical_cases.json")

CONTROLLED_CASES_OUTPUT = OUTPUT_DIR / "controlled_transmission_context_cases.json"
AUDIT_OUTPUT = OUTPUT_DIR / "mechanism_compatible_support_audit.csv"
SUMMARY_OUTPUT = OUTPUT_DIR / "mechanism_compatible_support_summary.json"


CLEAN_CONTROL_KEYS = {
    ("eval_cyber_port_pipeline_disruption", "maritime_chokepoint"),
    ("eval_dutch_asml_export_controls", "defense"),
    ("eval_food_export_grain_restriction", "marine_insurance"),
    ("eval_middle_east_oil_infrastructure_attack", "defense"),
    ("eval_middle_east_oil_infrastructure_attack", "marine_insurance"),
    ("eval_natural_gas_fertilizer_shock", "petrochemicals"),
    ("eval_natural_gas_fertilizer_shock", "refining"),
    ("eval_oil_shipping_chokepoint", "marine_insurance"),
    ("eval_panama_canal_drought", "container_shipping"),
    ("eval_red_sea_shipping_disruption", "marine_insurance"),
}


MANUAL_CLEAN_CONTROLS = [
    {
        "event_id": "eval_panama_canal_drought",
        "node": "container_shipping",
        "audit_label": "consistent",
        "rule6_result": "keep",
        "supporting_case_ids": [
            "case_panama_canal_drought_shipping_capacity",
            "case_2021_suez_blockage",
        ],
    },
    {
        "event_id": "eval_oil_shipping_chokepoint",
        "node": "oil_shipping",
        "audit_label": "consistent",
        "rule6_result": "keep",
        "supporting_case_ids": [
            "case_hormuz_tanker_tensions",
            "case_1987_1988_tanker_war_reflagging",
            "case_2023_red_sea_attacks",
        ],
    },
    {
        "event_id": "eval_middle_east_oil_infrastructure_attack",
        "node": "refining",
        "audit_label": "consistent",
        "rule6_result": "keep",
        "supporting_case_ids": [
            "case_middle_east_oil_supply_disruption",
            "case_opec_production_cut_policy_shock",
        ],
    },
    {
        "event_id": "eval_natural_gas_fertilizer_shock",
        "node": "petrochemicals",
        "audit_label": "consistent",
        "rule6_result": "keep",
        "supporting_case_ids": [
            "case_2022_gas_fertilizer_shock",
            "case_russia_ukraine_energy_shock",
        ],
    },
    {
        "event_id": "eval_natural_gas_fertilizer_shock",
        "node": "energy",
        "audit_label": "consistent",
        "rule6_result": "keep",
        "supporting_case_ids": [
            "case_2022_gas_fertilizer_shock",
            "case_russia_ukraine_energy_shock",
        ],
    },
    {
        "event_id": "eval_us_china_tariffs",
        "node": "trade_lanes",
        "audit_label": "mixed",
        "rule6_result": "keep",
        "supporting_case_ids": [
            "case_2018_2019_us_china_tariffs",
            "case_2024_ev_tariff_escalation_china",
        ],
    },
    {
        "event_id": "eval_red_sea_shipping_disruption",
        "node": "maritime_chokepoint",
        "audit_label": "consistent",
        "rule6_result": "keep",
        "supporting_case_ids": [
            "case_2023_red_sea_attacks",
            "case_2008_somali_piracy_gulf_of_aden",
        ],
    },
]


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


CURRENT_CONTEXTS: dict[tuple[str, str], dict[str, str]] = {
    ("eval_defense_supply_chain_escalation", "aviation"): _ctx(
        "aviation", "regulatory_restriction", "trade_access_restriction",
        "defense_procurement_policy_dispute", "contextual_background",
        "aerospace_defense_procurement_constraint",
    ),
    ("eval_huawei_entity_list", "defense"): _ctx(
        "defense", "export_restriction", "input_access_restriction",
        "entity_list_semiconductor_supply_restriction", "contextual_background",
        "semiconductor_input_access_constraint",
    ),
    ("eval_middle_east_oil_infrastructure_attack", "logistics"): _ctx(
        "logistics", "physical_disruption", "cost_increase",
        "oil_infrastructure_damage", "downstream_exposure",
        "transport_fuel_cost_exposure",
    ),
    ("eval_semiconductor_export_controls", "defense"): _ctx(
        "defense", "export_restriction", "input_access_restriction",
        "advanced_chip_export_controls", "contextual_background",
        "semiconductor_input_access_constraint",
    ),
    ("eval_uranium_nuclear_fuel_disruption", "marine_insurance"): _ctx(
        "marine_insurance", "export_restriction", "input_access_restriction",
        "uranium_supply_restriction", "contextual_background",
        "nuclear_fuel_input_constraint",
    ),
    ("eval_uranium_nuclear_fuel_disruption", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "export_restriction", "input_access_restriction",
        "uranium_supply_restriction", "contextual_background",
        "nuclear_fuel_input_constraint",
    ),
    ("eval_dutch_asml_export_controls", "critical_minerals"): _ctx(
        "critical_minerals", "export_restriction", "input_access_restriction",
        "semiconductor_input_export_controls", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("eval_huawei_entity_list", "critical_minerals"): _ctx(
        "critical_minerals", "export_restriction", "input_access_restriction",
        "electronics_input_restriction", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("eval_semiconductor_export_controls", "critical_minerals"): _ctx(
        "critical_minerals", "export_restriction", "input_access_restriction",
        "semiconductor_input_export_controls", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("hard_semiconductor_controls_paraphrased", "critical_minerals"): _ctx(
        "critical_minerals", "export_restriction", "input_access_restriction",
        "semiconductor_input_export_controls", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("eval_cyber_port_pipeline_disruption", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "cyber_disruption", "route_disruption",
        "port_operational_disruption", "transmission_channel",
        "maritime_route_security_constraint",
    ),
    ("eval_dutch_asml_export_controls", "defense"): _ctx(
        "defense", "export_restriction", "input_access_restriction",
        "semiconductor_supply_restriction", "downstream_exposure",
        "semiconductor_input_access_constraint",
    ),
    ("eval_food_export_grain_restriction", "marine_insurance"): _ctx(
        "marine_insurance", "export_restriction", "insurance_constraint",
        "grain_shipping_insurance_risk", "financing_or_insurance_channel",
        "food_shipping_insurance_constraint",
    ),
    ("eval_middle_east_oil_infrastructure_attack", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "regional_energy_security_escalation", "downstream_exposure",
        "regional_security_context",
    ),
    ("eval_middle_east_oil_infrastructure_attack", "marine_insurance"): _ctx(
        "marine_insurance", "physical_disruption", "insurance_constraint",
        "energy_facility_attack_risk", "financing_or_insurance_channel",
        "energy_shipping_insurance_constraint",
    ),
    ("eval_middle_east_oil_infrastructure_attack", "refining"): _ctx(
        "refining", "physical_disruption", "input_shortage",
        "oil_infrastructure_damage", "upstream_input",
        "refining_feedstock_constraint",
    ),
    ("eval_natural_gas_fertilizer_shock", "petrochemicals"): _ctx(
        "petrochemicals", "physical_disruption", "input_shortage",
        "gas_feedstock_shortage", "upstream_input",
        "petrochemical_feedstock_constraint",
    ),
    ("eval_natural_gas_fertilizer_shock", "energy"): _ctx(
        "energy", "physical_disruption", "input_shortage",
        "natural_gas_supply_disruption", "upstream_input",
        "energy_feedstock_constraint",
    ),
    ("eval_natural_gas_fertilizer_shock", "refining"): _ctx(
        "refining", "physical_disruption", "input_shortage",
        "energy_feedstock_shortage", "upstream_input",
        "refining_feedstock_constraint",
    ),
    ("eval_oil_shipping_chokepoint", "oil_shipping"): _ctx(
        "oil_shipping", "military_escalation", "route_disruption",
        "tanker_security_risk", "direct_disruption_target",
        "oil_shipping_security_constraint",
    ),
    ("eval_oil_shipping_chokepoint", "marine_insurance"): _ctx(
        "marine_insurance", "military_escalation", "insurance_constraint",
        "vessel_security_risk", "financing_or_insurance_channel",
        "energy_shipping_insurance_constraint",
    ),
    ("eval_panama_canal_drought", "container_shipping"): _ctx(
        "container_shipping", "capacity_constraint", "route_disruption",
        "canal_transit_capacity_reduction", "direct_disruption_target",
        "maritime_route_capacity_constraint",
    ),
    ("eval_red_sea_shipping_disruption", "marine_insurance"): _ctx(
        "marine_insurance", "military_escalation", "insurance_constraint",
        "vessel_security_risk", "financing_or_insurance_channel",
        "maritime_route_security_constraint",
    ),
    ("eval_red_sea_shipping_disruption", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "military_escalation", "route_disruption",
        "red_sea_vessel_security_risk", "direct_disruption_target",
        "maritime_route_security_constraint",
    ),
    ("eval_us_china_tariffs", "trade_lanes"): _ctx(
        "trade_lanes", "tariff", "trade_access_restriction",
        "tariff_and_customs_review", "compliance_channel",
        "tariff_trade_compliance_constraint",
    ),
}


CASE_CONTEXTS: dict[tuple[str, str], dict[str, str]] = {
    ("case_2010_china_japan_rare_earth_embargo", "critical_minerals"): _ctx(
        "critical_minerals", "export_restriction", "input_access_restriction",
        "rare_earth_export_disruption", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("case_2021_xinjiang_forced_labor_import_restrictions", "critical_minerals"): _ctx(
        "critical_minerals", "import_restriction", "compliance_constraint",
        "supplier_traceability_review", "upstream_input",
        "critical_material_compliance_constraint",
    ),
    ("case_china_gallium_germanium_graphite_controls", "critical_minerals"): _ctx(
        "critical_minerals", "export_restriction", "input_access_restriction",
        "export_licensing_controls", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("case_2024_ev_tariff_escalation_china", "critical_minerals"): _ctx(
        "critical_minerals", "tariff", "cost_increase",
        "battery_and_ev_input_tariffs", "upstream_input",
        "critical_material_cost_constraint",
    ),
    ("case_2017_north_korea_missile_escalation", "aviation"): _ctx(
        "aviation", "military_escalation", "security_risk",
        "missile_overflight_airspace_monitoring", "transmission_channel",
        "airspace_security_disruption",
    ),
    ("case_2019_india_pakistan_airspace_closure", "aviation"): _ctx(
        "aviation", "military_escalation", "route_disruption",
        "airspace_closure", "direct_disruption_target",
        "airspace_route_disruption",
    ),
    ("case_2011_libya_civil_war_oil_disruption", "aviation"): _ctx(
        "aviation", "physical_disruption", "cost_increase",
        "jet_fuel_feedstock_exposure", "downstream_exposure",
        "transport_fuel_cost_exposure",
    ),
    ("case_2024_taiwan_strait_drills_semiconductor_supply", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "regional_military_drills", "contextual_background",
        "regional_security_context",
    ),
    ("case_taiwan_strait_semiconductor_risk", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "regional_military_tension", "contextual_background",
        "regional_security_context",
    ),
    ("case_2010_china_japan_rare_earth_embargo", "defense"): _ctx(
        "defense", "export_restriction", "input_access_restriction",
        "rare_earth_input_dependency", "downstream_exposure",
        "critical_material_input_constraint",
    ),
    ("case_2019_turkey_f35_s400_defense_restrictions", "defense"): _ctx(
        "defense", "regulatory_restriction", "trade_access_restriction",
        "defense_procurement_policy_dispute", "direct_disruption_target",
        "aerospace_defense_procurement_constraint",
    ),
    ("case_2011_libya_civil_war_oil_disruption", "logistics"): _ctx(
        "logistics", "physical_disruption", "cost_increase",
        "fuel_supply_uncertainty", "downstream_exposure",
        "transport_fuel_cost_exposure",
    ),
    ("case_1987_1988_tanker_war_reflagging", "logistics"): _ctx(
        "logistics", "military_escalation", "route_disruption",
        "convoy_and_routing_constraints", "transmission_channel",
        "maritime_route_security_constraint",
    ),
    ("case_2023_arctic_lng_russian_energy_shipping_sanctions", "marine_insurance"): _ctx(
        "marine_insurance", "sanctions", "insurance_constraint",
        "energy_shipping_insurance_and_financing_limits", "financing_or_insurance_channel",
        "energy_shipping_insurance_constraint",
    ),
    ("case_israel_iran_escalation_energy_risk", "marine_insurance"): _ctx(
        "marine_insurance", "military_escalation", "insurance_constraint",
        "regional_energy_chokepoint_risk", "financing_or_insurance_channel",
        "energy_shipping_insurance_constraint",
    ),
    ("case_2023_red_sea_attacks", "marine_insurance"): _ctx(
        "marine_insurance", "military_escalation", "insurance_constraint",
        "vessel_security_risk", "financing_or_insurance_channel",
        "maritime_route_security_constraint",
    ),
    ("case_hormuz_tanker_tensions", "marine_insurance"): _ctx(
        "marine_insurance", "military_escalation", "insurance_constraint",
        "tanker_security_incidents", "financing_or_insurance_channel",
        "energy_shipping_insurance_constraint",
    ),
    ("case_2023_arctic_lng_russian_energy_shipping_sanctions", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "sanctions", "route_disruption",
        "arctic_lng_shipping_restrictions", "transmission_channel",
        "energy_shipping_sanctions_route_constraint",
    ),
    ("case_israel_iran_escalation_energy_risk", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "military_escalation", "security_risk",
        "persian_gulf_chokepoint_risk", "transmission_channel",
        "energy_chokepoint_security_constraint",
    ),
    ("case_2023_red_sea_attacks", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "military_escalation", "route_disruption",
        "red_sea_vessel_security_risk", "direct_disruption_target",
        "maritime_route_security_constraint",
    ),
    ("case_2008_somali_piracy_gulf_of_aden", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "military_escalation", "route_disruption",
        "gulf_of_aden_piracy_security_risk", "direct_disruption_target",
        "maritime_route_security_constraint",
    ),
    ("case_hormuz_tanker_tensions", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "military_escalation", "security_risk",
        "hormuz_tanker_security_incidents", "direct_disruption_target",
        "energy_chokepoint_security_constraint",
    ),
    ("case_2021_suez_blockage", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "physical_disruption", "route_disruption",
        "canal_blockage", "direct_disruption_target",
        "maritime_route_capacity_constraint",
    ),
    ("case_2023_red_sea_attacks", "maritime_chokepoint"): _ctx(
        "maritime_chokepoint", "military_escalation", "route_disruption",
        "red_sea_vessel_security_risk", "direct_disruption_target",
        "maritime_route_security_constraint",
    ),
    ("case_2023_black_sea_shipping_insurance_restrictions", "marine_insurance"): _ctx(
        "marine_insurance", "military_escalation", "insurance_constraint",
        "grain_shipping_war_risk_insurance", "financing_or_insurance_channel",
        "food_shipping_insurance_constraint",
    ),
    ("case_2022_abu_dhabi_oil_facility_attack", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "energy_facility_attack_defense_readiness", "downstream_exposure",
        "regional_security_context",
    ),
    ("case_israel_iran_escalation_energy_risk", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "regional_military_escalation", "downstream_exposure",
        "regional_security_context",
    ),
    ("case_1987_1988_tanker_war_reflagging", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "convoy_and_reflagging_security_operations", "downstream_exposure",
        "regional_security_context",
    ),
    ("case_2022_gas_fertilizer_shock", "petrochemicals"): _ctx(
        "petrochemicals", "physical_disruption", "input_shortage",
        "natural_gas_feedstock_shortage", "upstream_input",
        "petrochemical_feedstock_constraint",
    ),
    ("case_2022_gas_fertilizer_shock", "energy"): _ctx(
        "energy", "physical_disruption", "input_shortage",
        "natural_gas_feedstock_shortage", "upstream_input",
        "energy_feedstock_constraint",
    ),
    ("case_russia_ukraine_energy_shock", "petrochemicals"): _ctx(
        "petrochemicals", "sanctions", "input_shortage",
        "gas_and_energy_feedstock_disruption", "upstream_input",
        "petrochemical_feedstock_constraint",
    ),
    ("case_russia_ukraine_energy_shock", "energy"): _ctx(
        "energy", "sanctions", "input_shortage",
        "gas_and_energy_feedstock_disruption", "upstream_input",
        "energy_feedstock_constraint",
    ),
    ("case_middle_east_oil_supply_disruption", "refining"): _ctx(
        "refining", "physical_disruption", "input_shortage",
        "crude_supply_disruption", "upstream_input",
        "refining_feedstock_constraint",
    ),
    ("case_opec_production_cut_policy_shock", "refining"): _ctx(
        "refining", "capacity_constraint", "input_shortage",
        "crude_supply_policy_cut", "upstream_input",
        "refining_feedstock_constraint",
    ),
    ("case_panama_canal_drought_shipping_capacity", "container_shipping"): _ctx(
        "container_shipping", "capacity_constraint", "route_disruption",
        "canal_transit_capacity_reduction", "direct_disruption_target",
        "maritime_route_capacity_constraint",
    ),
    ("case_2021_suez_blockage", "container_shipping"): _ctx(
        "container_shipping", "physical_disruption", "route_disruption",
        "canal_blockage", "direct_disruption_target",
        "maritime_route_capacity_constraint",
    ),
    ("case_hormuz_tanker_tensions", "oil_shipping"): _ctx(
        "oil_shipping", "military_escalation", "route_disruption",
        "tanker_security_incidents", "direct_disruption_target",
        "oil_shipping_security_constraint",
    ),
    ("case_1987_1988_tanker_war_reflagging", "oil_shipping"): _ctx(
        "oil_shipping", "military_escalation", "route_disruption",
        "tanker_attack_risk", "direct_disruption_target",
        "oil_shipping_security_constraint",
    ),
    ("case_2023_red_sea_attacks", "oil_shipping"): _ctx(
        "oil_shipping", "military_escalation", "route_disruption",
        "red_sea_vessel_security_risk", "transmission_channel",
        "oil_shipping_security_constraint",
    ),
    ("case_2018_2019_us_china_tariffs", "trade_lanes"): _ctx(
        "trade_lanes", "tariff", "trade_access_restriction",
        "tariff_and_customs_review", "compliance_channel",
        "tariff_trade_compliance_constraint",
    ),
    ("case_2024_ev_tariff_escalation_china", "trade_lanes"): _ctx(
        "trade_lanes", "tariff", "trade_access_restriction",
        "clean_technology_tariff_escalation", "compliance_channel",
        "tariff_trade_compliance_constraint",
    ),
}


def main() -> None:
    """Write controlled enrichment and mechanism-support audit artifacts."""

    historical_cases = _load_json(HISTORICAL_CASES)
    historical_by_id = {case["event_id"]: case for case in historical_cases}
    error_payload = _load_json(ERROR_PROTOTYPE)
    rule_rows = _read_csv(RULE_AUDIT)
    error_instances = error_payload["error_instances"]
    clean_controls = [*_selected_clean_controls(rule_rows), *_manual_clean_controls()]
    instances = [*_instances_from_error_payload(error_instances), *clean_controls]

    enriched_cases = _build_controlled_cases(instances, historical_by_id)
    audit_rows = [_audit_instance(instance) for instance in instances]
    summary = _summary(audit_rows, enriched_cases, error_instances, clean_controls)

    _write_json(CONTROLLED_CASES_OUTPUT, enriched_cases)
    _write_csv(AUDIT_OUTPUT, audit_rows)
    _write_json(SUMMARY_OUTPUT, summary)

    print(json.dumps(summary["method_comparison"], indent=2, sort_keys=True))


def _instances_from_error_payload(error_instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in error_instances:
        rows.append({
            "source": "rule6_error",
            "event_id": item["event_id"],
            "node": item["node"],
            "audit_label": item["audit_label"],
            "rule6_result": item["rule6_result"],
            "supporting_case_ids": [entry["case_id"] for entry in item["supporting_case_contexts"]],
        })
    return rows


def _selected_clean_controls(rule_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    selected = []
    for row in rule_rows:
        key = (row["event_id"], row["node"])
        if key not in CLEAN_CONTROL_KEYS:
            continue
        selected.append({
            "source": "clean_control",
            "event_id": row["event_id"],
            "node": row["node"],
            "audit_label": row["audit_mechanism_label"],
            "rule6_result": "keep" if row["rule_6_support_mechanism_overlap"] == "True" else "reject",
            "supporting_case_ids": _split(row["supporting_case_ids"]),
        })
    return sorted(selected, key=lambda row: (row["event_id"], row["node"]))


def _manual_clean_controls() -> list[dict[str, Any]]:
    return [
        {"source": "clean_control", **row}
        for row in MANUAL_CLEAN_CONTROLS
    ]


def _build_controlled_cases(
    instances: list[dict[str, Any]],
    historical_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    contexts_by_case: dict[str, list[dict[str, Any]]] = {}
    nodes_by_case: dict[str, set[str]] = {}
    error_case_ids = set()
    control_case_ids = set()

    for instance in instances:
        target = error_case_ids if instance["source"] == "rule6_error" else control_case_ids
        for case_id in instance["supporting_case_ids"]:
            target.add(case_id)
            context = CASE_CONTEXTS.get((case_id, instance["node"]))
            if not context:
                continue
            context = {
                **context,
                "case_id": case_id,
                "diagnostic_only": True,
                "source_fields_used": [
                    "event_type",
                    "industries",
                    "supply_chain_nodes",
                    "affected_asset_types",
                    "affected_assets",
                    "transmission_chain",
                    "summary",
                ],
                "raw_event_type": historical_by_id.get(case_id, {}).get("event_type", ""),
                "raw_affected_asset_types": historical_by_id.get(case_id, {}).get("affected_asset_types", []),
                "raw_transmission_chain_steps": historical_by_id.get(case_id, {}).get("transmission_chain", []),
                "diagnostic_rationale": (
                    "Curated only for the controlled V4 transmission-context "
                    "prototype; not loaded by production code."
                ),
            }
            contexts_by_case.setdefault(case_id, []).append(context)
            nodes_by_case.setdefault(case_id, set()).add(instance["node"])

    cases = []
    for case_id in sorted(contexts_by_case):
        base = historical_by_id.get(case_id, {})
        cases.append({
            "case_id": case_id,
            "event_name": base.get("event_name", base.get("title", "")),
            "event_type": base.get("event_type", ""),
            "nodes_enriched": sorted(nodes_by_case[case_id]),
            "diagnostic_only": True,
            "transmission_contexts": sorted(
                contexts_by_case[case_id],
                key=lambda context: context["node"],
            ),
        })

    current_event_contexts = []
    for instance in sorted(instances, key=lambda row: (row["event_id"], row["node"])):
        context = CURRENT_CONTEXTS.get((instance["event_id"], instance["node"]))
        if not context:
            context = _ctx(
                instance["node"],
                "unknown",
                "unknown",
                "unknown",
                "unknown",
                "unknown",
            )
        current_event_contexts.append({
            "event_id": instance["event_id"],
            "node": instance["node"],
            "diagnostic_only": True,
            "source_fields_used": [
                "event_id",
                "event_type",
                "summary",
                "industries",
                "supply_chain_nodes",
            ],
            "transmission_context": context,
            "diagnostic_rationale": (
                "Offline current-event projection for the controlled "
                "mechanism-compatible support prototype. This is not a "
                "production EventAnalysis schema change."
            ),
        })

    return {
        "diagnostic_only": True,
        "schema_version": "controlled_transmission_context_v0",
        "selection_rationale": {
            "rule6_error_cases": (
                "All historical cases supporting the 10 Rule-6 error mechanism "
                "instances were included."
            ),
            "clean_controls": (
                "Additional non-error mechanism instances were selected to cover "
                "container_shipping, ports/maritime routes, oil_shipping, refining, "
                "petrochemicals, lng/energy shipping, trade-lane adjacent, energy, "
                "defense, and marine-insurance contexts."
            ),
        },
        "case_count": len(cases),
        "error_related_case_count": len(error_case_ids),
        "control_case_count": len(control_case_ids - error_case_ids),
        "nodes_covered": sorted({node for nodes in nodes_by_case.values() for node in nodes}),
        "current_event_contexts": current_event_contexts,
        "cases": cases,
    }


def _audit_instance(instance: dict[str, Any]) -> dict[str, Any]:
    current_context = CURRENT_CONTEXTS.get((instance["event_id"], instance["node"]))
    support_contexts = [
        {"case_id": case_id, **CASE_CONTEXTS[(case_id, instance["node"])]}
        for case_id in instance["supporting_case_ids"]
        if (case_id, instance["node"]) in CASE_CONTEXTS
    ]
    diagnostics = support_diagnostics(current_context, support_contexts)
    structured_result = (
        "keep"
        if diagnostics["candidate_under_structured_rule"]
        else (
            "insufficient_context"
            if diagnostics["compatible_support_count"] == 0
            and diagnostics["insufficient_context_count"] > 0
            else "reject"
        )
    )
    target_keep = instance["audit_label"] in {"consistent", "mixed"}
    structured_keep = diagnostics["candidate_under_structured_rule"]

    return {
        "source": instance["source"],
        "event_id": instance["event_id"],
        "node": instance["node"],
        "audit_label": instance["audit_label"],
        "raw_voting_result": "keep" if len(set(instance["supporting_case_ids"])) >= 2 else "reject",
        "rule6_result": instance["rule6_result"],
        "structured_context_result": structured_result,
        "raw_support_count": diagnostics["raw_support_count"],
        "compatible_support_count": diagnostics["compatible_support_count"],
        "incompatible_support_count": diagnostics["incompatible_support_count"],
        "insufficient_context_count": diagnostics["insufficient_context_count"],
        "supporting_case_ids": ";".join(instance["supporting_case_ids"]),
        "compatible_case_ids": ";".join(diagnostics["compatible_case_ids"]),
        "incompatible_case_ids": ";".join(diagnostics["incompatible_case_ids"]),
        "insufficient_context_case_ids": ";".join(diagnostics["insufficient_context_case_ids"]),
        "candidate_under_raw_rule": diagnostics["candidate_under_raw_rule"],
        "candidate_under_structured_rule": diagnostics["candidate_under_structured_rule"],
        "structured_correct": structured_keep == target_keep,
        "case_decisions_json": json.dumps(diagnostics["case_decisions"], sort_keys=True),
    }


def _summary(
    audit_rows: list[dict[str, Any]],
    enriched_cases: dict[str, Any],
    error_instances: list[dict[str, Any]],
    clean_controls: list[dict[str, Any]],
) -> dict[str, Any]:
    error_rows = [row for row in audit_rows if row["source"] == "rule6_error"]
    control_rows = [row for row in audit_rows if row["source"] == "clean_control"]
    return {
        "diagnostic_only": True,
        "controlled_scope": {
            "historical_cases_selected": enriched_cases["case_count"],
            "nodes_covered": enriched_cases["nodes_covered"],
            "rule6_error_instances": len(error_instances),
            "clean_control_instances": len(clean_controls),
            "error_related_case_count": enriched_cases["error_related_case_count"],
            "control_case_count": enriched_cases["control_case_count"],
        },
        "method_comparison": {
            "raw_voting": _method_metrics(audit_rows, "raw_voting_result"),
            "rule_6": _method_metrics(audit_rows, "rule6_result"),
            "structured_context_prototype": _method_metrics(audit_rows, "structured_context_result"),
        },
        "rule6_errors_only": {
            "weak_misses_fixed": sum(
                1
                for row in error_rows
                if row["audit_label"] == "weak_cooccurrence"
                and not row["candidate_under_structured_rule"]
            ),
            "false_rejections_fixed": sum(
                1
                for row in error_rows
                if row["audit_label"] in {"consistent", "mixed"}
                and row["candidate_under_structured_rule"]
            ),
            "by_label": _label_counts(error_rows, "structured_context_result"),
        },
        "clean_control_regression": {
            "controls_evaluated": len(control_rows),
            "controls_retained": sum(row["candidate_under_structured_rule"] for row in control_rows),
            "new_false_rejections": sum(
                1 for row in control_rows
                if row["audit_label"] in {"consistent", "mixed"}
                and not row["candidate_under_structured_rule"]
            ),
            "by_label": _label_counts(control_rows, "structured_context_result"),
        },
        "insufficient_context": {
            "instances_with_any_insufficient": sum(
                1 for row in audit_rows if int(row["insufficient_context_count"]) > 0
            ),
            "total_insufficient_case_votes": sum(
                int(row["insufficient_context_count"]) for row in audit_rows
            ),
            "instance_rate": _rate(
                sum(1 for row in audit_rows if int(row["insufficient_context_count"]) > 0),
                len(audit_rows),
            ),
        },
        "critical_minerals": [
            {
                "event_id": row["event_id"],
                "structured_context_result": row["structured_context_result"],
                "compatible_support_count": row["compatible_support_count"],
                "compatible_case_ids": row["compatible_case_ids"],
            }
            for row in audit_rows
            if row["node"] == "critical_minerals"
        ],
        "broad_nodes": {
            node: _node_summary([row for row in audit_rows if row["node"] == node])
            for node in sorted({row["node"] for row in audit_rows})
        },
    }


def _method_metrics(rows: list[dict[str, Any]], result_field: str) -> dict[str, int]:
    weak_rows = [row for row in rows if row["audit_label"] == "weak_cooccurrence"]
    nonweak_rows = [row for row in rows if row["audit_label"] in {"consistent", "mixed"}]
    return {
        "weak_correctly_rejected": sum(1 for row in weak_rows if row[result_field] != "keep"),
        "weak_missed": sum(1 for row in weak_rows if row[result_field] == "keep"),
        "non_weak_retained": sum(1 for row in nonweak_rows if row[result_field] == "keep"),
        "false_rejected": sum(1 for row in nonweak_rows if row[result_field] != "keep"),
        "insufficient_context": sum(1 for row in rows if row[result_field] == "insufficient_context"),
    }


def _label_counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(row[field] for row in rows).items()))


def _node_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "instances": len(rows),
        "weak": sum(1 for row in rows if row["audit_label"] == "weak_cooccurrence"),
        "non_weak": sum(1 for row in rows if row["audit_label"] in {"consistent", "mixed"}),
        "structured_kept": sum(row["candidate_under_structured_rule"] for row in rows),
        "structured_rejected": sum(not row["candidate_under_structured_rule"] for row in rows),
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _split(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def _load_json(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
