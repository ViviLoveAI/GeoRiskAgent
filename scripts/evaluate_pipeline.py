"""Evaluate exposure discovery and historical-case retrieval quality."""

from __future__ import annotations

import json
from pathlib import Path

from src.pipeline import run_pipeline
from src.vector_store import build_index


EVALUATION_CASES_PATH = Path(__file__).resolve().parents[1] / "data" / "evaluation_cases.json"


def main() -> None:
    """Run the evaluation set and print a concise summary."""

    build_index(force_rebuild=True)
    evaluation_cases = json.loads(EVALUATION_CASES_PATH.read_text(encoding="utf-8"))
    results = [_evaluate_case(case) for case in evaluation_cases]

    event_type_accuracy = _mean(result["event_type_match"] for result in results)
    node_recall = _mean(result["node_recall"] for result in results)
    retrieval_recall_at_3 = _mean(result["retrieval_recall_at_3"] for result in results)

    print("GeoRisk MVP Regression Evaluation")
    print("Scope: exposure discovery and retrieval quality only; no price or return metrics.")
    print(f"cases: {len(results)}")
    print(f"event_type_accuracy: {event_type_accuracy:.2f}")
    print(f"node_recall: {node_recall:.2f}")
    print(f"retrieval_recall_at_3: {retrieval_recall_at_3:.2f}")
    print()
    print("Case Results")
    for result in results:
        print(
            f"- {result['case_id']}: "
            f"event_type={result['event_type_match']}, "
            f"node_recall={result['node_recall']:.2f}, "
            f"retrieval_recall_at_3={result['retrieval_recall_at_3']:.2f}"
        )


def _evaluate_case(case: dict) -> dict:
    """Evaluate one exposure discovery test case."""

    report = run_pipeline(case["news"], top_k=3)
    predicted_nodes = set(report.event.supply_chain_nodes)
    expected_nodes = set(case["expected_nodes"])
    retrieved_case_ids = {retrieved.case_id for retrieved in report.retrieved_cases[:3]}
    expected_historical_cases = set(case["expected_historical_cases"])

    return {
        "case_id": case["case_id"],
        "event_type_match": report.event.event_type == case["expected_event_type"],
        "node_recall": _recall(predicted_nodes, expected_nodes),
        "retrieval_recall_at_3": _recall(retrieved_case_ids, expected_historical_cases),
    }


def _recall(predicted: set[str], expected: set[str]) -> float:
    """Calculate recall for one expected set."""

    if not expected:
        return 1.0
    return len(predicted & expected) / len(expected)


def _mean(values) -> float:
    """Calculate the arithmetic mean of numeric or boolean values."""

    values = list(values)
    if not values:
        return 0.0
    return sum(float(value) for value in values) / len(values)


if __name__ == "__main__":
    main()
