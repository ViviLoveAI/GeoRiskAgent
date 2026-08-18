"""Magnitude-based exposure hit-rate evaluation for CAR results.

A hit means the flagged asset showed a statistically abnormal move around the
event in either direction (|standardized CAR| >= threshold), because GeoRisk
predicts exposure, not price direction. Hit status is computed upstream by the
CAR calculator; this module only aggregates it and never re-derives direction.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


GEORISK_SOURCE = "georisk"
BASELINE_SOURCE = "baseline"


def magnitude_hit(result: dict[str, Any]) -> bool | None:
    """Return magnitude hit status for one CAR result.

    The calculator sets ``hit = |standardized_car| >= threshold``. When the
    standardized CAR could not be computed (for example, zero estimation-window
    abnormal-return variance), the pair is skipped from hit-rate evaluation
    rather than counted as a miss.
    """

    if result.get("standardized_car") is None:
        return None
    return bool(result.get("hit"))


def evaluate_exposure_results(pair_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute magnitude-based hit-rate summary for CAR pair results."""

    evaluated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for result in pair_results:
        skip_reason = _skip_reason(result)
        if skip_reason:
            skipped.append({**result, "skip_reason": skip_reason})
            continue

        hit = magnitude_hit(result)
        if hit is None:
            skip_reason = _standardized_car_skip_reason(result)
            skipped.append(
                {
                    **result,
                    "missing_data_reason": skip_reason,
                    "skip_reason": skip_reason,
                }
            )
            continue

        evaluated.append({**result, "hit": hit})

    georisk = [row for row in evaluated if _source(row) == GEORISK_SOURCE]
    baseline = [row for row in evaluated if _source(row) == BASELINE_SOURCE]

    return {
        "overall_hit_rate": _hit_rate(evaluated),
        "georisk_flagged_hit_rate": _hit_rate(georisk),
        "baseline_hit_rate": _hit_rate(baseline) if _has_baseline(pair_results) else None,
        "hit_rate_by_evidence_label": _hit_rate_by_field(georisk, "evidence_label"),
        "hit_rate_by_event_type": _hit_rate_by_field(evaluated, "event_type"),
        "evaluated_pairs": len(evaluated),
        "skipped_pairs": len(skipped),
        "skipped_reasons": dict(Counter(row["skip_reason"] for row in skipped)),
    }


def split_evaluated_and_skipped(
    pair_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return pair rows annotated with magnitude-based hit or skip reason."""

    evaluated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for result in pair_results:
        skip_reason = _skip_reason(result)
        if skip_reason:
            skipped.append({**result, "skip_reason": skip_reason})
            continue
        hit = magnitude_hit(result)
        if hit is None:
            skip_reason = _standardized_car_skip_reason(result)
            skipped.append(
                {
                    **result,
                    "missing_data_reason": skip_reason,
                    "skip_reason": skip_reason,
                }
            )
        else:
            evaluated.append({**result, "hit": hit})
    return evaluated, skipped


def _skip_reason(result: dict[str, Any]) -> str | None:
    """Return skip reason from CAR result fields, if any."""

    reason = result.get("missing_data_reason")
    if reason:
        return str(reason)
    if result.get("car") is None:
        return "missing_car"
    return None


def _standardized_car_skip_reason(result: dict[str, Any]) -> str:
    """Return the explicit skip reason for unavailable standardized CAR."""

    if result.get("asset_equals_benchmark") or result.get("symbol") == result.get("benchmark"):
        return "asset_equals_benchmark"
    return "standardized_car_unavailable"


def _source(result: dict[str, Any]) -> str:
    """Normalize source/group field for GeoRisk versus baseline summaries."""

    source = result.get("source") or result.get("group") or GEORISK_SOURCE
    return str(source)


def _has_baseline(pair_results: list[dict[str, Any]]) -> bool:
    """Return whether any pair is marked as baseline."""

    return any(_source(result) == BASELINE_SOURCE for result in pair_results)


def _hit_rate(rows: list[dict[str, Any]]) -> float | None:
    """Return magnitude-based hit rate for evaluated rows."""

    if not rows:
        return None
    return sum(1 for row in rows if row["hit"]) / len(rows)


def _hit_rate_by_field(rows: list[dict[str, Any]], field_name: str) -> dict[str, float]:
    """Compute hit rate grouped by a metadata field."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = row.get(field_name)
        if value is None or value == "":
            continue
        grouped.setdefault(str(value), []).append(row)
    return {
        value: rate
        for value, group_rows in grouped.items()
        if (rate := _hit_rate(group_rows)) is not None
    }
