"""Build the V4 production-migration freeze candidate manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.agents.transmission_builder import MIN_CASE_SUPPORT_FOR_SECOND_ORDER
from src.config import TRANSMISSION_CONTEXT_V1_PATH, USE_MECHANISM_COMPATIBLE_SUPPORT
from src.mechanism_context import (
    CANONICAL_FAMILY_VERSION,
    MECHANISM_COMPATIBILITY_VERSION,
    TRANSMISSION_CONTEXT_VERSION,
)


OUTPUT_PATH = Path("data/topk_sensitivity_v4/v4_freeze_candidate_manifest.json")


def main() -> None:
    manifest = build_manifest()
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps(manifest["freeze_candidate"], indent=2, sort_keys=True))


def build_manifest() -> dict[str, Any]:
    validation_summary = _load_json(
        Path("data/topk_sensitivity_v4/mechanism_freeze_candidate_validation_summary.json")
    )
    shadow_summary = _load_json(
        Path("data/topk_sensitivity_v4/production_shadow_comparison_summary.json")
    )
    context_payload = _load_json(TRANSMISSION_CONTEXT_V1_PATH)
    return {
        "diagnostic_only": False,
        "freeze_candidate": {
            "v4_candidate_identifier": "georisk_v4_mechanism_context_candidate_2026_08_11",
            "status": "production_migration_freeze_candidate",
            "top_k": 10,
            "production_default_top_k_changed": False,
            "compatible_support_threshold": MIN_CASE_SUPPORT_FOR_SECOND_ORDER,
            "transmission_context_version": TRANSMISSION_CONTEXT_VERSION,
            "canonical_family_version": CANONICAL_FAMILY_VERSION,
            "mechanism_compatibility_version": MECHANISM_COMPATIBILITY_VERSION,
            "asset_ranker_version": "ranking_v1",
            "unknown_unmapped_policy": (
                "unmapped/unknown transmission order is preserved separately "
                "and is not treated as first_order or second_order."
            ),
            "weak_background_policy": (
                "contextual_background is non-voting; same affected node alone "
                "is not mechanism-compatible support."
            ),
            "feature_flag_name": "USE_MECHANISM_COMPATIBLE_SUPPORT",
            "feature_flag_default": USE_MECHANISM_COMPATIBLE_SUPPORT,
        },
        "development_validation_summary": validation_summary["comparison"],
        "shadow_summary": shadow_summary,
        "historical_context_migration_summary": context_payload["coverage_summary"],
        "known_unresolved_cases": [
            {
                "event_id": "dev_lng_shipping_sanctions",
                "node": "trade_lanes",
                "reason": "genuinely ambiguous context; intentionally not forced during development.",
            }
        ],
        "frozen_behavior_files": {
            "mechanism_context": "src/mechanism_context.py",
            "transmission_builder": "src/agents/transmission_builder.py",
            "current_event_projection": "src/transmission_context_store.py",
            "historical_context_sidecar": str(TRANSMISSION_CONTEXT_V1_PATH),
            "asset_ranker": "src/agents/asset_ranker.py",
            "config": "src/config.py",
        },
        "artifact_hashes": {
            str(path): _sha256(path)
            for path in [
                TRANSMISSION_CONTEXT_V1_PATH,
                Path("data/topk_sensitivity_v4/mechanism_freeze_candidate_validation_summary.json"),
                Path("data/topk_sensitivity_v4/production_shadow_comparison_summary.json"),
            ]
            if path.exists()
        },
        "scope_guardrails": [
            "No CAR, price, return, or held-out validation results were used.",
            "Production default path remains legacy unless the feature flag is enabled.",
            "Development labels are closed; this manifest does not tune rules.",
        ],
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
