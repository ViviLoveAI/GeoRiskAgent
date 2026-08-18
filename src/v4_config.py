"""Frozen GeoRisk V4 configuration.

V4 is intentionally separate from legacy pipeline defaults. The values here
are the single source of truth for the frozen V4 candidate and must not be
changed based on held-out validation outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agents.asset_ranker import RANKING_VERSION
from src.agents.transmission_builder import MIN_CASE_SUPPORT_FOR_SECOND_ORDER
from src.config import TRANSMISSION_CONTEXT_V1_PATH
from src.mechanism_context import (
    CANONICAL_FAMILY_VERSION,
    MECHANISM_COMPATIBILITY_VERSION,
    TRANSMISSION_CONTEXT_VERSION,
)


METHODOLOGY_VERSION = "V4"
PRODUCTION_VERSION = "V4.1"
POST_FREEZE_FIXES_ENABLED = True
POST_FREEZE_FIX_MANIFEST = (
    "data/validation_v4/execution_diagnostics/"
    "v4_post_freeze_production_fix_manifest.json"
)


@dataclass(frozen=True)
class FrozenV4Config:
    """Immutable configuration for frozen GeoRisk V4 execution."""

    version: str = "GeoRisk V4"
    freeze_status: str = "V4 DEVELOPMENT FROZEN"
    retrieval_top_k: int = 10
    use_mechanism_compatible_support: bool = True
    compatible_support_threshold: int = MIN_CASE_SUPPORT_FOR_SECOND_ORDER
    transmission_context_version: str = TRANSMISSION_CONTEXT_VERSION
    canonical_family_version: str = CANONICAL_FAMILY_VERSION
    mechanism_compatibility_version: str = MECHANISM_COMPATIBILITY_VERSION
    asset_ranker_version: str = RANKING_VERSION
    historical_context_sidecar: str = str(TRANSMISSION_CONTEXT_V1_PATH)


V4_CONFIG = FrozenV4Config()


def assert_v4_config(config: FrozenV4Config = V4_CONFIG) -> None:
    """Fail fast if a frozen V4 invariant drifts."""

    expected = FrozenV4Config()
    if config != expected:
        raise ValueError(f"V4 config drift detected: {config!r} != {expected!r}")
    if MIN_CASE_SUPPORT_FOR_SECOND_ORDER != 2:
        raise ValueError("V4 compatible support threshold must remain 2.")
