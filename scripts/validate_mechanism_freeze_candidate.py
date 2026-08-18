"""Validate the frozen V4 mechanism-compatibility candidate offline.

The script evaluates a design split and a broader development-validation split.
It does not modify production historical cases, retrieval, transmission logic,
ranking, market data, or CAR outputs.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.prototype_mechanism_compatible_support import (
    CASE_CONTEXTS as DESIGN_CASE_CONTEXTS,
    CURRENT_CONTEXTS as DESIGN_CURRENT_CONTEXTS,
    _ctx,
    _read_csv,
    _write_csv,
    _write_json,
)
from src.validation.transmission_context import (
    REVIEW_CANONICAL_CONTEXT_FAMILIES,
    support_diagnostics_with_family_review,
)


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
HISTORICAL_CASES = Path("data/historical_cases.json")
DESIGN_AUDIT = OUTPUT_DIR / "two_failure_mode_compatibility_review.csv"
EXPANDED_CASES_OUTPUT = OUTPUT_DIR / "expanded_transmission_context_validation_cases.json"
VALIDATION_OUTPUT = OUTPUT_DIR / "mechanism_freeze_candidate_validation.csv"
SUMMARY_OUTPUT = OUTPUT_DIR / "mechanism_freeze_candidate_validation_summary.json"
ERRORS_OUTPUT = OUTPUT_DIR / "mechanism_freeze_candidate_validation_errors.csv"

BROAD_NODES = {
    "aviation",
    "customs",
    "defense",
    "energy",
    "financial_sanctions",
    "freight_routes",
    "logistics",
    "marine_insurance",
    "maritime_chokepoint",
    "payment_networks",
    "trade_lanes",
}


EXPANDED_CURRENT_CONTEXTS: dict[tuple[str, str], dict[str, str]] = {
    ("dev_red_sea_shipping_disruption", "container_shipping"): _ctx(
        "container_shipping", "military_escalation", "route_disruption",
        "red_sea_vessel_security_risk", "direct_disruption_target",
        "maritime_route_security_constraint",
    ),
    ("dev_red_sea_shipping_disruption", "marine_insurance"): _ctx(
        "marine_insurance", "military_escalation", "insurance_constraint",
        "red_sea_vessel_security_risk", "financing_or_insurance_channel",
        "maritime_route_security_constraint",
    ),
    ("dev_red_sea_shipping_disruption", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "regional_maritime_security_risk", "contextual_background",
        "regional_security_context",
    ),
    ("dev_energy_sanctions_oil_shipping", "financial_sanctions"): _ctx(
        "financial_sanctions", "sanctions", "financing_constraint",
        "oil_trade_finance_restriction", "direct_disruption_target",
        "financial_sanctions_trade_finance_constraint",
    ),
    ("dev_energy_sanctions_oil_shipping", "oil_shipping"): _ctx(
        "oil_shipping", "sanctions", "route_disruption",
        "oil_shipping_compliance_risk", "transmission_channel",
        "oil_shipping_security_constraint",
    ),
    ("dev_energy_sanctions_oil_shipping", "energy"): _ctx(
        "energy", "sanctions", "trade_access_restriction",
        "restricted_energy_exports", "downstream_exposure",
        "energy_trade_access_constraint",
    ),
    ("dev_graphite_export_controls", "battery_materials"): _ctx(
        "battery_materials", "export_restriction", "input_access_restriction",
        "graphite_export_licensing_controls", "upstream_input",
        "battery_material_input_constraint",
    ),
    ("dev_graphite_export_controls", "critical_minerals"): _ctx(
        "critical_minerals", "export_restriction", "input_access_restriction",
        "graphite_export_licensing_controls", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("dev_graphite_export_controls", "logistics"): _ctx(
        "logistics", "export_restriction", "input_access_restriction",
        "graphite_export_licensing_controls", "contextual_background",
        "critical_material_input_constraint",
    ),
    ("dev_semiconductor_export_controls", "semiconductor_equipment"): _ctx(
        "semiconductor_equipment", "export_restriction", "trade_access_restriction",
        "advanced_tool_export_controls", "direct_disruption_target",
        "semiconductor_export_control_constraint",
    ),
    ("dev_semiconductor_export_controls", "defense"): _ctx(
        "defense", "export_restriction", "input_access_restriction",
        "advanced_chip_export_controls", "downstream_strategic_exposure",
        "semiconductor_strategic_downstream_exposure",
    ),
    ("dev_semiconductor_export_controls", "aviation"): _ctx(
        "aviation", "export_restriction", "trade_access_restriction",
        "advanced_tool_export_controls", "contextual_background",
        "semiconductor_export_control_constraint",
    ),
    ("dev_food_export_restriction", "grain_exports"): _ctx(
        "grain_exports", "export_restriction", "trade_access_restriction",
        "food_export_ban", "direct_disruption_target",
        "food_export_trade_constraint",
    ),
    ("dev_food_export_restriction", "agriculture"): _ctx(
        "agriculture", "export_restriction", "trade_access_restriction",
        "food_export_ban", "downstream_exposure",
        "agricultural_export_trade_constraint",
    ),
    ("dev_food_export_restriction", "financial_sanctions"): _ctx(
        "financial_sanctions", "export_restriction", "trade_access_restriction",
        "food_export_ban", "contextual_background",
        "food_export_trade_constraint",
    ),
    ("dev_cyber_port_disruption", "ports"): _ctx(
        "ports", "cyber_disruption", "capacity_reduction",
        "port_operational_shutdown", "direct_disruption_target",
        "port_cyber_capacity_constraint",
    ),
    ("dev_cyber_port_disruption", "logistics"): _ctx(
        "logistics", "cyber_disruption", "capacity_reduction",
        "port_operational_shutdown", "transmission_channel",
        "logistics_cyber_capacity_constraint",
    ),
    ("dev_cyber_port_disruption", "energy"): _ctx(
        "energy", "cyber_disruption", "capacity_reduction",
        "port_operational_shutdown", "contextual_background",
        "port_cyber_capacity_constraint",
    ),
    ("dev_lng_shipping_sanctions", "lng_shipping"): _ctx(
        "lng_shipping", "sanctions", "route_disruption",
        "arctic_lng_shipping_restrictions", "direct_disruption_target",
        "energy_shipping_sanctions_route_constraint",
    ),
    ("dev_lng_shipping_sanctions", "marine_insurance"): _ctx(
        "marine_insurance", "sanctions", "insurance_constraint",
        "energy_shipping_insurance_and_financing_limits", "financing_or_insurance_channel",
        "energy_shipping_insurance_constraint",
    ),
    ("dev_trade_tariff_customs", "customs"): _ctx(
        "customs", "tariff", "compliance_constraint",
        "tariff_classification_review", "compliance_channel",
        "tariff_customs_compliance_constraint",
    ),
    ("dev_trade_tariff_customs", "trade_lanes"): _ctx(
        "trade_lanes", "tariff", "trade_access_restriction",
        "tariff_and_customs_review", "compliance_channel",
        "tariff_trade_compliance_constraint",
    ),
    ("dev_trade_tariff_customs", "energy"): _ctx(
        "energy", "tariff", "compliance_constraint",
        "tariff_classification_review", "contextual_background",
        "tariff_customs_compliance_constraint",
    ),
}


EXPANDED_CASE_CONTEXTS: dict[tuple[str, str], dict[str, str]] = {
    **DESIGN_CASE_CONTEXTS,
    ("case_2023_red_sea_attacks", "container_shipping"): _ctx(
        "container_shipping", "military_escalation", "route_disruption",
        "red_sea_vessel_security_risk", "direct_disruption_target",
        "maritime_route_security_constraint",
    ),
    ("case_2008_somali_piracy_gulf_of_aden", "container_shipping"): _ctx(
        "container_shipping", "military_escalation", "route_disruption",
        "gulf_of_aden_piracy_security_risk", "direct_disruption_target",
        "maritime_route_security_constraint",
    ),
    ("case_2021_suez_blockage", "container_shipping"): _ctx(
        "container_shipping", "physical_disruption", "route_disruption",
        "canal_blockage", "direct_disruption_target",
        "maritime_route_capacity_constraint",
    ),
    ("case_2022_russia_swift_financial_sanctions", "financial_sanctions"): _ctx(
        "financial_sanctions", "sanctions", "financing_constraint",
        "payment_network_restriction", "direct_disruption_target",
        "financial_sanctions_trade_finance_constraint",
    ),
    ("case_2018_iran_swift_restrictions", "financial_sanctions"): _ctx(
        "financial_sanctions", "sanctions", "financing_constraint",
        "swift_access_restriction", "direct_disruption_target",
        "financial_sanctions_trade_finance_constraint",
    ),
    ("case_2019_cosco_shipping_sanctions_tanker_market", "oil_shipping"): _ctx(
        "oil_shipping", "sanctions", "route_disruption",
        "shipping_compliance_restriction", "direct_disruption_target",
        "oil_shipping_security_constraint",
    ),
    ("case_2018_iran_oil_sanctions_reimposition", "oil_shipping"): _ctx(
        "oil_shipping", "sanctions", "route_disruption",
        "oil_export_shipping_restriction", "transmission_channel",
        "oil_shipping_security_constraint",
    ),
    ("case_2019_venezuela_oil_sanctions", "energy"): _ctx(
        "energy", "sanctions", "trade_access_restriction",
        "oil_export_sanctions", "downstream_exposure",
        "energy_trade_access_constraint",
    ),
    ("case_2022_russia_swift_financial_sanctions", "energy"): _ctx(
        "energy", "sanctions", "financing_constraint",
        "energy_trade_payment_disruption", "downstream_exposure",
        "energy_trade_finance_constraint",
    ),
    ("case_2023_south_china_sea_shipping_tensions", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "south_china_sea_maritime_security_tensions", "contextual_background",
        "regional_security_context",
    ),
    ("case_2023_china_graphite_battery_export_controls", "battery_materials"): _ctx(
        "battery_materials", "export_restriction", "input_access_restriction",
        "graphite_export_licensing_controls", "upstream_input",
        "battery_material_input_constraint",
    ),
    ("case_2022_chile_lithium_policy_shift", "battery_materials"): _ctx(
        "battery_materials", "regulatory_restriction", "input_access_restriction",
        "lithium_policy_uncertainty", "upstream_input",
        "battery_material_input_constraint",
    ),
    ("case_2020_indonesia_nickel_export_ban", "critical_minerals"): _ctx(
        "critical_minerals", "export_restriction", "input_access_restriction",
        "nickel_export_ban", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("case_2024_drc_cobalt_copper_mining_disruption", "critical_minerals"): _ctx(
        "critical_minerals", "physical_disruption", "input_shortage",
        "cobalt_copper_mining_disruption", "upstream_input",
        "critical_material_input_constraint",
    ),
    ("case_2023_dutch_asml_controls", "semiconductor_equipment"): _ctx(
        "semiconductor_equipment", "export_restriction", "trade_access_restriction",
        "advanced_lithography_export_controls", "direct_disruption_target",
        "semiconductor_export_control_constraint",
    ),
    ("case_2023_japan_chip_equipment_export_controls", "semiconductor_equipment"): _ctx(
        "semiconductor_equipment", "export_restriction", "trade_access_restriction",
        "chip_tool_export_controls", "direct_disruption_target",
        "semiconductor_export_control_constraint",
    ),
    ("case_2019_huawei_entity_list", "semiconductor_equipment"): _ctx(
        "semiconductor_equipment", "export_restriction", "trade_access_restriction",
        "entity_list_supply_restriction", "transmission_channel",
        "semiconductor_export_control_constraint",
    ),
    ("case_2024_taiwan_strait_drills_semiconductor_supply", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "advanced_foundry_concentration_risk", "downstream_strategic_exposure",
        "semiconductor_strategic_downstream_exposure",
    ),
    ("case_taiwan_strait_semiconductor_risk", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "advanced_chip_supply_uncertainty", "downstream_strategic_exposure",
        "semiconductor_strategic_downstream_exposure",
    ),
    ("case_2022_india_wheat_export_ban", "grain_exports"): _ctx(
        "grain_exports", "export_restriction", "trade_access_restriction",
        "wheat_export_ban", "direct_disruption_target",
        "food_export_trade_constraint",
    ),
    ("case_2008_rice_export_restrictions_food_security", "grain_exports"): _ctx(
        "grain_exports", "export_restriction", "trade_access_restriction",
        "rice_export_restrictions", "direct_disruption_target",
        "food_export_trade_constraint",
    ),
    ("case_2021_belarus_potash_sanctions", "agriculture"): _ctx(
        "agriculture", "sanctions", "input_shortage",
        "potash_fertilizer_restriction", "downstream_exposure",
        "agricultural_input_constraint",
    ),
    ("case_2022_russia_fertilizer_export_restrictions", "agriculture"): _ctx(
        "agriculture", "export_restriction", "input_shortage",
        "fertilizer_export_restriction", "downstream_exposure",
        "agricultural_input_constraint",
    ),
    ("case_2023_port_of_nagoya_cyberattack", "ports"): _ctx(
        "ports", "cyber_disruption", "capacity_reduction",
        "port_system_shutdown", "direct_disruption_target",
        "port_cyber_capacity_constraint",
    ),
    ("case_2023_dp_world_australia_cyber_port_disruption", "ports"): _ctx(
        "ports", "cyber_disruption", "capacity_reduction",
        "port_terminal_cyber_disruption", "direct_disruption_target",
        "port_cyber_capacity_constraint",
    ),
    ("case_2017_notpetya_shipping_logistics_cyberattack", "logistics"): _ctx(
        "logistics", "cyber_disruption", "capacity_reduction",
        "shipping_logistics_system_disruption", "transmission_channel",
        "logistics_cyber_capacity_constraint",
    ),
    ("case_2023_port_of_nagoya_cyberattack", "logistics"): _ctx(
        "logistics", "cyber_disruption", "capacity_reduction",
        "port_system_shutdown", "transmission_channel",
        "logistics_cyber_capacity_constraint",
    ),
    ("case_2021_colonial_pipeline_ransomware", "energy"): _ctx(
        "energy", "cyber_disruption", "capacity_reduction",
        "fuel_pipeline_shutdown", "direct_disruption_target",
        "energy_distribution_cyber_capacity_constraint",
    ),
    ("case_2021_myanmar_coup_supply_chain_disruption", "logistics"): _ctx(
        "logistics", "political_instability", "capacity_reduction",
        "factory_and_border_logistics_disruption", "transmission_channel",
        "logistics_operational_disruption",
    ),
    ("case_2024_us_east_gulf_port_strike", "logistics"): _ctx(
        "logistics", "labor_disruption", "capacity_reduction",
        "port_labor_work_stoppage", "transmission_channel",
        "logistics_port_labor_capacity_constraint",
    ),
    ("case_2022_russia_airspace_closure_aviation_routes", "aviation"): _ctx(
        "aviation", "military_escalation", "route_disruption",
        "airspace_access_restriction", "direct_disruption_target",
        "airspace_route_disruption",
    ),
    ("case_2014_crimea_financial_sanctions", "financial_sanctions"): _ctx(
        "financial_sanctions", "sanctions", "financing_constraint",
        "crimea_financial_access_restrictions", "direct_disruption_target",
        "financial_sanctions_trade_finance_constraint",
    ),
    ("case_2023_arctic_lng_russian_energy_shipping_sanctions", "lng_shipping"): _ctx(
        "lng_shipping", "sanctions", "route_disruption",
        "arctic_lng_shipping_restrictions", "direct_disruption_target",
        "energy_shipping_sanctions_route_constraint",
    ),
    ("case_2022_nord_stream_pipeline_sabotage", "lng_shipping"): _ctx(
        "lng_shipping", "physical_disruption", "supplier_substitution",
        "pipeline_gas_disruption_lng_substitution", "downstream_exposure",
        "energy_shipping_sanctions_route_constraint",
    ),
    ("case_2023_eu_carbon_border_adjustment_mechanism", "customs"): _ctx(
        "customs", "regulatory_restriction", "compliance_constraint",
        "carbon_border_documentation", "compliance_channel",
        "tariff_customs_compliance_constraint",
    ),
    ("case_2018_2019_us_china_tariffs", "customs"): _ctx(
        "customs", "tariff", "compliance_constraint",
        "tariff_classification_review", "compliance_channel",
        "tariff_customs_compliance_constraint",
    ),
    ("case_2023_eu_carbon_border_adjustment_mechanism", "trade_lanes"): _ctx(
        "trade_lanes", "regulatory_restriction", "trade_access_restriction",
        "carbon_border_trade_compliance", "compliance_channel",
        "tariff_trade_compliance_constraint",
    ),
    ("case_2023_eu_carbon_border_adjustment_mechanism", "energy"): _ctx(
        "energy", "regulatory_restriction", "compliance_constraint",
        "carbon_border_energy_intensity_reporting", "downstream_exposure",
        "energy_trade_compliance_constraint",
    ),
    ("case_2022_russia_fertilizer_export_restrictions", "energy"): _ctx(
        "energy", "export_restriction", "input_shortage",
        "natural_gas_fertilizer_feedstock_constraint", "upstream_input",
        "energy_feedstock_input_constraint",
    ),
    ("case_2018_2019_us_china_tariffs", "trade_lanes"): _ctx(
        "trade_lanes", "tariff", "trade_access_restriction",
        "tariff_and_customs_review", "compliance_channel",
        "tariff_trade_compliance_constraint",
    ),
}


def _inst(
    event_id: str,
    node: str,
    target: str,
    supporting_case_ids: list[str],
) -> dict[str, Any]:
    return {
        "evaluation_split": "expanded_validation_set",
        "event_id": event_id,
        "node": node,
        "mechanism_target": target,
        "supporting_case_ids": supporting_case_ids,
    }


EXPANDED_INSTANCES = [
    _inst("dev_red_sea_shipping_disruption", "container_shipping", "compatible_support_expected", [
        "case_2023_red_sea_attacks", "case_2008_somali_piracy_gulf_of_aden",
    ]),
    _inst("dev_red_sea_shipping_disruption", "marine_insurance", "compatible_support_expected", [
        "case_2023_red_sea_attacks", "case_hormuz_tanker_tensions",
    ]),
    _inst("dev_red_sea_shipping_disruption", "defense", "weak_cooccurrence_expected", [
        "case_2023_south_china_sea_shipping_tensions", "case_2019_turkey_f35_s400_defense_restrictions",
    ]),
    _inst("dev_energy_sanctions_oil_shipping", "financial_sanctions", "compatible_support_expected", [
        "case_2022_russia_swift_financial_sanctions", "case_2018_iran_swift_restrictions",
    ]),
    _inst("dev_energy_sanctions_oil_shipping", "oil_shipping", "compatible_support_expected", [
        "case_2019_cosco_shipping_sanctions_tanker_market", "case_2018_iran_oil_sanctions_reimposition",
    ]),
    _inst("dev_energy_sanctions_oil_shipping", "energy", "compatible_support_expected", [
        "case_2019_venezuela_oil_sanctions", "case_2022_russia_swift_financial_sanctions",
    ]),
    _inst("dev_graphite_export_controls", "battery_materials", "compatible_support_expected", [
        "case_2023_china_graphite_battery_export_controls", "case_2022_chile_lithium_policy_shift",
    ]),
    _inst("dev_graphite_export_controls", "critical_minerals", "compatible_support_expected", [
        "case_2020_indonesia_nickel_export_ban", "case_2024_drc_cobalt_copper_mining_disruption",
    ]),
    _inst("dev_semiconductor_export_controls", "semiconductor_equipment", "compatible_support_expected", [
        "case_2023_dutch_asml_controls", "case_2023_japan_chip_equipment_export_controls",
        "case_2019_huawei_entity_list",
    ]),
    _inst("dev_semiconductor_export_controls", "defense", "compatible_support_expected", [
        "case_2024_taiwan_strait_drills_semiconductor_supply", "case_taiwan_strait_semiconductor_risk",
    ]),
    _inst("dev_food_export_restriction", "grain_exports", "compatible_support_expected", [
        "case_2022_india_wheat_export_ban", "case_2008_rice_export_restrictions_food_security",
    ]),
    _inst("dev_food_export_restriction", "agriculture", "weak_cooccurrence_expected", [
        "case_2021_belarus_potash_sanctions", "case_2022_russia_fertilizer_export_restrictions",
    ]),
    _inst("dev_cyber_port_disruption", "ports", "compatible_support_expected", [
        "case_2023_port_of_nagoya_cyberattack", "case_2023_dp_world_australia_cyber_port_disruption",
    ]),
    _inst("dev_cyber_port_disruption", "logistics", "compatible_support_expected", [
        "case_2017_notpetya_shipping_logistics_cyberattack", "case_2023_port_of_nagoya_cyberattack",
    ]),
    _inst("dev_lng_shipping_sanctions", "lng_shipping", "compatible_support_expected", [
        "case_2023_arctic_lng_russian_energy_shipping_sanctions", "case_2022_nord_stream_pipeline_sabotage",
    ]),
    _inst("dev_lng_shipping_sanctions", "marine_insurance", "compatible_support_expected", [
        "case_2023_arctic_lng_russian_energy_shipping_sanctions", "case_hormuz_tanker_tensions",
    ]),
    _inst("dev_trade_tariff_customs", "customs", "compatible_support_expected", [
        "case_2023_eu_carbon_border_adjustment_mechanism", "case_2018_2019_us_china_tariffs",
    ]),
    _inst("dev_trade_tariff_customs", "trade_lanes", "compatible_support_expected", [
        "case_2023_eu_carbon_border_adjustment_mechanism", "case_2018_2019_us_china_tariffs",
    ]),
    _inst("dev_cyber_port_disruption", "energy", "weak_cooccurrence_expected", [
        "case_2021_colonial_pipeline_ransomware", "case_2022_gas_fertilizer_shock",
    ]),
    _inst("dev_graphite_export_controls", "logistics", "weak_cooccurrence_expected", [
        "case_2021_myanmar_coup_supply_chain_disruption", "case_2024_us_east_gulf_port_strike",
    ]),
    _inst("dev_semiconductor_export_controls", "aviation", "weak_cooccurrence_expected", [
        "case_2019_india_pakistan_airspace_closure", "case_2022_russia_airspace_closure_aviation_routes",
    ]),
    _inst("dev_food_export_restriction", "financial_sanctions", "weak_cooccurrence_expected", [
        "case_2022_russia_swift_financial_sanctions", "case_2014_crimea_financial_sanctions",
    ]),
    _inst("dev_lng_shipping_sanctions", "trade_lanes", "ambiguous", [
        "case_2023_arctic_lng_russian_energy_shipping_sanctions", "case_2018_2019_us_china_tariffs",
    ]),
    _inst("dev_trade_tariff_customs", "energy", "weak_cooccurrence_expected", [
        "case_2023_eu_carbon_border_adjustment_mechanism", "case_2022_russia_fertilizer_export_restrictions",
    ]),
]


def main() -> None:
    historical_cases = _load_json(HISTORICAL_CASES)
    historical_by_id = {case["event_id"]: case for case in historical_cases}
    design_rows = _design_rows()
    expanded_rows = [_evaluate_instance(instance, historical_by_id) for instance in EXPANDED_INSTANCES]
    all_rows = [*design_rows, *expanded_rows]

    expanded_cases = _expanded_cases_artifact(historical_by_id)
    errors = _error_rows(all_rows)
    summary = _summary(design_rows, expanded_rows, errors, expanded_cases)

    _write_json(EXPANDED_CASES_OUTPUT, expanded_cases)
    _write_csv(VALIDATION_OUTPUT, all_rows)
    _write_csv(ERRORS_OUTPUT, errors)
    _write_json(SUMMARY_OUTPUT, summary)
    print(json.dumps(summary["comparison"], indent=2, sort_keys=True))


def _design_rows() -> list[dict[str, Any]]:
    rows = []
    for row in _read_csv(DESIGN_AUDIT):
        target = (
            "weak_cooccurrence_expected"
            if row["audit_label"] == "weak_cooccurrence"
            else "compatible_support_expected"
        )
        rows.append({
            "evaluation_split": "design_set",
            "event_id": row["event_id"],
            "node": row["node"],
            "mechanism_target": target,
            "frozen_rule_result": row["after_result"],
            "raw_support_count": row["raw_support_count"],
            "compatible_support_count": row["after_compatible_support_count"],
            "incompatible_support_count": row["after_incompatible_support_count"],
            "insufficient_context_count": row["after_insufficient_context_count"],
            "supporting_case_ids": row["supporting_case_ids"],
            "compatible_case_ids": row["after_compatible_case_ids"],
            "incompatible_case_ids": row["after_incompatible_case_ids"],
            "canonical_family": _family_for(row["node"], row["event_id"]),
            "target_node_roles": "",
            "constraints": "",
            "node_specificity": _specificity(row["node"]),
            "correct": _correct(target, row["after_result"]),
        })
    return rows


def _evaluate_instance(
    instance: dict[str, Any],
    historical_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    event_id = instance["event_id"]
    node = instance["node"]
    support_contexts = [
        {"case_id": case_id, **EXPANDED_CASE_CONTEXTS.get((case_id, node), _missing_context(node))}
        for case_id in instance["supporting_case_ids"]
    ]
    diagnostics = support_diagnostics_with_family_review(
        EXPANDED_CURRENT_CONTEXTS.get((event_id, node)),
        support_contexts,
    )
    result = _result_label(diagnostics)
    target = instance["mechanism_target"]
    roles = sorted({context.get("target_node_role", "") for context in support_contexts})
    constraints = sorted({context.get("constraint_type", "") for context in support_contexts})
    families = sorted({_canonical_family(context.get("canonical_context", "")) for context in support_contexts})
    return {
        "evaluation_split": instance["evaluation_split"],
        "event_id": event_id,
        "node": node,
        "mechanism_target": target,
        "frozen_rule_result": result,
        "raw_support_count": diagnostics["raw_support_count"],
        "compatible_support_count": diagnostics["compatible_support_count"],
        "incompatible_support_count": diagnostics["incompatible_support_count"],
        "insufficient_context_count": diagnostics["insufficient_context_count"],
        "supporting_case_ids": ";".join(instance["supporting_case_ids"]),
        "compatible_case_ids": ";".join(diagnostics["compatible_case_ids"]),
        "incompatible_case_ids": ";".join(diagnostics["incompatible_case_ids"]),
        "canonical_family": ";".join(families),
        "target_node_roles": ";".join(roles),
        "constraints": ";".join(constraints),
        "node_specificity": _specificity(node),
        "correct": _correct(target, result),
    }


def _expanded_cases_artifact(historical_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_ids = sorted({case_id for instance in EXPANDED_INSTANCES for case_id in instance["supporting_case_ids"]})
    contexts_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (case_id, node), context in EXPANDED_CASE_CONTEXTS.items():
        if case_id not in case_ids:
            continue
        base = historical_by_id.get(case_id, {})
        contexts_by_case[case_id].append({
            **context,
            "case_id": case_id,
            "diagnostic_only": True,
            "raw_event_type": base.get("event_type", ""),
            "raw_transmission_chain_steps": base.get("transmission_chain", []),
            "raw_affected_asset_types": base.get("affected_asset_types", []),
            "raw_supply_chain_nodes": base.get("supply_chain_nodes", []),
            "source_fields_used": [
                "event_type",
                "industries",
                "supply_chain_nodes",
                "affected_asset_types",
                "affected_assets",
                "transmission_chain",
                "summary",
            ],
            "enrichment_rationale": (
                "Expanded development validation context using the frozen "
                "mechanism_compatibility_candidate_v1 schema."
            ),
        })
    return {
        "diagnostic_only": True,
        "mechanism_rule_version": "mechanism_compatibility_candidate_v1",
        "case_count": len(contexts_by_case),
        "mechanism_instances": len(EXPANDED_INSTANCES),
        "cases": [
            {
                "case_id": case_id,
                "event_name": historical_by_id.get(case_id, {}).get("event_name", ""),
                "event_type": historical_by_id.get(case_id, {}).get("event_type", ""),
                "transmission_contexts": sorted(contexts, key=lambda row: row["node"]),
            }
            for case_id, contexts in sorted(contexts_by_case.items())
        ],
    }


def _summary(
    design_rows: list[dict[str, Any]],
    expanded_rows: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    expanded_cases: dict[str, Any],
) -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "mechanism_rule_version": "mechanism_compatibility_candidate_v1",
        "expanded_scope": {
            "new_historical_cases": expanded_cases["case_count"],
            "mechanism_instances": len(expanded_rows),
            "mechanism_families": sorted({
                family
                for row in expanded_rows
                for family in str(row["canonical_family"]).split(";")
                if family
            }),
            "broad_node_instances": sum(row["node_specificity"] == "broad" for row in expanded_rows),
            "specific_node_instances": sum(row["node_specificity"] == "specific" for row in expanded_rows),
        },
        "comparison": {
            "design_set": _split_metrics(design_rows),
            "expanded_validation_set": _split_metrics(expanded_rows),
        },
        "by_node_expanded": _group_metrics(expanded_rows, "node"),
        "by_family_expanded": _group_metrics(expanded_rows, "canonical_family"),
        "by_role_expanded": _group_metrics(expanded_rows, "target_node_roles"),
        "broad_node_stability": _split_metrics([row for row in expanded_rows if row["node_specificity"] == "broad"]),
        "specific_node_preservation": _split_metrics([row for row in expanded_rows if row["node_specificity"] == "specific"]),
        "error_count": len(errors),
    }


def _split_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    compatible = [row for row in rows if row["mechanism_target"] == "compatible_support_expected"]
    weak = [row for row in rows if row["mechanism_target"] == "weak_cooccurrence_expected"]
    ambiguous = [row for row in rows if row["mechanism_target"] == "ambiguous"]
    false_rejects = [row for row in compatible if row["frozen_rule_result"] != "keep"]
    weak_leaks = [row for row in weak if row["frozen_rule_result"] == "keep"]
    weak_rejected = [row for row in weak if row["frozen_rule_result"] != "keep"]
    nonweak_retained = [row for row in compatible if row["frozen_rule_result"] == "keep"]
    insufficient = [row for row in rows if row["frozen_rule_result"] == "insufficient_context"]
    return {
        "mechanism_instances": len(rows),
        "compatible_expected": len(compatible),
        "weak_expected": len(weak),
        "ambiguous": len(ambiguous),
        "non_weak_retained": len(nonweak_retained),
        "non_weak_retention_rate": _rate(len(nonweak_retained), len(compatible)),
        "weak_rejected": len(weak_rejected),
        "weak_rejection_rate": _rate(len(weak_rejected), len(weak)),
        "false_rejects": len(false_rejects),
        "weak_leaks": len(weak_leaks),
        "insufficient_context": len(insufficient),
        "insufficient_context_rate": _rate(len(insufficient), len(rows)),
    }


def _group_metrics(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        keys = str(row[field]).split(";") if field in {"canonical_family", "target_node_roles"} else [str(row[field])]
        for key in keys:
            if key:
                groups[key].append(row)
    return {key: _split_metrics(value) for key, value in sorted(groups.items())}


def _error_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        error_type = ""
        if row["mechanism_target"] == "compatible_support_expected" and row["frozen_rule_result"] != "keep":
            error_type = "false_rejection"
        elif row["mechanism_target"] == "weak_cooccurrence_expected" and row["frozen_rule_result"] == "keep":
            error_type = "weak_leakage"
        elif row["frozen_rule_result"] == "insufficient_context":
            error_type = "insufficient_context"
        elif row["mechanism_target"] == "ambiguous":
            error_type = "ambiguous_target"
        if not error_type:
            continue
        result.append({
            "evaluation_split": row["evaluation_split"],
            "event_id": row["event_id"],
            "node": row["node"],
            "supporting_case_ids": row["supporting_case_ids"],
            "expected_target": row["mechanism_target"],
            "frozen_rule_result": row["frozen_rule_result"],
            "error_type": error_type,
            "canonical_family": row["canonical_family"],
            "target_node_roles": row["target_node_roles"],
            "constraints": row["constraints"],
            "brief_explanation": _error_explanation(row, error_type),
        })
    return result


def _error_explanation(row: dict[str, Any], error_type: str) -> str:
    if error_type == "ambiguous_target":
        return "Offline review target is ambiguous; excluded from binary success metrics."
    if error_type == "false_rejection":
        return "Frozen rule did not find two mechanism-compatible supporting cases."
    if error_type == "weak_leakage":
        return "Frozen rule found two compatible votes for an instance labeled weak co-occurrence."
    return "Frozen rule could not classify because required context was unavailable."


def _correct(target: str, result: str) -> bool:
    if target == "compatible_support_expected":
        return result == "keep"
    if target == "weak_cooccurrence_expected":
        return result != "keep"
    return result == "insufficient_context"


def _result_label(diagnostics: dict[str, Any]) -> str:
    if diagnostics["candidate_under_structured_rule"]:
        return "keep"
    if diagnostics["compatible_support_count"] == 0 and diagnostics["insufficient_context_count"] > 0:
        return "insufficient_context"
    return "reject"


def _missing_context(node: str) -> dict[str, str]:
    return _ctx(
        node,
        "unknown",
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )


def _family_for(node: str, event_id: str) -> str:
    context = DESIGN_CURRENT_CONTEXTS.get((event_id, node)) or EXPANDED_CURRENT_CONTEXTS.get((event_id, node))
    if not context:
        return ""
    return _canonical_family(context.get("canonical_context", ""))


def _canonical_family(canonical_context: str) -> str:
    return REVIEW_CANONICAL_CONTEXT_FAMILIES.get(canonical_context, canonical_context)


def _specificity(node: str) -> str:
    return "broad" if node in BROAD_NODES else "specific"


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _load_json(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


if __name__ == "__main__":
    main()
