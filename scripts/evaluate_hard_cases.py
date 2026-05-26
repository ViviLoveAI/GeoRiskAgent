"""Evaluate hard generalization cases for GeoRisk pipeline behavior.

This script measures exposure discovery and retrieval quality only. It does
not evaluate stock returns, price movement, or investment performance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from src.agents.llm_event_analyst import get_last_analysis_trace
from src.pipeline import run_pipeline
from src.vector_store import build_index


HARD_EVALUATION_CASES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "hard_evaluation_cases.json"
)


def main() -> None:
    """Run the hard generalization evaluation and print concise metrics."""

    parser = argparse.ArgumentParser(
        description="Run hard GeoRisk generalization evaluation."
    )
    parser.add_argument(
        "--event-analyzer",
        choices=["rule", "llm", "both"],
        default="both",
        help="Event analyzer to evaluate. LLM mode safely falls back to rules.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-case prediction details and mismatch reasons.",
    )
    args = parser.parse_args()

    build_index(force_rebuild=True)
    evaluation_cases = json.loads(HARD_EVALUATION_CASES_PATH.read_text(encoding="utf-8"))
    analyzers = ["rule", "llm"] if args.event_analyzer == "both" else [args.event_analyzer]

    for index, analyzer in enumerate(analyzers):
        if index:
            print()
        results = [_evaluate_case(case, analyzer) for case in evaluation_cases]
        _print_summary(results, analyzer, verbose=args.verbose)


def _print_summary(results: list[dict], analyzer: str, verbose: bool = False) -> None:
    """Print aggregate and case-level metrics for one event analyzer."""

    event_type_accuracy = _mean(result["event_type_match"] for result in results)
    node_recall = _mean(result["node_recall"] for result in results)
    positive_results = [result for result in results if result["retrieval_evaluated"]]
    retrieval_recall_at_1 = _mean(
        result["retrieval_recall_at_1"] for result in positive_results
    )
    retrieval_recall_at_3 = _mean(
        result["retrieval_recall_at_3"] for result in positive_results
    )
    mrr = _mean(result["reciprocal_rank"] for result in positive_results)

    negative_results = [result for result in results if result["negative_case"]]
    limited_support_rate = _mean(
        result["limited_support"] for result in negative_results
    )

    print(f"GeoRisk Hard Generalization Evaluation ({analyzer} Event Analyst)")
    print("Scope: exposure discovery and retrieval quality only; no price or return metrics.")
    print(f"cases: {len(results)}")
    print(f"event_type_accuracy: {event_type_accuracy:.2f}")
    print(f"node_recall: {node_recall:.2f}")
    print(f"retrieval_recall_at_1: {retrieval_recall_at_1:.2f}")
    print(f"retrieval_recall_at_3: {retrieval_recall_at_3:.2f}")
    print(f"mrr: {mrr:.2f}")
    print("retrieval metrics use positive cases with expected historical analogs.")
    if negative_results:
        print(f"negative_limited_support_rate: {limited_support_rate:.2f}")
    print()
    print("Case Results")
    for result in results:
        support_note = ""
        if result["negative_case"]:
            support_note = (
                f", limited_support={result['limited_support']}, "
                f"historical_supported={result['historical_supported_count']}, "
                f"max_confidence={result['max_confidence']:.2f}"
            )
        retrieval_note = "retrieval=n/a"
        if result["retrieval_evaluated"]:
            retrieval_note = (
                f"retrieval@1={result['retrieval_recall_at_1']:.2f}, "
                f"retrieval@3={result['retrieval_recall_at_3']:.2f}, "
                f"rr={result['reciprocal_rank']:.2f}"
            )
        print(
            f"- {result['case_id']}: "
            f"event_type={result['event_type_match']}, "
            f"node_recall={result['node_recall']:.2f}, "
            f"{retrieval_note}"
            f"{support_note}"
        )

    if verbose:
        print()
        print("Verbose Error Analysis")
        for result in results:
            _print_verbose_case(result)


def _evaluate_case(case: dict, event_analyzer: str) -> dict:
    """Evaluate one hard exposure discovery case."""

    report = run_pipeline(case["news"], top_k=3, event_analyzer=event_analyzer)
    predicted_nodes = set(report.event.supply_chain_nodes)
    expected_nodes = set(case["expected_nodes"])
    retrieved_case_ids = [retrieved.case_id for retrieved in report.retrieved_cases[:3]]
    expected_historical_cases = set(case["expected_historical_cases"])
    negative_case = bool(case.get("negative_case", False))

    historical_supported_count = sum(
        result.evidence_level == "historical_supported"
        for result in report.evidence_results
    )
    max_confidence = max(
        (result.confidence for result in report.evidence_results),
        default=0.0,
    )

    retrieval_evaluated = bool(expected_historical_cases)
    node_recall = _recall(predicted_nodes, expected_nodes)
    event_type_match = report.event.event_type == case["expected_event_type"]
    fallback_occurred = False
    fallback_reason = None
    supporting_phrases: object = report.event.risk_factors

    if event_analyzer == "llm":
        trace = get_last_analysis_trace()
        fallback_occurred = bool(trace.get("fallback_occurred", False))
        fallback_reason = trace.get("fallback_reason")
        supporting_phrases = trace.get("supporting_phrases", {})

    return {
        "case_id": case["case_id"],
        "news": case["news"],
        "negative_case": negative_case,
        "expected_event_type": case["expected_event_type"],
        "predicted_event_type": report.event.event_type,
        "event_type_match": event_type_match,
        "expected_nodes": sorted(expected_nodes),
        "predicted_nodes": sorted(predicted_nodes),
        "node_recall": node_recall,
        "retrieval_evaluated": retrieval_evaluated,
        "retrieval_recall_at_1": _recall(
            set(retrieved_case_ids[:1]), expected_historical_cases
        ) if retrieval_evaluated else None,
        "retrieval_recall_at_3": _recall(
            set(retrieved_case_ids[:3]), expected_historical_cases
        ) if retrieval_evaluated else None,
        "reciprocal_rank": (
            _reciprocal_rank(retrieved_case_ids, expected_historical_cases)
            if retrieval_evaluated
            else None
        ),
        "historical_supported_count": historical_supported_count,
        "max_confidence": max_confidence,
        "supporting_phrases": supporting_phrases,
        "fallback_occurred": fallback_occurred,
        "fallback_reason": fallback_reason,
        "mismatch_reason": _mismatch_reason(
            event_type_match,
            node_recall,
            report.event.event_type,
            case["expected_event_type"],
            predicted_nodes,
            expected_nodes,
        ),
        "limited_support": (
            historical_supported_count == 0 and max_confidence <= 0.49
            if negative_case
            else True
        ),
    }


def _print_verbose_case(result: dict) -> None:
    """Print detailed per-case diagnostics for hard evaluation."""

    print(f"- case_id: {result['case_id']}")
    print(f"  input: {result['news']}")
    print(f"  expected_event_type: {result['expected_event_type']}")
    print(f"  predicted_event_type: {result['predicted_event_type']}")
    print(f"  expected_supply_chain_nodes: {', '.join(result['expected_nodes'])}")
    print(f"  predicted_supply_chain_nodes: {', '.join(result['predicted_nodes'])}")
    print(f"  supporting_phrases: {_format_supporting_phrases(result['supporting_phrases'])}")
    print(f"  fallback_occurred: {result['fallback_occurred']}")
    if result["fallback_reason"]:
        print(f"  fallback_reason: {result['fallback_reason']}")
    print(f"  mismatch_reason: {result['mismatch_reason']}")


def _mismatch_reason(
    event_type_match: bool,
    node_recall: float,
    predicted_event_type: str,
    expected_event_type: str,
    predicted_nodes: set[str],
    expected_nodes: set[str],
) -> str:
    """Explain event-type and node-recall misses without affecting scoring."""

    reasons: list[str] = []
    if not event_type_match:
        reasons.append(
            f"event_type mismatch: expected {expected_event_type}, got {predicted_event_type}"
        )
    if node_recall < 1.0:
        missing_nodes = sorted(expected_nodes - predicted_nodes)
        extra_nodes = sorted(predicted_nodes - expected_nodes)
        reasons.append(
            "node recall miss: "
            f"missing {missing_nodes or 'none'}; extra {extra_nodes or 'none'}"
        )
    if not reasons:
        return "matched event_type and expected nodes"
    return "; ".join(reasons)


def _format_supporting_phrases(value: object) -> str:
    """Format rule keywords or LLM supporting phrases for console output."""

    if isinstance(value, dict):
        parts = []
        for key, phrases in value.items():
            if isinstance(phrases, list):
                rendered = ", ".join(str(phrase) for phrase in phrases) or "none"
            else:
                rendered = str(phrases)
            parts.append(f"{key}: [{rendered}]")
        return "; ".join(parts) if parts else "none"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    return str(value) if value else "none"


def _recall(predicted: set[str], expected: set[str]) -> float:
    """Calculate recall for one expected set."""

    if not expected:
        return 1.0
    return len(predicted & expected) / len(expected)


def _reciprocal_rank(retrieved_case_ids: list[str], expected: set[str]) -> float:
    """Calculate reciprocal rank for the first relevant retrieved case."""

    if not expected:
        return 1.0
    for index, case_id in enumerate(retrieved_case_ids, start=1):
        if case_id in expected:
            return 1.0 / index
    return 0.0


def _mean(values: Iterable[float | bool | None]) -> float:
    """Calculate the arithmetic mean of numeric or boolean values."""

    values = [value for value in values if value is not None]
    if not values:
        return 0.0
    return sum(float(value) for value in values) / len(values)


if __name__ == "__main__":
    main()
