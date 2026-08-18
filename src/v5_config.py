"""Configuration for GeoRisk V5 Agentic Discovery MVP.

V5 is a bounded discovery layer around frozen V4 verification. The V4
configuration remains the evidence gate source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.v4_config import V4_CONFIG, assert_v4_config


ARCHITECTURE_VERSION = "v5_agentic_discovery_mvp"
REPAIR_POLICY_VERSION = "node_repair_v1"
SPECIFICITY_RECOVERY_POLICY_VERSION = "specificity_recovery_v1"
CURRENT_EVENT_APPLICABILITY_POLICY_VERSION = "current_event_applicability_v1"


@dataclass(frozen=True)
class V5DiscoveryConfig:
    """Immutable configuration for bounded V5 node discovery repair."""

    architecture_version: str = ARCHITECTURE_VERSION
    repair_policy_version: str = REPAIR_POLICY_VERSION
    specificity_recovery_policy_version: str = SPECIFICITY_RECOVERY_POLICY_VERSION
    current_event_applicability_policy_version: str = CURRENT_EVENT_APPLICABILITY_POLICY_VERSION
    enable_node_repair: bool = True
    enable_specificity_recovery: bool = False
    enable_current_event_applicability_gate: bool = False
    max_repair_attempts: int = 1
    max_new_candidate_nodes: int = 5


V5_CONFIG = V5DiscoveryConfig()
V5_REPAIR_DISABLED_CONFIG = V5DiscoveryConfig(enable_node_repair=False)
V5_SPECIFICITY_RECOVERY_CONFIG = V5DiscoveryConfig(
    enable_specificity_recovery=True,
)
V5_RECOVERY_APPLICABILITY_CONFIG = V5DiscoveryConfig(
    enable_specificity_recovery=True,
    enable_current_event_applicability_gate=True,
)


def assert_v5_config(config: V5DiscoveryConfig = V5_CONFIG) -> None:
    """Fail fast if V5 discovery bounds or frozen V4 invariants drift."""

    assert_v4_config(V4_CONFIG)
    if config.max_repair_attempts != 1:
        raise ValueError("V5 node repair MVP allows exactly one repair attempt.")
    if config.max_new_candidate_nodes != 5:
        raise ValueError("V5 node repair MVP allows at most five new candidates.")
    if config.architecture_version != ARCHITECTURE_VERSION:
        raise ValueError(f"Unexpected V5 architecture version: {config.architecture_version}")
    if config.repair_policy_version != REPAIR_POLICY_VERSION:
        raise ValueError(f"Unexpected V5 repair policy version: {config.repair_policy_version}")
    if config.specificity_recovery_policy_version != SPECIFICITY_RECOVERY_POLICY_VERSION:
        raise ValueError(
            "Unexpected V5 specificity recovery policy version: "
            f"{config.specificity_recovery_policy_version}"
        )
    if config.current_event_applicability_policy_version != CURRENT_EVENT_APPLICABILITY_POLICY_VERSION:
        raise ValueError(
            "Unexpected V5 current-event applicability policy version: "
            f"{config.current_event_applicability_policy_version}"
        )
    if config.enable_current_event_applicability_gate and not config.enable_specificity_recovery:
        raise ValueError("Current-event applicability gate requires specificity recovery.")
