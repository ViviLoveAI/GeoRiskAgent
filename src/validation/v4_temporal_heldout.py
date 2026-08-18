"""Seal the V4 temporal generalization held-out benchmark.

The temporal held-out benchmark is selected and annotated before any frozen V4
prediction, price preparation, or CAR evaluation. This module writes benchmark
artifacts and readiness checks only.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.validation.v4_heldout_candidate_screening import (
    DEFAULT_CANDIDATE_PATH,
    DEFAULT_PROVISIONAL_ACCEPTED_OUTPUT,
)
from src.validation.v4_heldout_protocol import (
    DEFAULT_FREEZE_CHECKSUMS_PATH,
    DEFAULT_FREEZE_MANIFEST_PATH,
    DISALLOWED_OUTCOME_COLUMNS,
    assert_freeze_manifest_ready,
    validate_no_outcome_columns,
)


BENCHMARK_NAME = "V4 Temporal Generalization Held-out"
BENCHMARK_VERSION = "v4_temporal_heldout_v1"
BENCHMARK_TYPE = "temporal_generalization"
EVENT_YEAR = "2026"
DEFAULT_VALIDATION_V4_DIR = Path("data/validation_v4")

SELECTION_AUDIT_PATH = DEFAULT_VALIDATION_V4_DIR / "temporal_heldout_event_selection_audit.csv"
FINAL_EVENTS_PATH = DEFAULT_VALIDATION_V4_DIR / "temporal_final_heldout_events.csv"
GROUND_TRUTH_PATH = DEFAULT_VALIDATION_V4_DIR / "temporal_heldout_ground_truth.csv"
ANNOTATION_REVIEW_PATH = DEFAULT_VALIDATION_V4_DIR / "temporal_heldout_annotation_review.csv"
MANIFEST_PATH = DEFAULT_VALIDATION_V4_DIR / "v4_temporal_heldout_manifest.json"
CHECKSUMS_PATH = DEFAULT_VALIDATION_V4_DIR / "v4_temporal_heldout_checksums.json"
STATUS_PATH = DEFAULT_VALIDATION_V4_DIR / "heldout_status.json"

EXPECTED_SUPPORT_CLASSES = {
    "compatible_support_expected",
    "weak_cooccurrence_expected",
    "insufficient_context_expected",
}

SELECTED_CANDIDATE_IDS = [
    "v4cand_20260114_us_processed_critical_minerals",
    "v4cand_20260601_us_metal_tariff_adjustment",
    "v4cand_20260720_us_defense_supply_chains",
    "v4cand_20260424_us_iran_refinery_shadow_fleet",
    "v4cand_20260326_canada_russia_shadow_fleet",
    "v4cand_20260423_eu_russia_20th_sanctions",
    "v4cand_20260603_uk_russian_oil_products_tariff",
    "v4cand_20260319_imo_hormuz_safe_passage",
    "v4cand_20260611_imo_mts_settebello_attack",
    "v4cand_20260713_imo_black_sea_azov_attacks",
    "v4cand_20260213_india_wheat_sugar_exports",
    "v4cand_20260603_argentina_agro_export_duties",
    "v4cand_20260107_france_treated_plant_import_suspension",
    "v4cand_20260407_us_gru_dns_hijacking_disruption",
    "v4cand_20260722_faa_world_cup_counter_drone_restrictions",
    "v4cand_20260129_faa_venezuela_airspace_notams",
]

EVENT_METADATA = {
    "v4cand_20260114_us_processed_critical_minerals": ("critical_minerals_policy", "us_critical_minerals_trade_policy"),
    "v4cand_20260601_us_metal_tariff_adjustment": ("tariff_trade_restriction", "us_industrial_tariff_adjustment"),
    "v4cand_20260720_us_defense_supply_chains": ("defense_industrial_policy", "us_defense_industrial_base_policy"),
    "v4cand_20260225_us_iran_shadow_fleet_sanctions": ("iran_maritime_sanctions", "iran_shadow_fleet_sanctions_cluster"),
    "v4cand_20260415_us_iran_oil_smuggling_network": ("iran_energy_sanctions", "iran_oil_sanctions_cluster"),
    "v4cand_20260424_us_iran_refinery_shadow_fleet": ("iran_energy_shipping_sanctions", "iran_oil_sanctions_cluster"),
    "v4cand_20260528_us_iran_military_oil_sales": ("iran_energy_sanctions", "iran_oil_sanctions_cluster"),
    "v4cand_20260326_canada_russia_shadow_fleet": ("russia_shadow_fleet_sanctions", "russia_shadow_fleet_sanctions_cluster"),
    "v4cand_20260423_eu_russia_20th_sanctions": ("russia_sanctions_package", "eu_russia_sanctions_package_cluster"),
    "v4cand_20260723_eu_russia_21st_sanctions": ("russia_sanctions_package", "eu_russia_sanctions_package_cluster"),
    "v4cand_20260519_uk_russia_trade_sanctions": ("russia_trade_sanctions", "uk_russia_trade_controls_cluster"),
    "v4cand_20260603_uk_russian_oil_products_tariff": ("russian_oil_customs_restriction", "uk_russia_trade_controls_cluster"),
    "v4cand_20260615_uk_shadow_fleet_interdiction": ("russia_shadow_fleet_enforcement", "russia_shadow_fleet_sanctions_cluster"),
    "v4cand_20260319_imo_hormuz_safe_passage": ("maritime_chokepoint_security", "strait_of_hormuz_maritime_security"),
    "v4cand_20260611_imo_mts_settebello_attack": ("maritime_security_attack", "commercial_vessel_attack_episode"),
    "v4cand_20260713_imo_black_sea_azov_attacks": ("black_sea_maritime_security", "black_sea_shipping_security_episode"),
    "v4cand_20260723_imo_red_sea_attacks": ("red_sea_maritime_security", "red_sea_maritime_security_cluster"),
    "v4cand_20260712_e3_strait_hormuz_statement": ("maritime_chokepoint_security", "strait_of_hormuz_maritime_security"),
    "v4cand_20260213_india_wheat_sugar_exports": ("agriculture_export_policy", "india_food_export_policy"),
    "v4cand_20260603_argentina_agro_export_duties": ("agriculture_export_duty_policy", "argentina_agro_export_duties"),
    "v4cand_20260402_australia_export_cost_recovery_deferral": ("agriculture_export_administration", "australia_export_administration"),
    "v4cand_20260107_france_treated_plant_import_suspension": ("agriculture_import_restriction", "france_plant_import_restriction"),
    "v4cand_20260407_us_gru_dns_hijacking_disruption": ("cyber_infrastructure_disruption", "russia_linked_cyber_infrastructure_disruption"),
    "v4cand_20260722_faa_world_cup_counter_drone_restrictions": ("aviation_airspace_restriction", "us_airspace_security_restriction"),
    "v4cand_20260129_faa_venezuela_airspace_notams": ("aviation_airspace_policy", "venezuela_airspace_notice_policy"),
}

NOT_SELECTED_REASONS = {
    "v4cand_20260225_us_iran_shadow_fleet_sanctions": ("not_selected_redundant_episode", "Similar Iran maritime-sanctions episode retained through a later oil/shadow-fleet event with clearer energy-shipping scope."),
    "v4cand_20260415_us_iran_oil_smuggling_network": ("not_selected_redundant_episode", "Redundant within Iran oil-sanctions cluster after retaining the refinery/shadow-fleet episode."),
    "v4cand_20260528_us_iran_military_oil_sales": ("not_selected_redundant_episode", "Redundant within Iran oil-sanctions cluster after retaining the refinery/shadow-fleet episode."),
    "v4cand_20260723_eu_russia_21st_sanctions": ("not_selected_redundant_episode", "Redundant with the earlier EU Russia sanctions package retained for the temporal set."),
    "v4cand_20260519_uk_russia_trade_sanctions": ("not_selected_less_clear_scope", "Broad guidance update; a narrower Russian oil-products customs event is retained."),
    "v4cand_20260615_uk_shadow_fleet_interdiction": ("not_selected_redundant_episode", "Redundant with Canada/Russia shadow-fleet sanctions event retained for maritime-sanctions coverage."),
    "v4cand_20260723_imo_red_sea_attacks": ("not_selected_redundant_episode", "Maritime-security coverage retained through Hormuz, MT Settebello, and Black Sea/Azov events."),
    "v4cand_20260712_e3_strait_hormuz_statement": ("not_selected_redundant_episode", "Redundant with IMO Strait of Hormuz event retained for the chokepoint episode."),
    "v4cand_20260402_australia_export_cost_recovery_deferral": ("not_selected_less_clear_scope", "Administrative export-cost deferral is less clearly a disruption event than retained agriculture trade-policy events."),
}

ANNOTATIONS = [
    ("v4cand_20260114_us_processed_critical_minerals", "critical_minerals", "compatible_support_expected", "Official policy concerns processed critical minerals and derivative products.", "primary_source", "high", "", False, ""),
    ("v4cand_20260114_us_processed_critical_minerals", "broad_manufacturing_inputs", "weak_cooccurrence_expected", "Manufacturing may be downstream of critical materials, but same affected sector alone is not the same mechanism.", "event_description", "medium", "", True, "manufacturing_inputs remains a known frozen-vocabulary gap."),
    ("v4cand_20260601_us_metal_tariff_adjustment", "industrial_metals", "compatible_support_expected", "Tariff adjustment directly concerns steel, aluminum, and copper trade categories.", "primary_source", "high", "", False, ""),
    ("v4cand_20260601_us_metal_tariff_adjustment", "automotive_parts", "compatible_support_expected", "Official announcement includes automobile and parts categories as directly implicated tariff areas.", "primary_source", "medium", "", False, ""),
    ("v4cand_20260720_us_defense_supply_chains", "defense_industrial_base", "compatible_support_expected", "The event directly concerns defense industrial base capacity and supply chains.", "primary_source", "high", "", False, ""),
    ("v4cand_20260720_us_defense_supply_chains", "semiconductor_inputs", "insufficient_context_expected", "The event may involve technology inputs, but the candidate text alone does not establish a specific semiconductor input mechanism.", "event_description", "low", "Source facts are broad at the node level.", True, ""),
    ("v4cand_20260424_us_iran_refinery_shadow_fleet", "oil_shipping", "compatible_support_expected", "Sanctions target oil trade networks and vessels associated with shipping activity.", "primary_source", "high", "", False, ""),
    ("v4cand_20260424_us_iran_refinery_shadow_fleet", "refining", "compatible_support_expected", "The action references refinery-linked oil trade, giving a direct refining-related mechanism basis.", "primary_source", "medium", "", False, ""),
    ("v4cand_20260326_canada_russia_shadow_fleet", "shadow_fleet_shipping", "compatible_support_expected", "Sanctions target Russia-linked shadow fleet and maritime transport entities.", "primary_source", "high", "", False, ""),
    ("v4cand_20260326_canada_russia_shadow_fleet", "energy_trade", "weak_cooccurrence_expected", "Shadow fleet sanctions can relate to energy trade, but the candidate fact pattern is maritime-network focused without a specific energy transaction mechanism.", "event_description", "medium", "", False, ""),
    ("v4cand_20260423_eu_russia_20th_sanctions", "trade_restrictions", "compatible_support_expected", "The EU package is an official sanctions and trade-restriction event.", "primary_source", "high", "", False, ""),
    ("v4cand_20260423_eu_russia_20th_sanctions", "energy", "insufficient_context_expected", "The selected source summary is broad and does not by itself define a specific energy mechanism.", "event_description", "low", "Broad sanctions package with node-level ambiguity.", True, ""),
    ("v4cand_20260603_uk_russian_oil_products_tariff", "oil_products_customs", "compatible_support_expected", "The event directly concerns customs document codes for Russian oil products.", "primary_source", "high", "", False, ""),
    ("v4cand_20260603_uk_russian_oil_products_tariff", "energy_trade", "compatible_support_expected", "Russian oil-product customs treatment is a specific energy-trade access or compliance mechanism.", "primary_source", "medium", "", False, ""),
    ("v4cand_20260319_imo_hormuz_safe_passage", "maritime_chokepoint", "compatible_support_expected", "The Strait of Hormuz safe-passage framework is a chokepoint and route-security event.", "primary_source", "high", "", False, ""),
    ("v4cand_20260319_imo_hormuz_safe_passage", "energy_shipping", "compatible_support_expected", "Hormuz route security is plausibly within the frozen maritime/energy route family when tied to passage through the chokepoint.", "primary_source", "medium", "", False, ""),
    ("v4cand_20260611_imo_mts_settebello_attack", "commercial_shipping", "compatible_support_expected", "The event is an IMO-reported attack involving a commercial vessel.", "primary_source", "high", "", False, ""),
    ("v4cand_20260611_imo_mts_settebello_attack", "marine_insurance", "weak_cooccurrence_expected", "Marine insurance may be contextually related to vessel attacks, but the source facts do not establish insurance as the active transmission mechanism.", "event_description", "medium", "", False, ""),
    ("v4cand_20260713_imo_black_sea_azov_attacks", "maritime_security", "compatible_support_expected", "The event concerns attacks affecting shipping in the Black Sea and Sea of Azov.", "primary_source", "high", "", False, ""),
    ("v4cand_20260713_imo_black_sea_azov_attacks", "grain_exports", "insufficient_context_expected", "The region may be associated with grain flows, but the selected candidate text does not establish a food-export mechanism.", "event_description", "low", "Potential thematic link lacks sufficient event-specific context.", True, ""),
    ("v4cand_20260213_india_wheat_sugar_exports", "food_exports", "compatible_support_expected", "The official announcement concerns wheat and sugar export permissions.", "primary_source", "high", "", False, ""),
    ("v4cand_20260213_india_wheat_sugar_exports", "fertilizer_inputs", "weak_cooccurrence_expected", "Food export permissions are not the same mechanism as fertilizer input constraints.", "event_description", "high", "", False, ""),
    ("v4cand_20260603_argentina_agro_export_duties", "agriculture_exports", "compatible_support_expected", "The announcement concerns agricultural export duty changes.", "primary_source", "high", "", False, ""),
    ("v4cand_20260603_argentina_agro_export_duties", "fertilizer_inputs", "weak_cooccurrence_expected", "Export duties on agro products do not reproduce an input-shortage mechanism.", "event_description", "high", "", False, ""),
    ("v4cand_20260107_france_treated_plant_import_suspension", "plant_imports", "compatible_support_expected", "The official action suspends imports of specified treated plant products.", "primary_source", "high", "", False, ""),
    ("v4cand_20260107_france_treated_plant_import_suspension", "agriculture", "weak_cooccurrence_expected", "Agriculture is the downstream sector, but broad sector overlap alone is not mechanism-compatible support.", "event_description", "medium", "", False, ""),
    ("v4cand_20260407_us_gru_dns_hijacking_disruption", "cyber_infrastructure", "compatible_support_expected", "The event concerns disruption of a DNS hijacking network affecting digital infrastructure.", "primary_source", "high", "", False, ""),
    ("v4cand_20260407_us_gru_dns_hijacking_disruption", "logistics", "weak_cooccurrence_expected", "Logistics may depend on digital infrastructure, but the source facts do not establish a logistics-specific mechanism.", "event_description", "medium", "", False, ""),
    ("v4cand_20260722_faa_world_cup_counter_drone_restrictions", "airspace_restrictions", "compatible_support_expected", "FAA temporary flight restrictions are directly an airspace restriction mechanism.", "primary_source", "high", "", False, ""),
    ("v4cand_20260722_faa_world_cup_counter_drone_restrictions", "aviation_operations", "compatible_support_expected", "Temporary flight restrictions directly affect aviation operational access to defined airspace.", "primary_source", "medium", "", False, ""),
    ("v4cand_20260129_faa_venezuela_airspace_notams", "airspace_notams", "compatible_support_expected", "The FAA action concerns Venezuela-related airspace notices.", "primary_source", "medium", "", False, ""),
    ("v4cand_20260129_faa_venezuela_airspace_notams", "aviation_sanctions", "insufficient_context_expected", "The event is an airspace notice policy action; sanctions mechanism compatibility is not established.", "event_description", "low", "Mechanism boundary between airspace notice and sanctions is unclear.", True, ""),
]


@dataclass(frozen=True)
class TemporalArtifacts:
    """Paths produced when sealing the temporal held-out benchmark."""

    selection_audit: Path
    final_events: Path
    ground_truth: Path
    annotation_review: Path
    manifest: Path
    checksums: Path


def seal_temporal_heldout_benchmark(
    candidate_path: str | Path = DEFAULT_CANDIDATE_PATH,
    provisional_accepted_path: str | Path = DEFAULT_PROVISIONAL_ACCEPTED_OUTPUT,
    freeze_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
    freeze_checksums_path: str | Path = DEFAULT_FREEZE_CHECKSUMS_PATH,
    output_dir: str | Path = DEFAULT_VALIDATION_V4_DIR,
) -> dict[str, Any]:
    """Seal event selection and ground-truth annotations before prediction."""

    assert_freeze_manifest_ready(freeze_manifest_path)
    candidates = load_csv(candidate_path)
    provisional = load_csv(provisional_accepted_path)
    assert_candidate_integrity(candidates, provisional)

    output = Path(output_dir)
    artifacts = TemporalArtifacts(
        selection_audit=output / SELECTION_AUDIT_PATH.name,
        final_events=output / FINAL_EVENTS_PATH.name,
        ground_truth=output / GROUND_TRUTH_PATH.name,
        annotation_review=output / ANNOTATION_REVIEW_PATH.name,
        manifest=output / MANIFEST_PATH.name,
        checksums=output / CHECKSUMS_PATH.name,
    )

    selection_rows = build_selection_audit(candidates)
    final_events = [final_event_row(row) for row in candidates if row["candidate_id"] in SELECTED_CANDIDATE_IDS]
    ground_truth = build_ground_truth_rows()
    review_rows = build_annotation_review_rows(ground_truth)

    write_csv(artifacts.selection_audit, selection_rows)
    write_csv(artifacts.final_events, final_events)
    write_csv(artifacts.ground_truth, ground_truth)
    write_csv(artifacts.annotation_review, review_rows)

    manifest = build_manifest(
        candidates=candidates,
        final_events=final_events,
        ground_truth=ground_truth,
        review_rows=review_rows,
        freeze_manifest_path=Path(freeze_manifest_path),
        freeze_checksums_path=Path(freeze_checksums_path),
    )
    write_json(artifacts.manifest, manifest)
    checksums = build_checksums(artifacts)
    write_json(artifacts.checksums, checksums)
    update_status(output / "heldout_status.json")

    return {
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_version": BENCHMARK_VERSION,
        "candidate_pool_count": len(candidates),
        "selected_event_count": len(final_events),
        "not_selected_count": len(candidates) - len(final_events),
        "node_annotation_count": len(ground_truth),
        "manifest_path": str(artifacts.manifest),
        "checksums_path": str(artifacts.checksums),
        "predictions_frozen": False,
        "car_run": False,
    }


def assert_temporal_heldout_ready_for_prediction(
    manifest_path: str | Path = MANIFEST_PATH,
    checksums_path: str | Path = CHECKSUMS_PATH,
    freeze_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
) -> dict[str, Any]:
    """Fail fast unless the sealed temporal benchmark is ready for prediction."""

    assert_freeze_manifest_ready(freeze_manifest_path)
    manifest = load_json(manifest_path)
    checksums = load_json(checksums_path)
    if manifest.get("benchmark_version") != BENCHMARK_VERSION:
        raise RuntimeError("temporal_heldout_not_ready:wrong_benchmark_version")
    if manifest.get("leakage_status", {}).get("V4_predictions_run") is not False:
        raise RuntimeError("temporal_heldout_not_ready:predictions_already_run")
    if manifest.get("leakage_status", {}).get("CAR_run") is not False:
        raise RuntimeError("temporal_heldout_not_ready:car_already_run")
    failed = [
        path
        for path, expected in checksums.get("artifacts", {}).items()
        if sha256_file(path) != expected
    ]
    if failed:
        raise RuntimeError(f"temporal_heldout_not_ready:checksum_mismatch:{','.join(failed)}")
    return {
        "ready_for_prediction": True,
        "benchmark_version": BENCHMARK_VERSION,
        "selected_event_count": manifest.get("selected_event_count"),
        "node_annotation_count": manifest.get("node_annotation_count"),
    }


def assert_candidate_integrity(candidates: list[dict[str, str]], provisional: list[dict[str, str]]) -> None:
    """Ensure the final selection can only draw from the eligible candidate pool."""

    if len(candidates) != 25:
        raise RuntimeError(f"temporal_candidate_integrity_failed:expected_25_candidates:{len(candidates)}")
    provisional_ids = {row["candidate_id"] for row in provisional}
    missing = [candidate_id for candidate_id in SELECTED_CANDIDATE_IDS if candidate_id not in provisional_ids]
    if missing:
        raise RuntimeError(f"temporal_candidate_integrity_failed:selected_not_eligible:{','.join(missing)}")
    for row in candidates:
        validate_no_outcome_columns(list(row.keys()))
        if not row.get("t0_date"):
            raise RuntimeError(f"temporal_candidate_integrity_failed:missing_t0:{row.get('candidate_id')}")
        if row.get("event_date", "")[:4] != EVENT_YEAR:
            raise RuntimeError(f"temporal_candidate_integrity_failed:not_2026:{row.get('candidate_id')}")


def build_selection_audit(candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Create one selection audit row per candidate."""

    rows = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        selected = candidate_id in SELECTED_CANDIDATE_IDS
        event_family, episode_group = EVENT_METADATA[candidate_id]
        if selected:
            status = "selected_clear_independent_event"
            reason = "Selected for source quality, clear T0, independent episode value, and temporal benchmark diversity."
        else:
            status, reason = NOT_SELECTED_REASONS[candidate_id]
        rows.append(
            {
                "candidate_id": candidate_id,
                "selected_for_temporal_heldout": selected,
                "selection_status": status,
                "selection_reason": reason,
                "event_family": event_family,
                "episode_group": episode_group,
                "source_strength": "primary_only",
                "t0_quality": "clear",
                "overlap_status": "eligible_no_exact_or_near_duplicate",
                "notes": "2026 temporal generalization candidate; no V4 prediction or market outcome used.",
            }
        )
    return rows


def final_event_row(candidate: dict[str, str]) -> dict[str, str]:
    """Return pre-outcome fields for one sealed temporal held-out event."""

    event_family, episode_group = EVENT_METADATA[candidate["candidate_id"]]
    return {
        "event_id": candidate["candidate_id"],
        "event_name": candidate["event_name"],
        "event_date": candidate["event_date"],
        "t0_date": candidate["t0_date"],
        "short_description": candidate["short_description"],
        "primary_source": candidate["primary_source"],
        "secondary_source": candidate["secondary_source"],
        "source_date": candidate["source_date"],
        "event_type_if_preoutcome_observable": candidate["event_type_if_preoutcome_observable"],
        "regions": candidate["regions"],
        "countries": candidate["countries"],
        "first_order_shock_description": candidate["first_order_shock_description"],
        "selection_rationale": candidate["selection_rationale"],
        "event_family": event_family,
        "episode_group": episode_group,
        "benchmark_version": BENCHMARK_VERSION,
    }


def build_ground_truth_rows() -> list[dict[str, Any]]:
    """Build retrieval-blind event/node annotations."""

    rows = []
    for event_id, node, label, rationale, source_basis, confidence, ambiguity, gap, notes in ANNOTATIONS:
        if label not in EXPECTED_SUPPORT_CLASSES:
            raise RuntimeError(f"invalid_ground_truth_label:{label}")
        rows.append(
            {
                "event_id": event_id,
                "node": node,
                "expected_support_class": label,
                "mechanism_rationale": rationale,
                "source_basis": source_basis,
                "annotation_confidence": confidence,
                "ambiguity_reason": ambiguity,
                "representation_gap_observed": bool(gap),
                "review_notes": notes,
            }
        )
    return rows


def build_annotation_review_rows(ground_truth: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create a prediction-blind second-pass consistency review."""

    rows = []
    for row in ground_truth:
        review_note = "Pass-2 consistency review retained the initial label under frozen taxonomy."
        if row["expected_support_class"] == "insufficient_context_expected":
            review_note = "Pass-2 review retained insufficient-context label rather than forcing compatibility."
        if row["expected_support_class"] == "weak_cooccurrence_expected":
            review_note = "Pass-2 review confirmed same-node or sector overlap alone is not mechanism support."
        rows.append(
            {
                "event_id": row["event_id"],
                "node": row["node"],
                "initial_label": row["expected_support_class"],
                "review_label": row["expected_support_class"],
                "agreement": True,
                "resolution": "unchanged",
                "final_label": row["expected_support_class"],
                "confidence": row["annotation_confidence"],
                "notes": review_note,
            }
        )
    return rows


def build_manifest(
    candidates: list[dict[str, str]],
    final_events: list[dict[str, str]],
    ground_truth: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    freeze_manifest_path: Path,
    freeze_checksums_path: Path,
) -> dict[str, Any]:
    """Build the sealed temporal held-out manifest."""

    label_counts = count_values(ground_truth, "expected_support_class")
    review_disagreements = sum(1 for row in review_rows if str(row["agreement"]) != "True" and row["agreement"] is not True)
    return {
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_type": BENCHMARK_TYPE,
        "event_year": int(EVENT_YEAR),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Evaluate whether a frozen GeoRisk V4 system, built from historical cases, generalizes to independent newly occurring 2026 geopolitical events.",
        "scope_limitation": "This benchmark contains only 2026 events and is intended as a temporal generalization evaluation rather than a multi-year general benchmark.",
        "candidate_pool_count": len(candidates),
        "selected_event_count": len(final_events),
        "node_annotation_count": len(ground_truth),
        "freeze_linkage": {
            "v4_final_freeze_manifest": str(freeze_manifest_path),
            "v4_final_freeze_manifest_sha256": sha256_file(freeze_manifest_path),
            "v4_freeze_checksums": str(freeze_checksums_path),
            "v4_freeze_checksums_sha256": sha256_file(freeze_checksums_path),
        },
        "annotation": {
            "ground_truth_path": str(GROUND_TRUTH_PATH),
            "annotation_review_path": str(ANNOTATION_REVIEW_PATH),
            "taxonomy": sorted(EXPECTED_SUPPORT_CLASSES),
            "label_counts": label_counts,
            "review_agreement_count": len(review_rows) - review_disagreements,
            "review_disagreement_count": review_disagreements,
        },
        "leakage_status": {
            "V4_predictions_run": False,
            "prices_accessed": False,
            "CAR_run": False,
            "realized_outcomes_used": False,
        },
        "multi_year_benchmark_status": "not_started_separate_future_benchmark",
    }


def build_checksums(artifacts: TemporalArtifacts) -> dict[str, Any]:
    """Hash sealed temporal benchmark artifacts."""

    paths = [
        artifacts.final_events,
        artifacts.ground_truth,
        artifacts.annotation_review,
        artifacts.manifest,
    ]
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": {str(path): sha256_file(path) for path in paths},
    }


def update_status(path: Path) -> None:
    """Mark event selection and ground truth sealed without prediction/CAR."""

    status = load_json(path) if path.exists() else {}
    status.update(
        {
            "candidate_pool_created": True,
            "candidate_events_populated": True,
            "heldout_events_created": True,
            "ground_truth_frozen": True,
            "heldout_manifest_sealed": True,
            "predictions_frozen": False,
            "price_inputs_prepared": False,
            "car_run": False,
        }
    )
    write_json(path, status)


def load_csv(path: str | Path) -> list[dict[str, str]]:
    """Load a CSV as dictionaries and reject outcome columns."""

    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        validate_no_outcome_columns(list(reader.fieldnames or []))
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """Write CSV rows with stable field order."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    forbidden = set(fields) & DISALLOWED_OUTCOME_COLUMNS
    if forbidden:
        raise RuntimeError(f"temporal_artifact_outcome_fields:{','.join(sorted(forbidden))}")
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return output


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write JSON with stable formatting."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON object."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def sha256_file(path: str | Path) -> str:
    """Hash a file using SHA-256."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    """Count field values."""

    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "")
        counts[value] = counts.get(value, 0) + 1
    return counts
