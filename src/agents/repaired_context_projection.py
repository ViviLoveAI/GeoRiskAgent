"""V5-only current-context projection for repaired node candidates.

The canonical V4 projector remains unchanged. This module first delegates to
that projector; when it cannot produce context for a repaired candidate, it
adds narrowly scoped deterministic coverage for repaired-node hypotheses.
"""

from __future__ import annotations

import re

from src.schemas import EventAnalysis
from src.transmission_context_store import project_current_event_context
from src.v5_models import CurrentContextProjection


def project_repaired_node_context(
    event: EventAnalysis,
    node: str,
) -> CurrentContextProjection:
    """Project current-event context for one V5 repaired candidate."""

    existing = project_current_event_context(event, node)
    if existing is not None:
        return CurrentContextProjection(
            node=node,
            projection_attempted=True,
            projection_source="v4_project_current_event_context",
            projection_status="existing_v4_context",
            projected_current_context=existing,
            applicability_status="grounded",
            applicability_reason="canonical V4 current-event projection exists",
        )

    text = _event_text(event)
    projected, cues, applicability_status, applicability_reason = _project_v5_repaired_context(text, node)
    if projected is None:
        return CurrentContextProjection(
            node=node,
            projection_attempted=True,
            projection_source="v5_repaired_node_projection_v1",
            projection_status="projection_unavailable",
            projected_current_context=None,
            projection_cues=cues,
            applicability_status=applicability_status,
            applicability_reason=applicability_reason,
        )

    return CurrentContextProjection(
        node=node,
        projection_attempted=True,
        projection_source="v5_repaired_node_projection_v1",
        projection_status="projected",
        projected_current_context=projected,
        projection_cues=cues,
        applicability_status=applicability_status,
        applicability_reason=applicability_reason,
    )


def _project_v5_repaired_context(
    text: str,
    node: str,
) -> tuple[dict[str, str] | None, list[str], str, str]:
    if node == "maritime_chokepoint":
        grounding_cues = _matched_cues(
            text,
            [
                "hormuz",
                "strait",
                "safe passage",
                "suez",
                "bab el-mandeb",
                "canal",
                "chokepoint",
            ],
        )
        domain_cues = _matched_cues(text, ["maritime", "shipping", "vessel", "tanker"])
        cues = _dedupe([*grounding_cues, *domain_cues])
        if not cues:
            return None, [], "insufficient", "no current-event maritime cues matched"
        applicability_status = (
            "grounded" if grounding_cues else "domain_association_only"
        )
        applicability_reason = (
            "current event names a route/chokepoint/safe-passage mechanism"
            if grounding_cues
            else "current event contains maritime domain cues but no explicit route or chokepoint mechanism"
        )
        return _ctx(
            node,
            "military_escalation" if _has_any(text, ["security", "concern"]) else "physical_disruption",
            "route_disruption",
            "maritime_safe_passage_security_risk",
            "direct_disruption_target",
            "maritime_route_security_constraint",
        ), cues, applicability_status, applicability_reason
    if node == "cyber_infrastructure":
        grounding_cues = _matched_cues(
            text,
            ["cyber", "dns", "hijack", "digital infrastructure", "gru"],
        )
        disruption_cues = _matched_cues(text, ["disruption", "disrupt", "attack"])
        cues = _dedupe([*grounding_cues, *disruption_cues])
        if not grounding_cues:
            return None, cues, "insufficient", "no current-event cyber-infrastructure mechanism cues matched"
        applicability_status = (
            "grounded" if disruption_cues else "domain_association_only"
        )
        applicability_reason = (
            "current event names cyber/DNS/GRU cues and disruption language"
            if disruption_cues
            else "current event contains cyber domain cues but no explicit disruption mechanism"
        )
        return _ctx(
            node,
            "cyber_disruption",
            "capacity_reduction",
            "dns_hijacking_disruption",
            "direct_disruption_target",
            "logistics_cyber_capacity_constraint",
        ), cues, applicability_status, applicability_reason
    return None, [], "insufficient", "no V5 repaired-node projection rule matched"


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


def _event_text(event: EventAnalysis) -> str:
    parts = [
        event.title,
        event.summary,
        event.event_type,
        event.shock_direction,
        *event.industries,
        *event.supply_chain_nodes,
        *event.risk_factors,
    ]
    return " ".join(part.lower() for part in parts if part)


def _has_any(text: str, needles: list[str]) -> bool:
    return any(_has(text, needle) for needle in needles)


def _matched_cues(text: str, needles: list[str]) -> list[str]:
    return [needle for needle in needles if _has(text, needle)]


def _has(text: str, needle: str) -> bool:
    if not needle:
        return False
    escaped = re.escape(needle.lower())
    suffix = "" if needle.lower().endswith("s") else "(?:s|ed|ing)?"
    pattern = rf"(?<![a-z0-9]){escaped}{suffix}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
