"""Human-readable reporting for full CAR validation runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd


def build_validation_report(
    result_dir: str | Path,
    config: dict[str, Any],
    price_preparation: dict[str, Any],
    output_path: str | Path | None = None,
) -> Path:
    """Build a Markdown report from CAR validation artifacts."""

    result_path = Path(result_dir)
    output = Path(output_path) if output_path else result_path / "car_validation_report.md"
    summary = _read_json(result_path / "car_summary.json", {})
    pair_rows = _read_csv(result_path / "car_pair_results.csv")
    skipped_rows = _read_json(result_path / "skipped_pairs.json", [])
    evaluated_rows = [row for row in pair_rows if not row.get("missing_data_reason")]

    georisk_rows = [row for row in evaluated_rows if _source(row) == "georisk"]
    baseline_rows = [row for row in evaluated_rows if _source(row) == "baseline"]
    georisk_rate = _hit_rate(georisk_rows)
    baseline_rate = _hit_rate(baseline_rows)
    difference = (
        georisk_rate - baseline_rate
        if georisk_rate is not None and baseline_rate is not None
        else None
    )

    lines = [
        "# CAR Validation Report",
        "",
        "This is ex-post exposure validation, not price prediction or investment advice.",
        "Hit detection is magnitude-based: `abs(standardized_car) >= significance_threshold`.",
        "",
        "## Configuration",
        "",
        f"- Run timestamp: `{config.get('run_timestamp')}`",
        f"- Benchmark: `{config.get('benchmark_symbol')}`",
        f"- Estimation window: `{config.get('estimation_window')}`",
        f"- Event window: `{config.get('event_window')}`",
        f"- Significance threshold: `{config.get('significance_threshold')}`",
        f"- Event IDs: `{', '.join(config.get('event_ids', []))}`",
        "",
        "## Summary",
        "",
        f"- Held-out events: {summary.get('events_evaluated', 0)}",
        f"- Evaluated asset-event pairs: {summary.get('evaluated_pairs', 0)}",
        f"- Skipped pairs: {summary.get('skipped_pairs', 0)}",
        f"- GeoRisk flagged hit rate: {_format_rate(georisk_rate)} (n={len(georisk_rows)})",
        f"- Baseline hit rate: {_format_rate(baseline_rate)} (n={len(baseline_rows)})",
        f"- Difference: {_format_rate(difference)}",
        "",
    ]

    if len(evaluated_rows) < 30:
        lines.extend(
            [
                "> Sample size is small. Treat hit-rate differences as descriptive diagnostics, not a statistically strong performance claim.",
                "",
            ]
        )

    lines.extend(
        [
            "## Hit Rate By Evidence Label",
            "",
            _rate_table(evaluated_rows, "evidence_label"),
            "",
            "## Hit Rate By Event Type",
            "",
            _rate_table(evaluated_rows, "event_type"),
            "",
            "## Standardized CAR Distribution",
            "",
            _standardized_car_stats(evaluated_rows),
            "",
            "## Price Preparation",
            "",
            f"- Reused symbols: {len(price_preparation.get('reused_symbols', []))}",
            f"- Downloaded symbols: {len(price_preparation.get('downloaded_symbols', []))}",
            f"- Failed symbols: {len(price_preparation.get('failed_symbols', []))}",
            f"- Invalid event dates: {', '.join(price_preparation.get('invalid_event_dates', [])) or 'none'}",
            "",
            "## Skipped Pairs",
            "",
            _skipped_table(skipped_rows),
            "",
        ]
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def terminal_summary(result_dir: str | Path) -> str:
    """Return a concise terminal summary for a completed CAR run."""

    result_path = Path(result_dir)
    summary = _read_json(result_path / "car_summary.json", {})
    pair_rows = _read_csv(result_path / "car_pair_results.csv")
    evaluated_rows = [row for row in pair_rows if not row.get("missing_data_reason")]
    georisk_rows = [row for row in evaluated_rows if _source(row) == "georisk"]
    baseline_rows = [row for row in evaluated_rows if _source(row) == "baseline"]
    georisk_rate = _hit_rate(georisk_rows)
    baseline_rate = _hit_rate(baseline_rows)
    difference = (
        georisk_rate - baseline_rate
        if georisk_rate is not None and baseline_rate is not None
        else None
    )

    lines = [
        "CAR Validation Complete",
        "",
        f"Events: {summary.get('events_evaluated', 0)}",
        f"GeoRisk pairs evaluated: {len(georisk_rows)}",
        f"Baseline pairs evaluated: {len(baseline_rows)}",
        f"Skipped pairs: {summary.get('skipped_pairs', 0)}",
        "",
        f"GeoRisk hit rate: {_format_rate(georisk_rate)}",
        f"Baseline hit rate: {_format_rate(baseline_rate)}",
        f"Difference: {_format_rate(difference)}",
        "",
    ]
    for label in ["historical_supported", "sector_proxy", "inference_only"]:
        rows = [row for row in georisk_rows if row.get("evidence_label") == label]
        lines.append(f"{label}: {_format_rate(_hit_rate(rows))} (n={len(rows)})")
    lines.extend(["", f"Results written to {result_path}/"])
    return "\n".join(lines)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _source(row: dict[str, Any]) -> str:
    return str(row.get("source") or "georisk")


def _hit_rate(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if _as_bool(row.get("hit"))) / len(rows)


def _rate_table(rows: list[dict[str, Any]], field_name: str) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = row.get(field_name)
        if value:
            groups.setdefault(str(value), []).append(row)
    if not groups:
        return "No evaluated rows with this field."
    lines = ["| Group | Hit Rate | n |", "| --- | ---: | ---: |"]
    for value in sorted(groups):
        group_rows = groups[value]
        lines.append(f"| {value} | {_format_rate(_hit_rate(group_rows))} | {len(group_rows)} |")
    return "\n".join(lines)


def _standardized_car_stats(rows: list[dict[str, Any]]) -> str:
    values = [
        float(row["standardized_car"])
        for row in rows
        if _is_number(row.get("standardized_car"))
    ]
    if not values:
        return "No standardized CAR values were available."
    series = pd.Series(values)
    lines = [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| n | {len(values)} |",
        f"| mean | {mean(values):.4f} |",
        f"| median | {median(values):.4f} |",
        f"| std | {series.std(ddof=1):.4f} |",
        f"| min | {min(values):.4f} |",
        f"| max | {max(values):.4f} |",
    ]
    return "\n".join(lines)


def _skipped_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No skipped pairs."
    lines = ["| Event ID | Symbol | Reason |", "| --- | --- | --- |"]
    for row in rows:
        reason = row.get("skip_reason") or row.get("missing_data_reason") or ""
        lines.append(f"| {row.get('event_id', '')} | {row.get('symbol', '')} | {reason} |")
    return "\n".join(lines)


def _format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _is_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return not pd.isna(number)
