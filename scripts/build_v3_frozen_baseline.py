"""Build the frozen V3 baseline manifest and checksum artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.v3_config import V3_CONFIG, assert_v3_config


OUTPUT_DIR = Path("data/validation_general")
MANIFEST_PATH = OUTPUT_DIR / "v3_frozen_baseline_manifest.json"
CHECKSUMS_PATH = OUTPUT_DIR / "v3_frozen_baseline_checksums.json"
TRACE_PATH = OUTPUT_DIR / "v3_config_trace.json"
V3_SNAPSHOT_BUILDER = Path("scripts/build_validation_set_v3.py")
V3_MANIFEST = Path("data/validation_v3/v3_manifest.json")


def build_v3_frozen_baseline() -> dict[str, Any]:
    """Write V3 baseline freeze artifacts."""

    assert_v3_config(V3_CONFIG)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trace = {
        "baseline_version": V3_CONFIG.baseline_version,
        "legacy_call_site": "scripts/build_validation_set_v3.py:create_v3_snapshot",
        "historical_call": 'run_pipeline(event["event_description"], event_analyzer="rule")',
        "run_pipeline_default_top_k": 3,
        "retriever_default_top_k": 5,
        "vector_store_default_top_k": 5,
        "resolved_v3_top_k": V3_CONFIG.retrieval_top_k,
        "resolution_reasoning": (
            "The frozen V3 snapshot builder called run_pipeline with event_analyzer='rule' "
            "and no top_k override, so Python resolved the top_k argument at "
            "src/pipeline.py:run_pipeline default top_k=3. Retriever/vector-store "
            "defaults of 5 were bypassed because run_pipeline passed top_k explicitly."
        ),
        "event_analyzer": V3_CONFIG.event_analyzer,
        "mechanism_compatibility_enabled": V3_CONFIG.mechanism_compatibility_enabled,
    }
    write_json(TRACE_PATH, trace)
    manifest = {
        "baseline_name": V3_CONFIG.baseline_name,
        "baseline_version": V3_CONFIG.baseline_version,
        "freeze_status": "V3 BASELINE FROZEN",
        "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "historical_reconstruction_evidence": {
            "v3_snapshot_builder": str(V3_SNAPSHOT_BUILDER),
            "v3_manifest": str(V3_MANIFEST),
            "v3_manifest_git_commit": _load_json(V3_MANIFEST).get("git_commit", ""),
            "config_trace": str(TRACE_PATH),
        },
        "resolved_config": {
            "event_analyzer": V3_CONFIG.event_analyzer,
            "retrieval_embedding_model": V3_CONFIG.retrieval_embedding_model,
            "retrieval_unit": V3_CONFIG.retrieval_unit,
            "retrieval_top_k": V3_CONFIG.retrieval_top_k,
            "historical_KB_path": V3_CONFIG.historical_kb_path,
            "second_order_candidate_logic": "event nodes plus raw same-node recurrence from retrieved historical cases",
            "support_rule": "same node appears in >=2 independent retrieved cases",
            "support_threshold": V3_CONFIG.support_threshold,
            "TransmissionContext_enabled": V3_CONFIG.transmission_context_enabled,
            "mechanism_compatibility_enabled": V3_CONFIG.mechanism_compatibility_enabled,
            "canonical_family_enabled": V3_CONFIG.canonical_family_enabled,
            "asset_ranker_version": V3_CONFIG.asset_ranker_version,
        },
        "shared_components": {
            "market_mapper_version": "current_asset_mapping_loader",
            "evidence_agent_version": "current_evidence_agent_semantics",
            "asset_ranker_version": V3_CONFIG.asset_ranker_version,
            "shared_component_semantics_unchanged": True,
        },
        "known_limitations": [
            "V3 uses case-level retrieval over full historical cases rather than node-level mechanism fragments.",
            "V3 accepts second-order support from raw same-node recurrence and has no broad-node mechanism guardrail.",
            "V3 top_k is the legacy snapshot-builder resolved value 3; this is not a benchmark-optimized choice.",
        ],
        "prediction_status": {
            "multiyear_predictions_run": False,
            "prices_accessed": False,
            "CAR_run": False,
        },
    }
    write_json(MANIFEST_PATH, manifest)
    checksums = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_version": V3_CONFIG.baseline_version,
        "artifacts": {
            str(Path("src/v3_config.py")): sha256_file("src/v3_config.py"),
            str(Path("src/pipeline.py")): sha256_file("src/pipeline.py"),
            str(Path("src/agents/transmission_builder.py")): sha256_file("src/agents/transmission_builder.py"),
            str(Path("src/vector_store.py")): sha256_file("src/vector_store.py"),
            str(Path("data/historical_cases.json")): sha256_file("data/historical_cases.json"),
            str(V3_SNAPSHOT_BUILDER): sha256_file(V3_SNAPSHOT_BUILDER),
            str(V3_MANIFEST): sha256_file(V3_MANIFEST),
            str(TRACE_PATH): sha256_file(TRACE_PATH),
            str(MANIFEST_PATH): sha256_file(MANIFEST_PATH),
        },
    }
    write_json(CHECKSUMS_PATH, checksums)
    return {
        "manifest": str(MANIFEST_PATH),
        "checksums": str(CHECKSUMS_PATH),
        "trace": str(TRACE_PATH),
        "baseline_version": V3_CONFIG.baseline_version,
    }


def sha256_file(path: str | Path) -> str:
    """Return a file SHA-256 digest."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write stable JSON."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    print(json.dumps(build_v3_frozen_baseline(), indent=2, sort_keys=True))
