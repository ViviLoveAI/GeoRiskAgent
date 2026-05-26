"""Regression check for LLM Event Analyst supporting phrase normalization."""

from src.agents.llm_event_analyst import (
    LLMEventAnalysisCandidate,
    _normalize_supporting_phrases,
)


def main() -> None:
    """Verify string and missing supporting phrase fields normalize to lists."""

    payload = {
        "title": "Red Sea shipping disruption",
        "summary": "Red Sea shipping routes face disruption.",
        "event_type": "maritime_security_disruption",
        "regions": ["Middle East"],
        "industries": ["shipping"],
        "supply_chain_nodes": ["maritime_chokepoint"],
        "shock_direction": "route_disruption_risk",
        "risk_factors": ["Red Sea"],
        "supporting_phrases": {
            "event_type": "Red Sea shipping routes",
            "supply_chain_nodes": "shipping routes",
            "extra": 42,
        },
    }

    _normalize_supporting_phrases(payload)
    candidate = LLMEventAnalysisCandidate.model_validate(payload)

    assert candidate.supporting_phrases["event_type"] == ["Red Sea shipping routes"]
    assert candidate.supporting_phrases["supply_chain_nodes"] == ["shipping routes"]
    assert candidate.supporting_phrases["extra"] == ["42"]

    missing_payload = dict(payload)
    missing_payload["supporting_phrases"] = {"event_type": None}
    _normalize_supporting_phrases(missing_payload)
    missing_candidate = LLMEventAnalysisCandidate.model_validate(missing_payload)

    assert missing_candidate.supporting_phrases["event_type"] == []
    assert missing_candidate.supporting_phrases["supply_chain_nodes"] == []
    print("LLM supporting phrase normalization check passed.")


if __name__ == "__main__":
    main()
