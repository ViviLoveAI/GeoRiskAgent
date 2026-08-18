"""Single source of truth for the supply-chain node vocabulary.

Every supply-chain node used anywhere in the system (event-analyst rules,
historical cases, and the asset-mapping table) must be defined here. Nodes are
no longer free strings scattered across three files and aligned only by exact
string equality; they are a controlled vocabulary that can be validated and
resolved.

Usage:
- ``is_valid_node(node)`` / ``validate_nodes(nodes)`` to check membership.
- ``normalize_node(node)`` to resolve a known alias to its canonical id.
- ``all_node_ids()`` to enumerate the vocabulary.
- Run this module directly to validate that the data files
  (event rules, cases, asset mapping) contain only known nodes.

The ``category`` field groups nodes into transmission channels. It is not used
by the current transmission logic, but provides the basis for future
"same-channel" second-order rules.
"""

from __future__ import annotations

from dataclasses import dataclass


# --- Transmission channels (node categories) -------------------------------

class Channel:
    MARITIME = "maritime_logistics"
    ENERGY = "energy"
    SEMICONDUCTOR = "semiconductor_tech"
    MATERIALS = "materials_minerals"
    AGRICULTURE = "agriculture"
    DEFENSE_AERO = "defense_aerospace"
    TRADE_FINANCE = "trade_finance_policy"
    CYBER = "cyber"
    BROAD = "broad"


@dataclass(frozen=True)
class NodeSpec:
    """Definition of a single supply-chain node."""

    node_id: str
    definition: str
    category: str
    aliases: tuple[str, ...] = ()


# --- The controlled vocabulary ---------------------------------------------
# Ordered by channel for readability. node_id is the canonical string used in
# event rules, historical_cases.json, and asset_mapping.csv.

_SPECS: list[NodeSpec] = [
    # Maritime / logistics
    NodeSpec("maritime_chokepoint", "Narrow strategic maritime passages such as Suez, Hormuz, Bab el-Mandeb.", Channel.MARITIME),
    NodeSpec("container_shipping", "Containerized ocean freight carriers and charter markets.", Channel.MARITIME),
    NodeSpec("oil_shipping", "Crude and refined-product tanker transport.", Channel.MARITIME),
    NodeSpec("lng_shipping", "Liquefied natural gas maritime transport.", Channel.MARITIME),
    NodeSpec("freight_routes", "Overland and multimodal freight corridors.", Channel.MARITIME),
    NodeSpec("ports", "Port terminals and port operators.", Channel.MARITIME),
    NodeSpec("port_labor", "Port workforce and labor availability affecting throughput.", Channel.MARITIME),
    NodeSpec("panama_canal", "Panama Canal transit capacity and draft/water constraints.", Channel.MARITIME),
    NodeSpec("marine_insurance", "Marine and cargo insurance underwriting.", Channel.MARITIME),
    NodeSpec("logistics", "Third-party logistics, warehousing, and distribution.", Channel.MARITIME),
    NodeSpec("trade_lanes", "Bilateral and multilateral trade routes and flows.", Channel.MARITIME),

    # Energy
    NodeSpec("energy", "Broad oil, gas, and power supply.", Channel.ENERGY),
    NodeSpec("refining", "Crude oil refining capacity and margins.", Channel.ENERGY),
    NodeSpec("petrochemicals", "Petrochemical and chemical intermediates.", Channel.ENERGY),
    NodeSpec("pipeline_infrastructure", "Oil and gas pipeline transport infrastructure.", Channel.ENERGY),
    NodeSpec("nuclear_fuel", "Nuclear fuel cycle: conversion, enrichment, fabrication.", Channel.ENERGY),
    NodeSpec("uranium", "Uranium mining and supply.", Channel.ENERGY),

    # Semiconductor / tech
    NodeSpec("ai_chips", "Advanced AI accelerators and high-end GPUs.", Channel.SEMICONDUCTOR),
    NodeSpec("semiconductor_equipment", "Chipmaking tools such as lithography and deposition systems.", Channel.SEMICONDUCTOR),
    NodeSpec("eda_software", "Electronic design automation software for chip design.", Channel.SEMICONDUCTOR),
    NodeSpec("foundry", "Semiconductor contract manufacturing (wafer fabrication).", Channel.SEMICONDUCTOR),
    NodeSpec("data_centers", "Data center capacity and operators.", Channel.SEMICONDUCTOR),
    NodeSpec("taiwan_semiconductor_supply", "Concentrated advanced-chip supply centered on Taiwan.", Channel.SEMICONDUCTOR),

    # Materials / minerals
    NodeSpec("critical_minerals", "Strategically important minerals subject to supply or export risk.", Channel.MATERIALS),
    NodeSpec("rare_earths", "Rare earth element mining and processing.", Channel.MATERIALS),
    NodeSpec("gallium_germanium_graphite", "Export-controlled electronic and battery minerals (Ga, Ge, graphite).", Channel.MATERIALS),
    # NOTE: `graphite` overlaps with `gallium_germanium_graphite`. Kept separate
    # pending a decision on whether to merge or treat as different granularities.
    NodeSpec("graphite", "Graphite supply for battery anodes and industrial use.", Channel.MATERIALS),
    NodeSpec("battery_materials", "Inputs for battery cells such as lithium and cathode/anode materials.", Channel.MATERIALS),
    NodeSpec("manufacturing_inputs", "Intermediate industrial inputs and components.", Channel.MATERIALS),

    # Agriculture
    NodeSpec("agriculture", "Crop production and agricultural output.", Channel.AGRICULTURE),
    NodeSpec("grain_exports", "Grain trade and export flows.", Channel.AGRICULTURE),
    NodeSpec("fertilizer", "Fertilizer and crop-nutrient production.", Channel.AGRICULTURE),
    NodeSpec("food_export_controls", "Export restrictions on food and agricultural commodities.", Channel.AGRICULTURE),

    # Defense / aerospace
    NodeSpec("defense", "Defense and military procurement supply chain.", Channel.DEFENSE_AERO),
    NodeSpec("aerospace_supply_chain", "Aircraft and aerospace component manufacturing and suppliers.", Channel.DEFENSE_AERO),
    NodeSpec("aviation", "Commercial and cargo air transport.", Channel.DEFENSE_AERO),

    # Trade / finance / policy
    NodeSpec("customs", "Customs, licensing, and border clearance for regulated goods.", Channel.TRADE_FINANCE),
    NodeSpec("financial_sanctions", "Sanctions affecting cross-border financial flows.", Channel.TRADE_FINANCE),
    NodeSpec("payment_networks", "Cross-border payment and settlement rails.", Channel.TRADE_FINANCE),

    # Cyber
    NodeSpec("cyber_infrastructure", "Digital and operational-technology systems underpinning critical infrastructure.", Channel.CYBER),

    # Broad catch-all
    NodeSpec("broad_etf", "Catch-all broad-market exposure used when no specific channel is identified.", Channel.BROAD),
]


NODE_REGISTRY: dict[str, NodeSpec] = {spec.node_id: spec for spec in _SPECS}

# alias -> canonical node_id
_ALIAS_INDEX: dict[str, str] = {
    alias: spec.node_id for spec in _SPECS for alias in spec.aliases
}


# --- Public API ------------------------------------------------------------

def all_node_ids() -> set[str]:
    """Return the set of canonical node ids."""

    return set(NODE_REGISTRY)


def is_valid_node(node: str) -> bool:
    """Return whether a string is a known canonical node id or alias."""

    return node in NODE_REGISTRY or node in _ALIAS_INDEX


def normalize_node(node: str) -> str | None:
    """Resolve a node string to its canonical id, or None if unknown."""

    if node in NODE_REGISTRY:
        return node
    return _ALIAS_INDEX.get(node)


def unknown_nodes(nodes: list[str]) -> list[str]:
    """Return the subset of nodes that are not valid (canonical or alias)."""

    return [node for node in nodes if not is_valid_node(node)]


def validate_nodes(nodes: list[str], source: str = "input") -> None:
    """Raise ValueError if any node is unknown. Use for startup/config checks."""

    unknown = unknown_nodes(nodes)
    if unknown:
        raise ValueError(
            f"Unknown supply-chain node(s) in {source}: {sorted(set(unknown))}. "
            f"Add them to nodes.NODE_REGISTRY or fix the spelling."
        )


def node_definition(node: str) -> str | None:
    """Return the human-readable definition for a node, if known."""

    canonical = normalize_node(node)
    return NODE_REGISTRY[canonical].definition if canonical else None


def nodes_in_channel(category: str) -> set[str]:
    """Return all node ids belonging to a given transmission channel."""

    return {
        spec.node_id for spec in NODE_REGISTRY.values() if spec.category == category
    }


# --- Data-source consistency check (run this module directly) --------------

def _check_data_sources() -> int:
    """Validate that all nodes used in the data files are in the registry.

    Returns a process exit code (0 = ok, 1 = drift found).
    """

    import csv
    import json
    import re
    from pathlib import Path

    base = Path(__file__).resolve().parent
    data = base.parent / "data"

    problems: list[str] = []

    # asset_mapping.csv
    mapping_path = data / "asset_mapping.csv"
    if mapping_path.exists():
        with mapping_path.open(encoding="utf-8") as handle:
            map_nodes = [row["supply_chain_node"] for row in csv.DictReader(handle)]
        unknown = unknown_nodes(map_nodes)
        if unknown:
            problems.append(f"asset_mapping.csv has unknown nodes: {sorted(set(unknown))}")

    # historical_cases.json
    cases_path = data / "historical_cases.json"
    if cases_path.exists():
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        case_nodes = [n for c in cases for n in c.get("supply_chain_nodes", [])]
        unknown = unknown_nodes(case_nodes)
        if unknown:
            problems.append(f"historical_cases.json has unknown nodes: {sorted(set(unknown))}")

    # event rules (regex-extracted from the analyst source)
    analyst_path = base / "agents" / "event_analyst.py"
    if not analyst_path.exists():
        analyst_path = base / "event_analyst.py"
    if analyst_path.exists():
        src = analyst_path.read_text(encoding="utf-8")
        rule_nodes: list[str] = []
        for block in re.findall(r'"supply_chain_nodes"\s*:\s*\[(.*?)\]', src, re.S):
            rule_nodes.extend(re.findall(r'"([a-z_]+)"', block))
        unknown = unknown_nodes(rule_nodes)
        if unknown:
            problems.append(f"event rules have unknown nodes: {sorted(set(unknown))}")

    if problems:
        print("NODE REGISTRY DRIFT DETECTED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"OK: all data-source nodes are in the registry ({len(NODE_REGISTRY)} nodes).")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_check_data_sources())
