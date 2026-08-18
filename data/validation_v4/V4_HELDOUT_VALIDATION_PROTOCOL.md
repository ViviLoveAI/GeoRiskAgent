# GeoRisk V4 Untouched Held-Out Validation Protocol

Status: protocol scaffold only. No held-out events, predictions, prices, CAR, or hit labels have been created by this artifact.

## Frozen V4 Configuration

- top_k: 10
- mechanism-compatible support: enabled
- compatible support threshold: 2
- TransmissionContext: transmission_context_v1
- canonical family: canonical_family_v1
- mechanism compatibility: mechanism_compatibility_candidate_v1
- Asset Ranker: ranking_v1
- historical context sidecar: /Users/weiyuliu/Documents/GeoRisk Agentic RAG project/data/transmission_context_v1.json

## Non-Negotiable Guardrails

- Do not inspect CAR, SCAR, price returns, hit labels, or post-event market outcomes before event selection and prediction snapshots are sealed.
- Do not tune top_k, support threshold, canonical families, TransmissionContext schema, ranking, labels, or compatibility semantics after held-out evaluation begins.
- Any held-out failure becomes a post-freeze V5 candidate issue, not a V4 tuning opportunity.

## Required Sequence

1. Collect candidate events using only pre-outcome source facts.
2. Screen candidates for held-out status and KB/V1/V2/V3 non-overlap.
3. Select final V4 held-out set and seal event manifest hash.
4. Run frozen run_v4_pipeline only; freeze prediction snapshots.
5. Seal snapshot hashes before any CAR, price, or return inspection.
6. Only then prepare price inputs and run CAR validation.

## Event Selection Requirements

- Source-backed, contemporaneous event description.
- Clear event date T0.
- No exact V1/V2/V3 overlap.
- No exact incident-level historical KB duplicate.
- Clean estimation window and low confounding for later CAR use.

## Current State

- heldout_events_created: false
- predictions_frozen: false
- car_run: false

