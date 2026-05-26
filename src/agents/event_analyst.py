"""Deterministic MVP event analyst.

This module uses simple keyword rules to classify geopolitical risk news into
normalized event attributes. It does not predict stock prices or provide
investment advice.
"""

from src.schemas import EventAnalysis


DEFAULT_EVENT_TYPE = "geopolitical_risk_event"
DEFAULT_SHOCK_DIRECTION = "risk_watchlist_candidate"

EVENT_RULES = [
    {
        "event_type": "taiwan_strait_semiconductor_risk",
        "keywords": ["taiwan strait", "taiwan blockade", "taiwan military", "taiwan semiconductor"],
        "regions": ["East Asia", "Global"],
        "industries": ["semiconductors", "electronics", "AI chips", "data centers", "defense"],
        "supply_chain_nodes": [
            "foundry",
            "ai_chips",
            "semiconductor_equipment",
            "data_centers",
            "manufacturing_inputs",
            "defense",
        ],
        "shock_direction": "semiconductor_supply_disruption_risk",
    },
    {
        "event_type": "critical_minerals_export_controls",
        "keywords": [
            "rare earth",
            "rare earths",
            "critical minerals",
            "gallium",
            "germanium",
            "graphite",
            "battery materials",
            "mineral export controls",
        ],
        "regions": ["East Asia", "Global"],
        "industries": ["critical minerals", "rare earths", "battery materials", "electronics"],
        "supply_chain_nodes": [
            "critical_minerals",
            "rare_earths",
            "gallium_germanium_graphite",
            "manufacturing_inputs",
            "customs",
        ],
        "shock_direction": "critical_minerals_access_risk",
    },
    {
        "event_type": "canal_shipping_disruption",
        "keywords": ["panama canal", "canal drought", "low water levels", "draft restrictions"],
        "regions": ["Latin America", "North America", "Global"],
        "industries": ["container shipping", "bulk shipping", "LNG shipping", "agriculture", "logistics"],
        "supply_chain_nodes": [
            "panama_canal",
            "maritime_chokepoint",
            "container_shipping",
            "freight_routes",
            "lng_shipping",
            "agriculture",
            "logistics",
        ],
        "shock_direction": "canal_capacity_disruption_risk",
    },
    {
        "event_type": "grain_export_disruption",
        "keywords": ["black sea grain", "grain corridor", "grain export", "wheat exports", "corn exports"],
        "regions": ["Eastern Europe", "Black Sea", "Global"],
        "industries": ["agriculture", "grain trading", "shipping", "fertilizer", "food production"],
        "supply_chain_nodes": [
            "grain_exports",
            "agriculture",
            "freight_routes",
            "maritime_chokepoint",
            "fertilizer",
            "logistics",
        ],
        "shock_direction": "grain_export_disruption_risk",
    },
    {
        "event_type": "oil_policy_shock",
        "keywords": ["opec", "opec+", "production cut", "oil supply policy", "crude production cut"],
        "regions": ["Middle East", "Global"],
        "industries": ["oil", "refining", "petrochemicals", "aviation", "transportation"],
        "supply_chain_nodes": ["energy", "oil_shipping", "refining", "petrochemicals", "aviation"],
        "shock_direction": "oil_supply_policy_risk",
    },
    {
        "event_type": "regional_energy_escalation",
        "keywords": ["israel-iran", "israel iran", "iran escalation", "regional escalation", "persian gulf escalation"],
        "regions": ["Middle East", "Global"],
        "industries": ["oil", "LNG", "tanker shipping", "marine insurance", "refining", "defense"],
        "supply_chain_nodes": [
            "defense",
            "energy",
            "maritime_chokepoint",
            "oil_shipping",
            "lng_shipping",
            "marine_insurance",
            "refining",
        ],
        "shock_direction": "regional_energy_escalation_risk",
    },
    {
        "event_type": "cyber_infrastructure_disruption",
        "keywords": ["cyberattack", "cyber attack", "ransomware", "port cyber", "pipeline cyber", "critical infrastructure cyber"],
        "regions": ["North America", "Europe", "Global"],
        "industries": ["energy infrastructure", "ports", "logistics", "cybersecurity", "transportation"],
        "supply_chain_nodes": [
            "cyber_infrastructure",
            "pipeline_infrastructure",
            "ports",
            "energy",
            "logistics",
            "freight_routes",
        ],
        "shock_direction": "cyber_operational_disruption_risk",
    },
    {
        "event_type": "defense_spending_shock",
        "keywords": ["defense spending", "defence spending", "military budget", "defense budget", "munitions", "missile defense"],
        "regions": ["Europe", "North America", "Global"],
        "industries": ["defense", "aerospace", "electronics", "cybersecurity", "manufacturing"],
        "supply_chain_nodes": [
            "defense",
            "manufacturing_inputs",
            "semiconductor_equipment",
            "ai_chips",
            "cyber_infrastructure",
        ],
        "shock_direction": "defense_procurement_risk",
    },
    {
        "event_type": "uranium_supply_chain_risk",
        "keywords": ["uranium", "nuclear fuel", "enrichment", "conversion services", "nuclear fuel cycle"],
        "regions": ["Europe", "North America", "Central Asia", "Global"],
        "industries": ["uranium mining", "nuclear fuel", "utilities", "energy"],
        "supply_chain_nodes": [
            "uranium",
            "nuclear_fuel",
            "energy",
            "trade_lanes",
            "customs",
            "manufacturing_inputs",
        ],
        "shock_direction": "nuclear_fuel_supply_risk",
    },
    {
        "event_type": "maritime_security_disruption",
        "keywords": ["red sea", "houthi", "vessel attack", "shipping attack", "bab el-mandeb"],
        "regions": ["Middle East", "Red Sea"],
        "industries": ["container shipping", "energy shipping", "logistics", "insurance"],
        "supply_chain_nodes": [
            "maritime_chokepoint",
            "container_shipping",
            "freight_routes",
            "marine_insurance",
            "oil_shipping",
            "lng_shipping",
            "logistics",
        ],
        "shock_direction": "route_disruption_risk",
    },
    {
        "event_type": "shipping_chokepoint_disruption",
        "keywords": ["suez", "canal", "chokepoint", "port closure", "blocked waterway"],
        "regions": ["Middle East", "Europe", "Asia"],
        "industries": ["container shipping", "logistics", "retail", "manufacturing"],
        "supply_chain_nodes": [
            "maritime_chokepoint",
            "container_shipping",
            "freight_routes",
            "ports",
            "logistics",
        ],
        "shock_direction": "shipping_delay_risk",
    },
    {
        "event_type": "technology_export_controls",
        "keywords": [
            "export control",
            "export controls",
            "entity list",
            "semiconductor",
            "chip",
            "asml",
            "huawei",
            "lithography",
        ],
        "regions": ["North America", "East Asia", "Europe"],
        "industries": ["semiconductors", "chip equipment", "electronics"],
        "supply_chain_nodes": [
            "semiconductor_equipment",
            "ai_chips",
            "eda_software",
            "foundry",
            "data_centers",
            "customs",
        ],
        "shock_direction": "technology_access_risk",
    },
    {
        "event_type": "energy_infrastructure_disruption",
        "keywords": ["oil facility", "refinery attack", "pipeline attack", "abqaiq", "khurais"],
        "regions": ["Middle East", "Global"],
        "industries": ["oil", "refining", "petrochemicals", "aviation"],
        "supply_chain_nodes": ["energy", "refining", "petrochemicals", "aviation", "oil_shipping"],
        "shock_direction": "energy_supply_disruption_risk",
    },
    {
        "event_type": "war_and_sanctions_energy_disruption",
        "keywords": ["war", "invasion", "sanctions", "russia", "ukraine", "pipeline gas"],
        "regions": ["Europe", "Eastern Europe", "Global"],
        "industries": ["natural gas", "oil", "power generation", "chemicals"],
        "supply_chain_nodes": ["energy", "lng_shipping", "refining", "petrochemicals", "manufacturing_inputs"],
        "shock_direction": "sanctions_and_energy_flow_risk",
    },
    {
        "event_type": "trade_policy_and_tariffs",
        "keywords": ["tariff", "tariffs", "trade war", "customs", "duties", "trade restrictions"],
        "regions": ["North America", "East Asia", "Global"],
        "industries": ["manufacturing", "agriculture", "consumer goods", "electronics", "logistics"],
        "supply_chain_nodes": ["trade_lanes", "customs", "manufacturing_inputs", "agriculture", "logistics"],
        "shock_direction": "trade_cost_risk",
    },
    {
        "event_type": "energy_and_agricultural_input_shock",
        "keywords": ["fertilizer", "ammonia", "natural gas", "crop input", "food supply"],
        "regions": ["Europe", "Global"],
        "industries": ["natural gas", "fertilizer", "agriculture", "chemicals", "food production"],
        "supply_chain_nodes": ["energy", "fertilizer", "agriculture", "petrochemicals", "manufacturing_inputs"],
        "shock_direction": "input_cost_risk",
    },
]


REGION_KEYWORDS = {
    "Middle East": ["middle east", "red sea", "suez", "hormuz", "saudi", "iran", "yemen"],
    "Latin America": ["panama", "latin america"],
    "Black Sea": ["black sea"],
    "Central Asia": ["kazakhstan", "central asia"],
    "Europe": ["europe", "eu", "netherlands", "germany"],
    "Eastern Europe": ["russia", "ukraine"],
    "East Asia": ["china", "taiwan", "japan", "asia"],
    "North America": ["united states", "u.s.", "us ", "america"],
    "Global": ["global", "worldwide", "international"],
}


def analyze_event(news_text: str) -> EventAnalysis:
    """Analyze news text with simple deterministic keyword rules."""

    if not news_text.strip():
        raise ValueError("news_text must not be empty.")

    text = news_text.lower()
    matched_rule = _match_event_rule(text)
    regions = _dedupe([*matched_rule["regions"], *_infer_regions(text)])

    return EventAnalysis(
        title=_make_title(news_text),
        summary=_make_summary(news_text),
        event_type=matched_rule["event_type"],
        regions=regions,
        industries=list(matched_rule["industries"]),
        supply_chain_nodes=list(matched_rule["supply_chain_nodes"]),
        shock_direction=matched_rule["shock_direction"],
        risk_factors=_matched_keywords(text, matched_rule["keywords"]),
    )


def _match_event_rule(text: str) -> dict:
    """Return the first event rule matched by the news text."""

    for rule in EVENT_RULES:
        if any(keyword in text for keyword in rule["keywords"]):
            return rule

    return {
        "event_type": DEFAULT_EVENT_TYPE,
        "keywords": [],
        "regions": ["Global"],
        "industries": [],
        "supply_chain_nodes": ["broad_etf"],
        "shock_direction": DEFAULT_SHOCK_DIRECTION,
    }


def _infer_regions(text: str) -> list[str]:
    """Infer extra regions from simple keyword matches."""

    return [
        region
        for region, keywords in REGION_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return matched risk keywords for basic traceability."""

    return [keyword for keyword in keywords if keyword in text]


def _make_title(news_text: str) -> str:
    """Create a compact title from the first sentence or opening text."""

    first_sentence = news_text.strip().split(".", maxsplit=1)[0]
    return first_sentence[:120].strip()


def _make_summary(news_text: str) -> str:
    """Create a concise summary from the raw news text."""

    return news_text.strip()[:500]


def _dedupe(values: list[str]) -> list[str]:
    """Preserve order while removing duplicates."""

    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
