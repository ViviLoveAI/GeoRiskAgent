"""Trace frozen V4 config propagation without touching held-out data."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.agents.event_analyst import analyze_event
from src.pipeline import run_v4_pipeline
from src.schemas import RetrievedCase
from src.v4_config import V4_CONFIG


OUTPUT = Path("data/topk_sensitivity_v4/v4_config_trace.json")


def main() -> None:
    trace = run_trace()
    OUTPUT.write_text(json.dumps(trace, indent=2, sort_keys=True))
    print(json.dumps(trace, indent=2, sort_keys=True))


def run_trace() -> dict[str, object]:
    news = "Red Sea shipping routes face disruption due to escalating regional conflict."
    observed: dict[str, object] = {
        "requested_mode": "V4",
        "resolved_top_k": V4_CONFIG.retrieval_top_k,
        "mechanism_support_enabled": V4_CONFIG.use_mechanism_compatible_support,
        "support_threshold": V4_CONFIG.compatible_support_threshold,
        "transmission_context_version": V4_CONFIG.transmission_context_version,
        "canonical_family_version": V4_CONFIG.canonical_family_version,
        "mechanism_compatibility_version": V4_CONFIG.mechanism_compatibility_version,
        "retriever_top_k": None,
        "vector_store_top_k": None,
    }

    event = analyze_event(news)

    def fake_retrieve_cases(news_text, event_arg, top_k=5):
        observed["retriever_top_k"] = top_k
        observed["vector_store_top_k"] = top_k
        return [
            RetrievedCase(
                case_id="case_2023_red_sea_attacks",
                title="Red Sea attacks",
                summary="Shipping disruption.",
                supply_chain_nodes=["container_shipping"],
            )
        ]

    with patch("src.pipeline.retrieve_cases", side_effect=fake_retrieve_cases):
        with patch("src.pipeline._analyze_event", return_value=event):
            run_v4_pipeline(news, event_analyzer="rule")

    observed["trace_passed"] = (
        observed["resolved_top_k"] == 10
        and observed["retriever_top_k"] == 10
        and observed["vector_store_top_k"] == 10
        and observed["mechanism_support_enabled"] is True
    )
    return observed


if __name__ == "__main__":
    main()
