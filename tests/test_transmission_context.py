from src.validation.transmission_context import (
    COMPATIBLE,
    INCOMPATIBLE,
    INSUFFICIENT_CONTEXT,
    REVIEW_CANONICAL_CONTEXT_FAMILIES,
    mechanism_compatibility,
    mechanism_compatibility_with_family_review,
    support_diagnostics,
    support_diagnostics_with_family_review,
)


def test_same_canonical_context_forms_compatible_vote():
    current = _ctx("critical_material_input_constraint", "upstream_input", "input_access_restriction")
    support = _ctx("critical_material_input_constraint", "upstream_input", "input_access_restriction")

    decision = mechanism_compatibility(current, support)

    assert decision.status == COMPATIBLE
    assert "canonical" in decision.reason


def test_contextual_background_role_is_not_a_mechanism_vote():
    current = _ctx("regional_security_context", "direct_disruption_target", "security_risk")
    support = _ctx("regional_security_context", "contextual_background", "security_risk")

    decision = mechanism_compatibility(current, support)

    assert decision.status == INCOMPATIBLE
    assert "contextual background" in decision.reason


def test_incompatible_constraint_and_context_do_not_match():
    current = _ctx("airspace_route_disruption", "direct_disruption_target", "route_disruption")
    support = _ctx("critical_material_input_constraint", "upstream_input", "input_access_restriction")

    decision = mechanism_compatibility(current, support)

    assert decision.status == INCOMPATIBLE


def test_canonical_family_allows_raw_vocabulary_mismatch():
    current = _ctx("critical_material_input_constraint", "upstream_input", "input_access_restriction")
    support = _ctx("critical_material_compliance_constraint", "upstream_input", "compliance_constraint")

    decision = mechanism_compatibility(current, support)

    assert decision.status == COMPATIBLE
    assert "family" in decision.reason


def test_insufficient_context_does_not_auto_accept():
    current = _ctx("critical_material_input_constraint", "upstream_input", "input_access_restriction")
    support = {"canonical_context": "unknown", "target_node_role": "upstream_input"}

    decision = mechanism_compatibility(current, support)

    assert decision.status == INSUFFICIENT_CONTEXT


def test_support_diagnostics_is_deterministic_and_counts_three_states():
    current = _ctx("critical_material_input_constraint", "upstream_input", "input_access_restriction")
    contexts = [
        {"case_id": "case_1", **_ctx("critical_material_input_constraint", "upstream_input", "input_access_restriction")},
        {"case_id": "case_2", **_ctx("regional_security_context", "contextual_background", "security_risk")},
        {"case_id": "case_3", "canonical_context": "unknown", "target_node_role": "upstream_input"},
    ]

    first = support_diagnostics(current, contexts)
    second = support_diagnostics(current, contexts)

    assert first == second
    assert first["compatible_support_count"] == 1
    assert first["incompatible_support_count"] == 1
    assert first["insufficient_context_count"] == 1
    assert first["candidate_under_structured_rule"] is False


def test_review_family_hierarchy_matches_maritime_route_subtypes():
    current = _ctx("maritime_route_security_constraint", "transmission_channel", "route_disruption")
    support = _ctx("maritime_route_capacity_constraint", "direct_disruption_target", "route_disruption")

    decision = mechanism_compatibility_with_family_review(current, support)

    assert decision.status == COMPATIBLE
    assert "family" in decision.reason


def test_review_active_role_compatibility_does_not_promote_background():
    current = _ctx("maritime_route_security_constraint", "transmission_channel", "route_disruption")
    support = _ctx("maritime_route_security_constraint", "contextual_background", "route_disruption")

    decision = mechanism_compatibility_with_family_review(current, support)

    assert decision.status == INCOMPATIBLE


def test_downstream_strategic_exposure_is_active_review_role():
    current = _ctx(
        "semiconductor_strategic_downstream_exposure",
        "downstream_strategic_exposure",
        "input_access_restriction",
    )
    support = _ctx(
        "semiconductor_input_access_constraint",
        "downstream_strategic_exposure",
        "security_risk",
    )

    decision = mechanism_compatibility_with_family_review(current, support)

    assert decision.status == COMPATIBLE


def test_freeze_candidate_contains_expected_context_families():
    assert (
        REVIEW_CANONICAL_CONTEXT_FAMILIES["maritime_route_capacity_constraint"]
        == "maritime_route_disruption"
    )
    assert (
        REVIEW_CANONICAL_CONTEXT_FAMILIES["semiconductor_strategic_downstream_exposure"]
        == "strategic_technology_downstream_exposure"
    )


def test_energy_trade_access_and_finance_are_same_review_family():
    assert (
        REVIEW_CANONICAL_CONTEXT_FAMILIES["energy_trade_access_constraint"]
        == "energy_trade_constraint"
    )
    assert (
        REVIEW_CANONICAL_CONTEXT_FAMILIES["energy_trade_finance_constraint"]
        == "energy_trade_constraint"
    )


def test_energy_trade_sibling_family_match_is_distinct_from_exact_match():
    exact = mechanism_compatibility_with_family_review(
        _ctx("energy_trade_access_constraint", "downstream_exposure", "trade_access_restriction"),
        _ctx("energy_trade_access_constraint", "downstream_exposure", "trade_access_restriction"),
    )
    sibling = mechanism_compatibility_with_family_review(
        _ctx("energy_trade_access_constraint", "downstream_exposure", "trade_access_restriction"),
        _ctx("energy_trade_finance_constraint", "downstream_exposure", "financing_constraint"),
    )

    assert exact.status == COMPATIBLE
    assert sibling.status == COMPATIBLE
    assert "same canonical transmission context" in exact.reason
    assert "family" in sibling.reason


def test_different_energy_mechanism_family_is_rejected():
    current = _ctx("energy_trade_access_constraint", "downstream_exposure", "trade_access_restriction")
    support = _ctx("energy_feedstock_input_constraint", "upstream_input", "input_shortage")

    decision = mechanism_compatibility_with_family_review(current, support)

    assert decision.status == INCOMPATIBLE


def test_same_energy_node_alone_does_not_create_family_compatibility():
    current = {
        **_ctx("energy_trade_access_constraint", "downstream_exposure", "trade_access_restriction"),
        "node": "energy",
    }
    support = {
        **_ctx("energy_distribution_cyber_capacity_constraint", "direct_disruption_target", "capacity_reduction"),
        "node": "energy",
    }

    decision = mechanism_compatibility_with_family_review(current, support)

    assert current["node"] == support["node"]
    assert decision.status == INCOMPATIBLE


def test_background_role_blocks_energy_family_vote():
    current = _ctx("energy_trade_access_constraint", "downstream_exposure", "trade_access_restriction")
    support = _ctx("energy_trade_finance_constraint", "contextual_background", "financing_constraint")

    decision = mechanism_compatibility_with_family_review(current, support)

    assert decision.status == INCOMPATIBLE


def test_energy_family_does_not_change_agriculture_false_rejection():
    from scripts.validate_mechanism_freeze_candidate import (
        EXPANDED_CASE_CONTEXTS,
        EXPANDED_CURRENT_CONTEXTS,
    )

    current = EXPANDED_CURRENT_CONTEXTS[("dev_food_export_restriction", "agriculture")]
    support_contexts = [
        {
            "case_id": "case_2021_belarus_potash_sanctions",
            **EXPANDED_CASE_CONTEXTS[("case_2021_belarus_potash_sanctions", "agriculture")],
        },
        {
            "case_id": "case_2022_russia_fertilizer_export_restrictions",
            **EXPANDED_CASE_CONTEXTS[("case_2022_russia_fertilizer_export_restrictions", "agriculture")],
        },
    ]

    diagnostics = support_diagnostics_with_family_review(current, support_contexts)

    assert diagnostics["candidate_under_structured_rule"] is False
    assert diagnostics["compatible_support_count"] == 0


def test_agriculture_contexts_are_not_collapsed_into_broad_family():
    assert "agricultural_export_trade_constraint" not in REVIEW_CANONICAL_CONTEXT_FAMILIES
    assert "agricultural_input_constraint" not in REVIEW_CANONICAL_CONTEXT_FAMILIES


def test_agriculture_development_label_is_granularity_corrected():
    from scripts.validate_mechanism_freeze_candidate import EXPANDED_INSTANCES

    agriculture = [
        instance for instance in EXPANDED_INSTANCES
        if instance["event_id"] == "dev_food_export_restriction"
        and instance["node"] == "agriculture"
    ][0]

    assert agriculture["mechanism_target"] == "weak_cooccurrence_expected"


def test_energy_family_does_not_resolve_ambiguous_trade_lanes():
    from scripts.validate_mechanism_freeze_candidate import (
        EXPANDED_CASE_CONTEXTS,
        EXPANDED_CURRENT_CONTEXTS,
        _missing_context,
    )

    node = "trade_lanes"
    current = EXPANDED_CURRENT_CONTEXTS.get(("dev_lng_shipping_sanctions", node))
    support_contexts = [
        {
            "case_id": "case_2023_arctic_lng_russian_energy_shipping_sanctions",
            **EXPANDED_CASE_CONTEXTS.get(
                ("case_2023_arctic_lng_russian_energy_shipping_sanctions", node),
                _missing_context(node),
            ),
        },
        {
            "case_id": "case_2018_2019_us_china_tariffs",
            **EXPANDED_CASE_CONTEXTS[("case_2018_2019_us_china_tariffs", node)],
        },
    ]

    diagnostics = support_diagnostics_with_family_review(current, support_contexts)

    assert diagnostics["candidate_under_structured_rule"] is False
    assert diagnostics["insufficient_context_count"] == 2


def test_support_threshold_remains_two_votes():
    current = _ctx("energy_trade_access_constraint", "downstream_exposure", "trade_access_restriction")
    support_contexts = [
        {
            "case_id": "case_1",
            **_ctx("energy_trade_access_constraint", "downstream_exposure", "trade_access_restriction"),
        }
    ]

    diagnostics = support_diagnostics_with_family_review(current, support_contexts)

    assert diagnostics["compatible_support_count"] == 1
    assert diagnostics["candidate_under_structured_rule"] is False


def _ctx(canonical_context: str, role: str, constraint_type: str) -> dict[str, str]:
    return {
        "canonical_context": canonical_context,
        "target_node_role": role,
        "constraint_type": constraint_type,
    }
