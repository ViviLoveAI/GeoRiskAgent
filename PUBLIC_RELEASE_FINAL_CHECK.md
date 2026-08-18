# GeoRisk Public Release Final Check

Final check date: 2026-08-18  
Release scope: public GitHub release candidate for the V4/V4.1 production system, frozen V5 MVP evaluation path, and thin LangGraph V5 orchestration adapter.

## A. Final Status

READY FOR PUBLIC RELEASE

The repository is ready for owner review and public release after staging the intended release snapshot. No P0 blockers remain. The remaining issues are non-blocking packaging/documentation choices.

## B. Files Added / Modified

Release-packaging changes made in this task:

- Added `PUBLIC_RELEASE_MANIFEST.md` to define the canonical public snapshot.
- Added `.github/workflows/ci.yml` with a minimal credential-free CI gate.
- Updated `.gitignore` and `.dockerignore` to keep noncanonical V5 scratch/intermediate directories out of Git and Docker build context.
- Added this `PUBLIC_RELEASE_FINAL_CHECK.md`.
- Added `src/orchestration/langgraph_v5.py` as a thin LangGraph adapter around the frozen V5 bounded recovery workflow.
- Added `tests/test_langgraph_v5_equivalence.py` to prove methodology-relevant equivalence between the frozen V5 runner and the LangGraph runner.
- Added `langgraph>=0.2,<0.3` to `requirements.txt`.

Previously completed safety-cleanup files that are part of the public candidate:

- `.env.example`
- `LICENSE`
- `pytest.ini`
- `docs/DATA_POLICY.md`
- `PUBLIC_RELEASE_AUDIT_V5.md`
- `public_release_audit_v5.json`

No V4/V5 methodology, thresholds, retrieval behavior, transmission logic, repair logic, applicability semantics, evaluation labels, or frozen result values were changed.

## C. Canonical Public Artifact Set

Core runtime:

- `src/`
- `app.py`
- `data/historical_cases.json`
- `data/asset_mapping.csv`
- `data/transmission_context_v1.json`
- `requirements.txt`
- `.env.example`
- `Dockerfile`
- `docker-compose.yml`

Frozen V5 code/config:

- `src/v5_config.py`
- `src/v5_models.py`
- `src/v5_pipeline.py`
- `src/agents/node_discovery_repair.py`
- `src/agents/repaired_context_projection.py`
- `src/v4_config.py`
- `src/mechanism_context.py`
- `src/transmission_context_store.py`
- `src/orchestration/langgraph_v5.py`

Canonical evaluation artifacts:

- `data/validation_general/results/v3_v4_paired_evaluation_summary.json`
- `data/validation_v4/results/attempt_002/v4_temporal_mechanism_evaluation_summary.json`
- `data/validation_v4/results/attempt_002/v4_temporal_compatible_node_funnel_summary.json`
- `data/validation_v4/execution_diagnostics/v4_post_freeze_production_fix_manifest.json`
- `data/topk_sensitivity_v4/topk_sensitivity_summary.json`
- `data/topk_sensitivity_v4/v4_final_freeze_manifest.json`
- `data/topk_sensitivity_v4/v4_freeze_checksums.json`
- `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_experiment_summary.json`
- `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_four_condition_funnel.csv`
- `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_review.csv`
- `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_three_probe_comparison.csv`
- `data/validation_v5/recovery_applicability_ab/condition_b_v5_0_2/`
- `data/validation_v5/recovery_applicability_ab/condition_c_specificity_recovery/`
- `data/validation_v5/recovery_applicability_ab/condition_d_recovery_applicability_gate/`

Documentation/tests:

- `README.md`
- `ARCHITECTURE.md`
- `CHANGELOG.md`
- `PROJECT_SPEC.md`
- `RELEASE_NOTES.md`
- `PUBLIC_RELEASE_AUDIT_V5.md`
- `public_release_audit_v5.json`
- `PUBLIC_RELEASE_MANIFEST.md`
- `docs/DATA_POLICY.md`
- `docs/*.md`
- `tests/`
- `.github/workflows/ci.yml`
- `LICENSE`

## D. Excluded Data / Artifacts

Confirmed excluded by `.gitignore` and/or `.dockerignore`:

- `.env` and `.env.*`, except `.env.example`
- raw source/news/candidate dumps
- downloaded market-price files
- local Chroma/vector DB state
- Chroma backup directories
- local model/cache directories
- Python and pytest caches
- logs/tmp/editor/system files
- noncanonical V5 scratch/intermediate experiment directories

The final V5 `recovery_applicability_ab/` artifacts remain eligible for public release and are not ignored.

## E. Test Results

Final verification commands:

| Check | Result |
| --- | --- |
| `pytest -q` | 322 passed, 0 failed, 0 skipped, 3 warnings |
| CLI smoke test | Passed |
| `docker compose config` | Passed |
| JSON parse checks | Passed for audit, V4 summary, and V5 recovery/applicability artifacts |
| V4 wrapped checksum validation | Passed |
| Canonical V4/V5 metric check | Passed; headline values unchanged |
| LangGraph behavioral equivalence | Passed; frozen V5 and LangGraph V5 match after ignoring timing-only latency fields |

The pytest warnings are local dependency warnings from pandas/opentelemetry plus one LangGraph/LangChain pending-deprecation warning, not release regressions.

## F. Secrets / Privacy

Final status:

- Release-candidate working tree secret scan: 0 findings.
- Git-history secret scan: 0 findings across 1 commit.
- Ignored raw candidate directories remain excluded from Git.
- Remaining concrete `/Users/...` paths are frozen/provenance strings, not runtime paths. They are documented in `PUBLIC_RELEASE_MANIFEST.md`.

## G. Freeze Integrity

V4/V5 freeze integrity is preserved.

- Production `/analyze` remains V4/V4.1.
- V5 remains a frozen Python/evaluation path only, with an optional LangGraph orchestration representation.
- V5 headline condition remains `recovery_applicability_ab/condition_d_recovery_applicability_gate`.
- No frozen evaluation outputs were regenerated.
- Canonical temporal values remain:
  - V4 compatible retained: 3/21
  - V5 compatible retained: 5/21
  - V4 false rejection: 18
  - V5 false rejection: 16
  - Weak leakage: 0 for both V4 and V5
  - False acceptance: 0 for both V4 and V5

## H. CI

Added `.github/workflows/ci.yml`.

The workflow:

1. checks out the repository;
2. sets up Python 3.11;
3. installs `requirements.txt`;
4. runs `pytest -q`;
5. validates `docker compose config`.

CI sets `USE_LLM_EVENT_ANALYST=false` and `GEORISK_LOCAL_MODEL_FILES_ONLY=true`, so it is expected to run without OpenAI credentials, paid LLM calls, deployment access, or downloaded market-price data.

## I. Remaining Non-Blocking Issues

- The working tree is still unstaged/uncommitted relative to the single initial commit. The owner should stage the intended release snapshot deliberately.
- Some frozen/provenance artifacts contain historical absolute local paths. They are documented and do not affect runtime execution.
- Older public-release audit/verification files may remain as historical records, but `PUBLIC_RELEASE_AUDIT_V5.md` is the current source of truth.
- Dependencies use lower bounds rather than a lockfile. This is acceptable for the MVP release, but a constraints file would improve long-term reproducibility.

## J. Recommended Release Commit

Suggested commit message:

```text
release: publish GeoRisk V5 evaluation and V4 production system
```

Suggested tag:

```text
v1.0.0
```
