"""Build final GeoRisk V4 freeze manifest and checksums."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.mechanism_context import (
    CANONICAL_CONTEXT_FAMILIES,
    COMPATIBLE_SUPPORT_THRESHOLD,
)
from src.vector_store import MODEL_NAME
from src.v4_config import V4_CONFIG


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
MANIFEST = OUTPUT_DIR / "v4_final_freeze_manifest.json"
CHECKSUMS = OUTPUT_DIR / "v4_freeze_checksums.json"


def main() -> None:
    manifest = build_manifest()
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    checksums = build_checksums([Path(path) for path in manifest["frozen_files"].values()])
    checksums[str(MANIFEST)] = _sha256(MANIFEST)
    CHECKSUMS.write_text(json.dumps(checksums, indent=2, sort_keys=True))
    print(json.dumps({"manifest": str(MANIFEST), "checksums": str(CHECKSUMS)}, indent=2))


def build_manifest() -> dict[str, Any]:
    migration = _load_json(OUTPUT_DIR / "full_kb_context_migration_audit_summary.json")
    validation = _load_json(OUTPUT_DIR / "mechanism_freeze_candidate_validation_summary.json")
    shadow = _load_json(OUTPUT_DIR / "production_shadow_comparison_summary.json")
    trace = _load_json(OUTPUT_DIR / "v4_config_trace.json")
    config_audit = _read_text(OUTPUT_DIR / "v4_config_audit.csv")
    return {
        "version": V4_CONFIG.version,
        "freeze_status": "V4 DEVELOPMENT FROZEN",
        "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "retrieval": {
            "top_k": V4_CONFIG.retrieval_top_k,
            "embedding_model": MODEL_NAME,
            "vector_store": "ChromaDB PersistentClient",
            "retrieval_text_unchanged": True,
            "embeddings_unchanged": True,
        },
        "mechanism_representation": {
            "transmission_context_version": V4_CONFIG.transmission_context_version,
            "canonical_family_version": V4_CONFIG.canonical_family_version,
            "mechanism_compatibility_version": V4_CONFIG.mechanism_compatibility_version,
            "canonical_families": CANONICAL_CONTEXT_FAMILIES,
        },
        "support_policy": {
            "support_threshold": COMPATIBLE_SUPPORT_THRESHOLD,
            "exact_mechanism_support": "same canonical_context",
            "canonical_family_support": "same canonical_family(canonical_context)",
            "weak_background_exclusion": "contextual_background is non-voting",
            "insufficient_context_behavior": "does not vote; remains unresolved",
        },
        "ranking": {
            "asset_ranker_version": V4_CONFIG.asset_ranker_version,
            "asset_ranker_frozen": True,
        },
        "historical_representation": {
            "total_historical_nodes": migration["historical_case_nodes_total"],
            "informative_contexts": migration["migrated_case_nodes"],
            "coverage": migration["historical_case_node_coverage"],
            "sidecar_path": V4_CONFIG.historical_context_sidecar,
            "known_unresolved_categories": [
                "manufacturing_inputs: frozen-vocabulary representation gap",
                "selected energy nodes: genuinely ambiguous",
                "dev_lng_shipping_sanctions / trade_lanes: known ambiguous development case",
            ],
        },
        "development_evidence": {
            "design_set": validation["comparison"]["design_set"],
            "expanded_validation_set": validation["comparison"]["expanded_validation_set"],
            "shadow_comparison": shadow,
        },
        "config_trace": trace,
        "config_audit_csv_embedded": config_audit,
        "frozen_files": {
            "v4_config": "src/v4_config.py",
            "mechanism_context": "src/mechanism_context.py",
            "transmission_context_store": "src/transmission_context_store.py",
            "transmission_builder": "src/agents/transmission_builder.py",
            "asset_ranker": "src/agents/asset_ranker.py",
            "historical_context_sidecar": V4_CONFIG.historical_context_sidecar,
        },
        "freeze_marker": (
            "V4 DEVELOPMENT FROZEN: future held-out findings must be recorded "
            "as post-freeze V5 candidate issues, not used to tune V4."
        ),
    }


def build_checksums(paths: list[Path]) -> dict[str, str]:
    return {str(path): _sha256(path) for path in paths if path.exists()}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _read_text(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
