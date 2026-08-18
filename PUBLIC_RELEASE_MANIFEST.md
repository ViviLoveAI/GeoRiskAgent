# GeoRisk Public Release Manifest

Release candidate date: 2026-08-18  
Status source: `PUBLIC_RELEASE_AUDIT_V5.md` and `public_release_audit_v5.json`

This manifest defines the intended public GitHub snapshot for the frozen GeoRisk V5 MVP release. It is a packaging document only. It does not change V4/V5 thresholds, gates, retrieval behavior, node repair behavior, applicability semantics, labels, or frozen experiment outputs.

## A. Core Runtime

Include these files because they are required to run the production V4/V4.1 system, CLI, API, Streamlit demo, or local knowledge-base rebuild:

| Path | Reason |
| --- | --- |
| `src/` | Core pipeline, schemas, config, V4/V5 configs, agents, API, report formatting, vector-store health tooling. |
| `app.py` | Streamlit frontend. |
| `data/historical_cases.json` | Curated historical case knowledge base used by retrieval. |
| `data/asset_mapping.csv` | Curated asset universe; runtime must not invent tickers. |
| `data/transmission_context_v1.json` | V4 mechanism-context sidecar. |
| `requirements.txt` | Single supported Python dependency entry point. |
| `.env.example` | Documents optional API and model/bootstrap settings without secrets. |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore` | Local container packaging and compose validation. |
| `.gitignore` | Prevents local-only, raw, credential, cache, and generated data from entering Git. |
| `AGENTS.md` | Repository guardrails for future AI-assisted work. |

Production `/analyze` remains V4/V4.1. V5 is preserved as a frozen Python/evaluation path and must not be described as the production API.

## B. V5 Frozen Evaluation

Include these code/config files because they define the frozen V5 MVP path and its verification boundary:

| Path | Reason |
| --- | --- |
| `src/v5_config.py` | Explicit V5 architecture, repair, specificity recovery, applicability gate, and budget policies. |
| `src/v5_models.py` | V5 state/result models. |
| `src/v5_pipeline.py` | Bounded V5 orchestration around the frozen V4 verification boundary. |
| `src/agents/node_discovery_repair.py` | Bounded node repair implementation. |
| `src/agents/repaired_context_projection.py` | Repaired-node current-context projection and applicability cue handling. |
| `src/nodes.py` | Controlled node vocabulary utilities. |
| `src/mechanism_context.py` and `src/transmission_context_store.py` | V4 support semantics reused by V5 verification. |
| `src/v4_config.py` | Frozen V4 configuration inherited by V5 verification. |
| `src/orchestration/langgraph_v5.py` | Thin LangGraph state-machine adapter around the existing frozen V5 workflow. |

The public frozen V5 condition is the recovery/applicability configuration documented by `V5_RECOVERY_APPLICABILITY_CONFIG` and the `condition_d_recovery_applicability_gate` artifacts. Do not infer that bare `V5_CONFIG` is the headline release condition.

## C. Canonical Evaluation Artifacts

Include the compact authoritative artifacts needed to trace public README claims:

| Path | Classification | Reason |
| --- | --- | --- |
| `data/validation_general/results/v3_v4_paired_evaluation_summary.json` | Canonical public benchmark/result | Source for V4 reliability headline metrics. |
| `data/validation_v4/results/attempt_002/v4_temporal_mechanism_evaluation_summary.json` | Canonical public benchmark/result | Source for V4 temporal held-out metrics. |
| `data/validation_v4/results/attempt_002/v4_temporal_compatible_node_funnel_summary.json` | Canonical public diagnostic | Source for temporal compatible-node funnel. |
| `data/validation_v4/execution_diagnostics/v4_post_freeze_production_fix_manifest.json` | Canonical provenance | Documents audited post-freeze implementation fixes without changing frozen metrics. |
| `data/topk_sensitivity_v4/topk_sensitivity_summary.json` | Canonical public benchmark/result | Source for README top-k sensitivity table. |
| `data/topk_sensitivity_v4/v4_final_freeze_manifest.json` | Canonical provenance | Documents frozen V4 configuration and artifact set. |
| `data/topk_sensitivity_v4/v4_freeze_checksums.json` | Canonical provenance | Supports freeze integrity checks. |
| `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_experiment_summary.json` | Canonical public benchmark/result | Source for headline V4 vs V5 temporal result. |
| `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_four_condition_funnel.csv` | Canonical diagnostic | Compact A/B/C/D funnel comparison. |
| `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_review.csv` | Canonical diagnostic | Human-readable final recovery/applicability review. |
| `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_three_probe_comparison.csv` | Supporting canonical diagnostic | Documents probe-level comparison used in the final V5 analysis. |
| `data/validation_v5/recovery_applicability_ab/condition_d_recovery_applicability_gate/` | Canonical V5 final condition | Contains summary, event results, mechanism evaluation, funnel, snapshots, trajectory review, accepted specificity review, and raw prediction provenance for the final frozen V5 condition. |
| `data/validation_v5/recovery_applicability_ab/condition_b_v5_0_2/` and `condition_c_specificity_recovery/` | Supporting non-headline evidence | Needed because the final experiment summary references these condition summaries for A/B/C/D comparison. |
| `data/market_validation/broad_random/broad_random_summary.json` | Optional public validation summary | Source for optional ex-post market-validation README table. |
| `data/market_validation/curated_activation/activation_summary.json` | Optional public validation summary | Source for optional activation comparison table. |

Large raw V5 prediction files under the final `recovery_applicability_ab/` directory are acceptable to keep because they are modest in size and referenced by summary provenance. Raw prediction files from older noncanonical V5 experiment directories are excluded.

## D. Documentation

Include these documents:

| Path | Reason |
| --- | --- |
| `README.md` | Primary public onboarding and truth source. |
| `ARCHITECTURE.md` | Historical architecture context; header points readers to README for current release truth. |
| `CHANGELOG.md` | Historical change record; header points readers to README for current release truth. |
| `PROJECT_SPEC.md` | Project scope and implementation intent. |
| `RELEASE_NOTES.md` | Release-facing notes if retained by owner. |
| `PUBLIC_RELEASE_AUDIT_V5.md` and `public_release_audit_v5.json` | Evidence-based public-release audit and machine-readable summary. |
| `PUBLIC_RELEASE_MANIFEST.md` | This canonical release packaging manifest. |
| `PUBLIC_RELEASE_FINAL_CHECK.md` | Final release verification report. |
| `docs/DATA_POLICY.md` | Public raw/source/price data policy. |
| `docs/*.md` | Evaluation workflow and design notes that explain frozen artifacts. |
| `LICENSE` | Project license. |

Older `PUBLIC_RELEASE_AUDIT.md` and `PUBLIC_RELEASE_VERIFICATION.md` may remain as historical cleanup records. They should not supersede the V5 audit.

## E. Tests

Include `tests/` because it is the public deterministic regression suite. The mandatory release gate is:

```bash
pytest -q
```

The expected current result is 322 passed tests after the LangGraph equivalence tests were added. CI sets `USE_LLM_EVENT_ANALYST=false` and `GEORISK_LOCAL_MODEL_FILES_ONLY=true`, so tests do not require OpenAI credentials or paid API calls.

Script-level smoke/evaluation helpers under `scripts/` should remain available for reproducibility and provenance. Some scripts require network/provider access for optional market-data regeneration; they are not part of normal CI.

## F. Examples / Demo Assets

Include only lightweight assets that help a first-time visitor understand the project:

| Path | Reason |
| --- | --- |
| `assets/dashboard.png` | README/demo visual. |
| `assets/assets:red_sea_report.png` | Example report screenshot. |
| `assets/assets:semiconductor_report.png` | Example report screenshot. |
| `data/evaluation_cases.json` and `data/hard_evaluation_cases.json` | Small deterministic example/evaluation inputs. |

## G. Excluded Material

The following categories must stay out of Git and container build context:

| Category | Paths / Patterns | Reason |
| --- | --- | --- |
| Secrets and local environment | `.env`, `.env.*`, credential JSON, private keys, bearer tokens | Must never be public. `.env.example` is the only allowed env file. |
| Raw source/news dumps | `data/validation_candidates/raw/`, `data/validation_v3/candidates/raw/`, `data/validation_v3/candidates_2019_2024/raw/`, non-placeholder files under `data/validation_v4/candidates/raw/` | Redistribution terms and copied snippets are unclear. |
| Downloaded market-price data | `data/prices/`, `data/eval/*prices*.csv`, `data/market_validation/**/prices/` | Provider redistribution terms are unclear; regenerate locally. |
| Chroma/vector DB state | `chroma_db/`, `chroma_db_backup*/` | Generated local runtime state; rebuild from public data. |
| Local model/cache files | `.cache/`, `.huggingface/`, `models/` | Generated user-machine state and potentially large. |
| Python/test caches | `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/` | Generated local state. |
| Logs/tmp/editor files | `logs/`, `tmp/`, `temp/`, `*.log`, `.DS_Store`, `.idea/`, `.vscode/` | Local-only noise. |
| Noncanonical V5 scratch/intermediate experiments | `data/validation_v5/guardrail_routing_audit/`, `node_repair_ab/`, `node_repair_ab_v2/`, `node_repair_projection_ab/`, `specificity_recovery_ab/` | Superseded by the final `recovery_applicability_ab/` condition set and not needed for headline claims. |

## Absolute Local Paths

Remaining concrete `/Users/...` strings are preserved only in frozen/provenance artifacts:

- `data/transmission_context_v1.json`
- `data/topk_sensitivity_v4/v4_freeze_candidate_manifest.json`
- `data/topk_sensitivity_v4/v4_final_freeze_manifest.json`
- `data/topk_sensitivity_v4/v4_freeze_checksums.json`
- `data/validation_v4/V4_HELDOUT_VALIDATION_PROTOCOL.md`
- `data/validation_v4/v4_heldout_protocol_manifest.json`

These are historical provenance strings, not runtime paths. They should not block clean-machine execution. Normalizing them should be a dedicated provenance migration only if checksum implications are explicitly handled.

## Release Snapshot Rule

Before the public commit, stage intentionally:

1. Runtime code/config/data needed by README quick start.
2. Frozen V4/V5 configs and deterministic tests.
3. Canonical compact evaluation artifacts listed above.
4. Documentation and release audit/manifest/final check files.

Do not stage ignored raw/source dumps, price datasets, Chroma state, caches, or noncanonical V5 scratch directories.
