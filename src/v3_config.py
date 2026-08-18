"""Frozen GeoRisk V3 baseline configuration.

The V3 baseline is reconstructed from the pre-V4 validation path that built
``data/validation_v3`` snapshots through ``run_pipeline(..., event_analyzer="rule")``
without passing ``top_k``. That call resolved to the legacy pipeline default
``top_k=3`` and used raw same-node support, not TransmissionContext.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agents.asset_ranker import RANKING_VERSION
from src.agents.transmission_builder import MIN_CASE_SUPPORT_FOR_SECOND_ORDER
from src.vector_store import MODEL_NAME


@dataclass(frozen=True)
class FrozenV3Config:
    """Immutable configuration for the frozen GeoRisk V3 baseline."""

    baseline_name: str = "GeoRisk V3 Baseline"
    baseline_version: str = "georisk_v3_frozen_v1"
    event_analyzer: str = "rule"
    retrieval_embedding_model: str = MODEL_NAME
    retrieval_unit: str = "historical_case_retrieval_text"
    retrieval_top_k: int = 3
    support_basis: str = "raw_same_node_recurrence"
    support_threshold: int = MIN_CASE_SUPPORT_FOR_SECOND_ORDER
    transmission_context_enabled: bool = False
    mechanism_compatibility_enabled: bool = False
    canonical_family_enabled: bool = False
    asset_ranker_version: str = RANKING_VERSION
    historical_kb_path: str = "data/historical_cases.json"


V3_CONFIG = FrozenV3Config()


def assert_v3_config(config: FrozenV3Config = V3_CONFIG) -> None:
    """Fail fast if a frozen V3 invariant drifts."""

    expected = FrozenV3Config()
    if config != expected:
        raise ValueError(f"V3 config drift detected: {config!r} != {expected!r}")
    if MIN_CASE_SUPPORT_FOR_SECOND_ORDER != 2:
        raise ValueError("V3 raw support threshold must remain 2.")
