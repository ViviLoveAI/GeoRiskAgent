"""End-to-end orchestration for GeoRisk Transmission Analyzer.

The pipeline generates a geopolitical risk watchlist report. It does not
predict stock prices and does not provide investment advice.
"""

import argparse

from src.agents.case_retriever import retrieve_cases
from src.agents.asset_ranker import rank_assets
from src.agents.event_analyst import analyze_event
from src.agents.evidence_agent import grade_evidence
from src.agents.llm_event_analyst import analyze_event_with_llm
from src.agents.market_mapper import map_assets
from src.agents.report_agent import generate_report
from src.agents.transmission_builder import build_transmission_chain
from src.config import USE_LLM_EVENT_ANALYST
from src.report_formatter import format_concise_report
from src.schemas import EventAnalysis
from src.schemas import FinalReport
from src.v3_config import V3_CONFIG, assert_v3_config
from src.v4_config import V4_CONFIG, assert_v4_config


def run_pipeline(
    news_text: str,
    top_k: int = 3,
    event_analyzer: str | None = None,
) -> FinalReport:
    """Run the full GeoRisk Transmission Analyzer workflow."""

    if not news_text.strip():
        raise ValueError("news_text must contain a geopolitical risk news item.")

    event = _analyze_event(news_text, event_analyzer)
    retrieved_cases = retrieve_cases(news_text, event, top_k=top_k)
    transmission_chain = build_transmission_chain(event, retrieved_cases)
    candidate_assets = map_assets(event, transmission_chain)
    evidence_results = grade_evidence(
        event,
        candidate_assets,
        retrieved_cases,
        transmission_chain,
    )
    evidence_results = rank_assets(
        evidence_results,
        event,
        retrieved_cases,
        transmission_chain,
    )
    final_report = generate_report(
        event,
        retrieved_cases,
        transmission_chain,
        evidence_results,
    )

    return final_report


def run_v4_pipeline(
    news_text: str,
    event_analyzer: str | None = None,
) -> FinalReport:
    """Run the frozen GeoRisk V4 configuration explicitly.

    This path does not rely on legacy defaults or environment feature flags.
    """

    assert_v4_config(V4_CONFIG)
    if not news_text.strip():
        raise ValueError("news_text must contain a geopolitical risk news item.")

    event = _analyze_event(news_text, event_analyzer)
    retrieved_cases = retrieve_cases(news_text, event, top_k=V4_CONFIG.retrieval_top_k)
    transmission_chain = build_transmission_chain(
        event,
        retrieved_cases,
        use_mechanism_compatible_support=V4_CONFIG.use_mechanism_compatible_support,
    )
    candidate_assets = map_assets(event, transmission_chain)
    evidence_results = grade_evidence(
        event,
        candidate_assets,
        retrieved_cases,
        transmission_chain,
    )
    evidence_results = rank_assets(
        evidence_results,
        event,
        retrieved_cases,
        transmission_chain,
    )
    final_report = generate_report(
        event,
        retrieved_cases,
        transmission_chain,
        evidence_results,
    )

    return final_report


def run_v3_pipeline(news_text: str) -> FinalReport:
    """Run the frozen GeoRisk V3 baseline explicitly.

    V3 reproduces the pre-V4 snapshot builder path: rule-based event analysis,
    top_k=3 case retrieval, raw same-node second-order support, and no
    TransmissionContext or mechanism-compatible support.
    """

    assert_v3_config(V3_CONFIG)
    if not news_text.strip():
        raise ValueError("news_text must contain a geopolitical risk news item.")

    event = _analyze_event(news_text, V3_CONFIG.event_analyzer)
    retrieved_cases = retrieve_cases(news_text, event, top_k=V3_CONFIG.retrieval_top_k)
    transmission_chain = build_transmission_chain(
        event,
        retrieved_cases,
        use_mechanism_compatible_support=V3_CONFIG.mechanism_compatibility_enabled,
    )
    candidate_assets = map_assets(event, transmission_chain)
    evidence_results = grade_evidence(
        event,
        candidate_assets,
        retrieved_cases,
        transmission_chain,
    )
    evidence_results = rank_assets(
        evidence_results,
        event,
        retrieved_cases,
        transmission_chain,
    )
    final_report = generate_report(
        event,
        retrieved_cases,
        transmission_chain,
        evidence_results,
    )

    return final_report


def _analyze_event(news_text: str, event_analyzer: str | None) -> EventAnalysis:
    """Select the configured event analyst without changing downstream logic."""

    selected_analyzer = event_analyzer
    if selected_analyzer is None:
        selected_analyzer = "llm" if USE_LLM_EVENT_ANALYST else "rule"

    if selected_analyzer == "rule":
        return analyze_event(news_text)
    if selected_analyzer == "llm":
        return analyze_event_with_llm(news_text)

    raise ValueError("event_analyzer must be either 'rule' or 'llm'.")


def main() -> None:
    """CLI entry point for running the pipeline."""

    parser = argparse.ArgumentParser(description="Run the GeoRisk pipeline.")
    parser.add_argument("--news", required=True, help="News text to analyze.")
    parser.add_argument("--top-k", type=int, default=3, help="Number of cases to retrieve.")
    parser.add_argument(
        "--format",
        choices=["json", "concise"],
        default="concise",
        help="Output format.",
    )
    parser.add_argument(
        "--event-analyzer",
        choices=["rule", "llm"],
        default="rule",
        help="Event analyzer to use. LLM mode safely falls back to rule-based analysis.",
    )
    args = parser.parse_args()

    report = run_pipeline(
        args.news,
        top_k=args.top_k,
        event_analyzer=args.event_analyzer,
    )
    if args.format == "json":
        print(report.model_dump_json(indent=2))
    else:
        print(format_concise_report(report))


if __name__ == "__main__":
    main()
