"""Audit GeoRisk V4 and legacy retrieval configuration call sites."""

from __future__ import annotations

import csv
import json
from pathlib import Path


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
AUDIT_CSV = OUTPUT_DIR / "v4_config_audit.csv"
TRACE_JSON = OUTPUT_DIR / "v4_config_trace.json"


def main() -> None:
    rows = config_audit_rows()
    _write_csv(AUDIT_CSV, rows)
    print(json.dumps({"audit_rows": len(rows), "output": str(AUDIT_CSV)}, indent=2))


def config_audit_rows() -> list[dict[str, object]]:
    """Return known top-k and V4 config call sites."""

    return [
        _row("src/pipeline.py", "run_pipeline(top_k=3)", 3, "legacy", True, True, "Caller can override top_k; legacy default remains 3."),
        _row("src/pipeline.py", "CLI --top-k default", 3, "legacy", True, True, "CLI default remains legacy 3."),
        _row("src/pipeline.py", "run_v4_pipeline()", 10, "v4", True, False, "Dedicated V4 entry point uses V4_CONFIG.retrieval_top_k."),
        _row("src/api.py", "AnalyzeRequest.top_k", 3, "legacy", False, True, "API endpoint calls legacy run_pipeline with request top_k."),
        _row("app.py", "Streamlit run_pipeline(..., top_k=3)", 3, "legacy", False, True, "UI remains legacy/demo path."),
        _row("src/agents/case_retriever.py", "retrieve_cases(top_k=5)", 5, "shared_internal_default", True, True, "V4 path passes explicit 10, so default is bypassed."),
        _row("src/vector_store.py", "query_cases(top_k=5)", 5, "shared_internal_default", True, True, "V4 path passes explicit 10 through retriever."),
        _row("src/v4_config.py", "V4_CONFIG.retrieval_top_k", 10, "v4", True, False, "Single frozen V4 source of truth."),
        _row("src/v4_config.py", "V4_CONFIG.use_mechanism_compatible_support", True, "v4", True, False, "V4 path explicitly enables mechanism support."),
    ]


def _row(
    file: str,
    function_or_cli: str,
    current_default: object,
    mode: str,
    v4_path_can_reach: bool,
    explicit_override_exists: bool,
    notes: str,
) -> dict[str, object]:
    risk = "none" if mode == "v4" else (
        "low_when_run_v4_pipeline_is_used" if v4_path_can_reach and explicit_override_exists else "legacy_only"
    )
    return {
        "file": file,
        "function_or_cli": function_or_cli,
        "current_default": current_default,
        "legacy_or_v4": mode,
        "v4_path_can_reach": v4_path_can_reach,
        "explicit_override_exists": explicit_override_exists,
        "risk_of_silent_3_or_5_fallback": risk,
        "notes": notes,
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
