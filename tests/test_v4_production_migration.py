from pathlib import Path

from src.agents.transmission_builder import (
    MIN_CASE_SUPPORT_FOR_SECOND_ORDER,
    build_transmission_chain,
)
from src.config import USE_MECHANISM_COMPATIBLE_SUPPORT
from src.mechanism_context import (
    CANONICAL_FAMILY_VERSION,
    COMPATIBLE_SUPPORT_THRESHOLD,
    MECHANISM_COMPATIBILITY_VERSION,
    TRANSMISSION_CONTEXT_VERSION,
    canonical_family,
    support_diagnostics,
)
from src.schemas import EventAnalysis, RetrievedCase
from src.transmission_context_store import (
    load_historical_contexts,
    missing_context,
    project_current_event_context,
)


def test_transmission_context_v1_versioning_is_explicit():
    assert TRANSMISSION_CONTEXT_VERSION == "transmission_context_v1"
    assert CANONICAL_FAMILY_VERSION == "canonical_family_v1"
    assert MECHANISM_COMPATIBILITY_VERSION == "mechanism_compatibility_candidate_v1"


def test_canonical_family_normalization_is_narrow():
    assert canonical_family("energy_trade_access_constraint") == "energy_trade_constraint"
    assert canonical_family("energy_trade_finance_constraint") == "energy_trade_constraint"
    assert canonical_family("energy_feedstock_input_constraint") == "energy_feedstock_input_constraint"
    assert canonical_family("agricultural_export_trade_constraint") == "agricultural_export_trade_constraint"
    assert canonical_family("agricultural_input_constraint") == "agricultural_input_constraint"


def test_historical_context_sidecar_loads_node_specific_contexts():
    contexts = load_historical_contexts()

    food = contexts[("case_2022_india_wheat_export_ban", "grain_exports")]
    agriculture = contexts[("case_2022_russia_fertilizer_export_restrictions", "agriculture")]

    assert food["canonical_context"] == "food_export_trade_constraint"
    assert agriculture["canonical_context"] == "agricultural_input_constraint"
    assert food["node"] != agriculture["node"]


def test_old_migrated_contexts_are_preserved_after_full_migration():
    contexts = load_historical_contexts()

    red_sea = contexts[("case_2023_red_sea_attacks", "container_shipping")]

    assert red_sea["canonical_context"] == "maritime_route_security_constraint"
    assert red_sea["constraint_type"] == "route_disruption"
    assert red_sea["target_node_role"] == "direct_disruption_target"


def test_new_full_kb_sidecar_entries_parse_correctly():
    contexts = load_historical_contexts()

    customs = contexts[("case_2018_2019_us_china_tariffs", "customs")]
    freight = contexts[("case_1987_1988_tanker_war_reflagging", "freight_routes")]

    assert customs["canonical_context"] == "tariff_customs_compliance_constraint"
    assert customs["target_node_role"] == "compliance_channel"
    assert freight["canonical_context"] == "maritime_route_security_constraint"
    assert freight["target_node_role"] == "transmission_channel"


def test_unresolved_manufacturing_inputs_are_not_migrated_or_voting():
    contexts = load_historical_contexts()
    unresolved = missing_context("manufacturing_inputs")

    assert not any(node == "manufacturing_inputs" for _, node in contexts)
    diagnostics = support_diagnostics(
        unresolved,
        [
            {"case_id": "case_1", **unresolved},
            {"case_id": "case_2", **unresolved},
        ],
    )
    assert diagnostics["candidate_under_structured_rule"] is False
    assert diagnostics["insufficient_context_count"] == 2


def test_current_event_projection_is_node_specific_for_second_order_candidates():
    event = EventAnalysis(
        title="Food export restriction announced",
        summary="A government announced a wheat and food export ban affecting grain trade.",
        event_type="food export ban",
        supply_chain_nodes=["grain_exports"],
        shock_direction="export restriction",
    )

    grain = project_current_event_context(event, "grain_exports")
    agriculture = project_current_event_context(event, "agriculture")

    assert grain is not None
    assert agriculture is not None
    assert grain["target_node_role"] == "direct_disruption_target"
    assert agriculture["target_node_role"] == "downstream_exposure"
    assert grain["canonical_context"] != agriculture["canonical_context"]


def test_ambiguous_context_can_remain_unresolved():
    event = EventAnalysis(
        title="LNG sanctions",
        summary="Sanctions disrupted Arctic LNG shipping.",
        event_type="energy sanctions",
        supply_chain_nodes=["lng_shipping"],
        shock_direction="sanctions",
    )

    assert project_current_event_context(event, "trade_lanes") is None
    assert missing_context("trade_lanes")["canonical_context"] == "unknown"


def test_legacy_path_remains_default_and_uses_raw_node_support(monkeypatch):
    monkeypatch.setattr(
        "src.agents.transmission_builder.load_historical_contexts",
        lambda: {},
    )
    event = _event(["grain_exports"])
    cases = _cases_with_agriculture_support()

    chain = build_transmission_chain(event, cases)

    assert USE_MECHANISM_COMPATIBLE_SUPPORT is False
    assert "agriculture" in chain.affected_nodes
    assert chain.node_evidence_levels["agriculture"] == "case_grounded"


def test_v4_path_only_with_flag_and_uses_mechanism_support(monkeypatch):
    contexts = {
        ("case_2021_belarus_potash_sanctions", "agriculture"): {
            "node": "agriculture",
            "shock_type": "sanctions",
            "constraint_type": "input_shortage",
            "upstream_driver": "potash_fertilizer_restriction",
            "target_node_role": "downstream_exposure",
            "canonical_context": "agricultural_input_constraint",
        },
        ("case_2022_russia_fertilizer_export_restrictions", "agriculture"): {
            "node": "agriculture",
            "shock_type": "export_restriction",
            "constraint_type": "input_shortage",
            "upstream_driver": "fertilizer_export_restriction",
            "target_node_role": "downstream_exposure",
            "canonical_context": "agricultural_input_constraint",
        },
    }
    monkeypatch.setattr(
        "src.agents.transmission_builder.load_historical_contexts",
        lambda: contexts,
    )
    event = _event(["grain_exports"])
    cases = _cases_with_agriculture_support()

    legacy = build_transmission_chain(event, cases, use_mechanism_compatible_support=False)
    v4 = build_transmission_chain(event, cases, use_mechanism_compatible_support=True)

    assert "agriculture" in legacy.affected_nodes
    assert "agriculture" not in v4.affected_nodes


def test_support_threshold_remains_two():
    assert COMPATIBLE_SUPPORT_THRESHOLD == 2
    assert MIN_CASE_SUPPORT_FOR_SECOND_ORDER == 2
    current = {
        "node": "energy",
        "shock_type": "sanctions",
        "constraint_type": "trade_access_restriction",
        "upstream_driver": "restricted_energy_exports",
        "target_node_role": "downstream_exposure",
        "canonical_context": "energy_trade_access_constraint",
    }
    support = [
        {
            "case_id": "case_1",
            "node": "energy",
            "shock_type": "sanctions",
            "constraint_type": "trade_access_restriction",
            "upstream_driver": "oil_export_sanctions",
            "target_node_role": "downstream_exposure",
            "canonical_context": "energy_trade_access_constraint",
        }
    ]

    diagnostics = support_diagnostics(current, support)

    assert diagnostics["compatible_support_count"] == 1
    assert diagnostics["candidate_under_structured_rule"] is False


def test_transmission_context_sidecar_exists_after_migration():
    assert Path("data/transmission_context_v1.json").exists()


def _event(nodes: list[str]) -> EventAnalysis:
    return EventAnalysis(
        title="Food export restriction announced",
        summary="A government announced a wheat and food export ban affecting grain trade.",
        event_type="food export ban",
        supply_chain_nodes=nodes,
        shock_direction="export restriction",
    )


def _cases_with_agriculture_support() -> list[RetrievedCase]:
    return [
        RetrievedCase(
            case_id="case_2021_belarus_potash_sanctions",
            title="Belarus potash sanctions",
            summary="Potash sanctions affected fertilizer supply.",
            supply_chain_nodes=["agriculture"],
        ),
        RetrievedCase(
            case_id="case_2022_russia_fertilizer_export_restrictions",
            title="Russia fertilizer export restrictions",
            summary="Fertilizer export restrictions affected crop inputs.",
            supply_chain_nodes=["agriculture"],
        ),
    ]
