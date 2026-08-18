from scripts.audit_context_coverage import (
    build_context_coverage_rows,
    summarize_context_coverage,
)
from scripts.validate_mechanism_freeze_candidate import (
    EXPANDED_CASE_CONTEXTS,
    EXPANDED_CURRENT_CONTEXTS,
)
from src.validation.transmission_context import support_diagnostics_with_family_review


def test_context_coverage_does_not_count_unknown_as_informative():
    rows = [
        {
            "source_type": "current_event_projection",
            "event_id": "event",
            "case_id": "",
            "node": "node",
            "has_context": True,
            "missing_fields": "",
            "non_informative_fields": "shock_type",
            "gap_type": "partial_context",
            "notes": "",
        }
    ]

    summary = summarize_context_coverage(rows)

    assert summary["overall_informative_coverage"]["covered"] == 0
    assert summary["partial_node_count"] == 1


def test_context_coverage_separates_historical_and_current_sources():
    rows = build_context_coverage_rows()
    summary = summarize_context_coverage(rows)

    assert summary["historical_relevant_nodes"] > 0
    assert summary["current_event_relevant_nodes"] > 0
    assert (
        summary["historical_relevant_nodes"] + summary["current_event_relevant_nodes"]
        == summary["total_relevant_nodes"]
    )


def test_current_projection_is_node_specific_not_mechanically_copied():
    container = EXPANDED_CURRENT_CONTEXTS[
        ("dev_red_sea_shipping_disruption", "container_shipping")
    ]
    insurance = EXPANDED_CURRENT_CONTEXTS[
        ("dev_red_sea_shipping_disruption", "marine_insurance")
    ]
    defense = EXPANDED_CURRENT_CONTEXTS[
        ("dev_red_sea_shipping_disruption", "defense")
    ]

    assert container["target_node_role"] == "direct_disruption_target"
    assert insurance["target_node_role"] == "financing_or_insurance_channel"
    assert defense["target_node_role"] == "contextual_background"
    assert len({
        container["constraint_type"],
        insurance["constraint_type"],
        defense["constraint_type"],
    }) > 1


def test_existing_complete_contexts_remain_informative():
    context = EXPANDED_CASE_CONTEXTS[
        ("case_2023_red_sea_attacks", "container_shipping")
    ]

    assert context["canonical_context"] == "maritime_route_security_constraint"
    assert context["target_node_role"] == "direct_disruption_target"
    assert all(context[field] != "unknown" for field in [
        "shock_type",
        "constraint_type",
        "upstream_driver",
        "target_node_role",
        "canonical_context",
    ])


def test_unresolved_ambiguous_context_remains_missing():
    rows = build_context_coverage_rows()
    missing_trade_lanes = [
        row for row in rows
        if row["node"] == "trade_lanes"
        and (
            row["event_id"] == "dev_lng_shipping_sanctions"
            or row["case_id"] == "case_2023_arctic_lng_russian_energy_shipping_sanctions"
        )
    ]

    assert len(missing_trade_lanes) == 2
    assert {row["gap_type"] for row in missing_trade_lanes} == {"missing_context"}


def test_contextual_background_still_cannot_create_weak_support_vote():
    current = EXPANDED_CURRENT_CONTEXTS[("dev_cyber_port_disruption", "energy")]
    support_contexts = [
        {
            "case_id": "case_2021_colonial_pipeline_ransomware",
            **EXPANDED_CASE_CONTEXTS[("case_2021_colonial_pipeline_ransomware", "energy")],
        },
        {
            "case_id": "case_2022_gas_fertilizer_shock",
            **EXPANDED_CASE_CONTEXTS[("case_2022_gas_fertilizer_shock", "energy")],
        },
    ]

    diagnostics = support_diagnostics_with_family_review(current, support_contexts)

    assert diagnostics["candidate_under_structured_rule"] is False
    assert diagnostics["compatible_support_count"] == 0
    assert diagnostics["incompatible_support_count"] == 2
