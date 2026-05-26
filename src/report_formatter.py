"""Readable report formatting helpers."""

from src.schemas import FinalReport


EVIDENCE_LEVELS = ["historical_supported", "sector_proxy", "inference_only"]
NODE_LABELS = {
    "maritime_chokepoint": "maritime chokepoints",
    "container_shipping": "container shipping",
    "freight_routes": "freight routes",
    "ports": "ports",
    "marine_insurance": "marine insurance",
    "oil_shipping": "oil tanker shipping",
    "lng_shipping": "LNG shipping",
    "energy": "energy supply",
    "refining": "refining",
    "petrochemicals": "petrochemicals",
    "aviation": "aviation fuel demand",
    "semiconductor_equipment": "semiconductor equipment",
    "ai_chips": "AI chips",
    "eda_software": "chip design software",
    "foundry": "semiconductor foundries",
    "data_centers": "data centers",
    "trade_lanes": "trade lanes",
    "customs": "customs and compliance",
    "manufacturing_inputs": "manufacturing inputs",
    "agriculture": "agriculture",
    "fertilizer": "fertilizer",
    "logistics": "logistics networks",
    "defense": "defense supply chains",
    "broad_etf": "broad market context",
}
EVENT_TYPE_LABELS = {
    "maritime_security_disruption": "Maritime security disruption",
    "shipping_chokepoint_disruption": "Shipping chokepoint disruption",
    "technology_export_controls": "Technology export controls",
    "energy_infrastructure_disruption": "Energy infrastructure disruption",
    "war_and_sanctions_energy_disruption": "War and sanctions energy disruption",
    "trade_policy_and_tariffs": "Trade policy and tariffs",
    "energy_and_agricultural_input_shock": "Energy and agricultural input shock",
    "geopolitical_risk_event": "Geopolitical risk event",
}


def format_concise_report(report: FinalReport, verbose: bool = False) -> str:
    """Return a compact markdown report.

    The formatted report is for risk watchlist generation only. It does not
    predict stock prices or provide investment advice.
    """

    sections = [
        "# GeoRisk Transmission Report",
        _event_summary(report),
        _historical_cases(report, verbose=verbose),
        _transmission_chain(report),
        _asset_watchlist(report, verbose=verbose),
        "## Disclaimer\nRisk watchlist only. Not price prediction or investment advice.",
    ]
    return "\n\n".join(section for section in sections if section)


def _event_summary(report: FinalReport) -> str:
    """Format the event summary section."""

    event = report.event
    regions = ", ".join(event.regions) if event.regions else "unspecified"
    nodes = _format_nodes(event.supply_chain_nodes) if event.supply_chain_nodes else "unspecified"
    return "\n".join(
        [
            "## Event Summary",
            f"- Type: {_event_type_label(event.event_type)}",
            f"- Regions: {regions}",
            f"- Key Nodes: {nodes}",
        ]
    )


def _historical_cases(report: FinalReport, verbose: bool = False) -> str:
    """Format the top three retrieved historical cases."""

    lines = ["## Top 3 Retrieved Historical Cases"]
    for case in report.retrieved_case_summaries[:3]:
        label = case.get("event_name", "Unknown case")
        if verbose:
            label = f"{label} [{case.get('case_id', 'unknown')}]"
        lines.append(f"- {label}")
    return "\n".join(lines)


def _transmission_chain(report: FinalReport) -> str:
    """Format a compact human-readable transmission chain."""

    if report.event.event_type == "technology_export_controls":
        return _technology_export_control_chain()

    event = report.event
    nodes = _important_nodes(report.transmission_chain.affected_nodes)
    uncertainty = _uncertainty_step(report)
    steps = [
        _shock_sentence(event.shock_direction, event.title),
        f"Pressure concentrates in {_format_nodes(nodes)}",
    ]
    if uncertainty:
        steps.append(uncertainty)
    steps.extend(
        [
            "Historical analogs support risk transmission",
            "Secondary exposure channels",
        ]
    )

    lines = ["## Transmission Chain"]
    for index, step in enumerate(steps[:5], start=1):
        lines.append(f"{index}. {step}")
    return "\n".join(lines)


def _technology_export_control_chain() -> str:
    """Format a technology export-control transmission chain."""

    steps = [
        "Export controls restrict access to advanced chips, chipmaking equipment, or design tools",
        "Pressure concentrates in semiconductor equipment, AI chips, EDA software, and foundry nodes",
        "Retrieved historical analogs support technology-access and compliance-risk channels",
        "Mapped assets are secondary risk watchlist candidates, not trading signals",
    ]
    lines = ["## Transmission Chain"]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step}")
    return "\n".join(lines)


def _asset_watchlist(report: FinalReport, verbose: bool = False) -> str:
    """Format the grouped secondary asset watchlist."""

    lines = ["## Secondary Asset Watchlist"]
    group_limits = {
        "historical_supported": 6,
        "sector_proxy": 4,
        "inference_only": 8,
    }

    for level in EVIDENCE_LEVELS:
        assets = report.secondary_asset_watchlist.get(level, [])
        if level == "inference_only" and not assets:
            continue

        assets = assets[: group_limits[level]]
        lines.append(f"### {_title_case_level(level)}")
        if not assets:
            lines.append("- None")
            continue

        for asset in assets:
            confidence = asset.get("confidence", "n/a")
            if isinstance(confidence, float):
                confidence = f"{confidence:.2f}"
            lines.append(
                "- "
                f"{asset.get('ticker', 'n/a')} | "
                f"{asset.get('asset_name', 'Unknown asset')} | "
                f"{asset.get('supply_chain_node', 'unknown_node')} | "
                f"confidence: {confidence}"
            )
            if verbose and asset.get("reason"):
                lines.append(f"  - {asset['reason']}")
    return "\n".join(lines)


def _important_nodes(nodes: list[str]) -> list[str]:
    """Select the most readable high-signal affected nodes."""

    preferred = [
        "maritime_chokepoint",
        "container_shipping",
        "freight_routes",
        "marine_insurance",
        "oil_shipping",
        "lng_shipping",
        "energy",
        "semiconductor_equipment",
        "ai_chips",
        "trade_lanes",
    ]
    selected = [node for node in preferred if node in nodes]
    selected.extend(node for node in nodes if node not in selected)
    return selected[:3] or ["affected supply-chain nodes"]


def _format_nodes(nodes: list[str]) -> str:
    """Format normalized nodes as readable phrases."""

    return ", ".join(NODE_LABELS.get(node, node.replace("_", " ")) for node in nodes)


def _event_type_label(event_type: str) -> str:
    """Format normalized event types as readable phrases."""

    return EVENT_TYPE_LABELS.get(event_type, event_type.replace("_", " ").title())


def _shock_sentence(shock_direction: str, title: str) -> str:
    """Convert a normalized shock label into a readable sentence."""

    shock_sentences = {
        "route_disruption_risk": (
            "Regional conflict increases route disruption risk near Red Sea shipping lanes"
        ),
        "shipping_delay_risk": "Shipping disruption increases delay risk across freight routes",
        "technology_access_risk": "Policy restrictions increase technology access risk",
        "energy_supply_disruption_risk": "Infrastructure disruption increases energy supply risk",
        "sanctions_and_energy_flow_risk": "Conflict and sanctions increase energy flow risk",
        "trade_cost_risk": "Trade policy changes increase cross-border cost risk",
        "input_cost_risk": "Energy stress increases agricultural input cost risk",
        "risk_watchlist_candidate": "The event creates a broad risk watchlist signal",
    }
    return shock_sentences.get(shock_direction, title)


def _title_case_level(level: str) -> str:
    """Format evidence levels for display."""

    return level.replace("_", " ").title()


def _uncertainty_step(report: FinalReport) -> str | None:
    """Infer a compact uncertainty step from nodes and chain text."""

    text = " ".join(report.transmission_chain.chain_steps).lower()
    nodes = set(report.transmission_chain.affected_nodes)
    parts: list[str] = []
    if {"oil_shipping", "lng_shipping", "energy"} & nodes or "fuel" in text:
        parts.append("fuel")
    if "marine_insurance" in nodes or "insurance" in text:
        parts.append("insurance")
    if {"freight_routes", "container_shipping", "logistics"} & nodes or "freight" in text:
        parts.append("freight")

    if not parts:
        return None
    return f"{', '.join(parts)} uncertainty can widen secondary exposure channels"
