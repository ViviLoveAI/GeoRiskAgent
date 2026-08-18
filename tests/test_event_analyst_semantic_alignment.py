from src.agents.event_analyst import analyze_event


TARIFF_CONTEXT = (
    "US-China Tariff Escalation\n"
    "Context: The US raises tariffs on Chinese industrial goods and imported components,\n"
    "increasing input costs for manufacturers and encouraging companies to shift\n"
    "sourcing toward Mexico and Southeast Asia. The disruption may affect trade\n"
    "lanes, freight routes, logistics, and downstream manufacturing supply chains."
)


def test_tariff_escalation_does_not_match_war_inside_toward():
    event = analyze_event(TARIFF_CONTEXT)

    assert event.title == "US-China Tariff Escalation"
    assert event.event_type == "trade_policy_and_tariffs"
    assert "tariff" in event.risk_factors
    assert "war" not in event.risk_factors
    assert {"trade_lanes", "customs", "manufacturing_inputs", "logistics"}.issubset(
        set(event.supply_chain_nodes)
    )
    assert "energy" not in event.supply_chain_nodes
    assert "lng_shipping" not in event.supply_chain_nodes
    assert "refining" not in event.supply_chain_nodes
    assert "petrochemicals" not in event.supply_chain_nodes


def test_trade_war_phrase_still_matches_trade_policy_rule():
    event = analyze_event("US-China trade war raises tariffs on imported components.")

    assert event.event_type == "trade_policy_and_tariffs"
    assert "trade war" in event.risk_factors


def test_red_sea_shipping_disruption_retains_maritime_semantics():
    event = analyze_event(
        "Red Sea Shipping Disruption. Regional conflict disrupts shipping routes."
    )

    assert event.event_type == "maritime_security_disruption"
    assert "maritime_chokepoint" in event.supply_chain_nodes
    assert "marine_insurance" in event.supply_chain_nodes
    assert "freight_routes" in event.supply_chain_nodes


def test_energy_fertilizer_shock_retains_energy_semantics():
    event = analyze_event(
        "Energy & Fertilizer Shock. Natural gas disruptions raise fertilizer input costs."
    )

    assert event.event_type == "energy_and_agricultural_input_shock"
    assert "energy" in event.supply_chain_nodes
    assert "fertilizer" in event.supply_chain_nodes
    assert "petrochemicals" in event.supply_chain_nodes
