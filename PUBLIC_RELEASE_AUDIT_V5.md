# Public Release Audit - GeoRisk V5 MVP

Audit rerun date: 2026-08-18  
Scope: post-cleanup open-source readiness for the frozen GeoRisk V5 MVP. This cleanup did not change thresholds, gates, benchmark labels, retrieval depth, node repair semantics, applicability semantics, asset mapping semantics, or frozen V4/V5 outputs.

## Release Readiness

Status: READY FOR PUBLIC RELEASE

The prior P0 release blockers are cleared for a Git-based public release: secret-like raw candidate strings were sanitized, raw candidate/source dumps and downloaded market price files are excluded by `.gitignore`/`.dockerignore`, a data policy exists, a license exists, clean-machine model bootstrap is documented/configurable, the default release test command passes, and frozen V5 now has a tested thin LangGraph orchestration adapter.

Remaining work before announcement is owner review and staging: choose the exact public snapshot and decide whether to preserve absolute local paths embedded in frozen provenance artifacts as documented historical strings.

## Cleanup Changes Applied

- Sanitized 4 OpenAI-key-shaped `sk-...` URL fragments in ignored raw candidate JSON files.
- Added public data policy: `docs/DATA_POLICY.md`.
- Added MIT `LICENSE`.
- Added `.env.example`.
- Added `pytest.ini` so `pytest -q` runs the intended `tests/` suite with `pythonpath = .`.
- Added `src/orchestration/langgraph_v5.py` as a thin LangGraph state-machine adapter around the existing frozen V5 workflow.
- Added `tests/test_langgraph_v5_equivalence.py` to compare frozen V5 and LangGraph V5 methodology-relevant outputs.
- Updated `.gitignore` to exclude raw candidate/source dumps, downloaded market prices, Chroma DBs, caches, and local/generated state.
- Updated `.dockerignore` to keep raw/source dumps, downloaded prices, Chroma DBs, and caches out of container build context.
- Added explicit direct dependencies: `numpy`, `transformers`, and `yfinance`; added lower bounds for `fastapi`, `uvicorn`, and `openai`.
- Loaded `.env` in `src/config.py`.
- Made `GEORISK_LOCAL_MODEL_FILES_ONLY` configurable while preserving the stable default `true`.
- Documented clean-machine retrieval bootstrap with `GEORISK_LOCAL_MODEL_FILES_ONLY=false python -m src.vector_store_health --rebuild`.
- Updated README with frozen V5 temporal results, data policy, license, reproducibility notes, and the fact that the public `/analyze` API remains V4/V4.1.
- Recorded `src/vector_store.py` in the post-freeze production-fix manifest as a non-methodology reproducibility fix.

## Repository State

- Branch: `main`, tracking `origin/main`.
- Git history: one tracked commit, `85d26cd (HEAD -> main, origin/main) Initial GeoRisk Transmission Analyzer MVP`.
- Working tree: still dirty by design. The current repo contains the V5 release work as modified and untracked files relative to the initial MVP commit.
- Important newly created cleanup files: `.env.example`, `LICENSE`, `pytest.ini`, `docs/DATA_POLICY.md`, `PUBLIC_RELEASE_AUDIT_V5.md`, `public_release_audit_v5.json`.
- Ignored after cleanup: raw candidate/source directories, downloaded price directories/files, `chroma_db/`, Chroma backups, `.pytest_cache/`, and Python caches.

## P0 - Must Fix Before Making Repo Public

None found in the post-cleanup rerun.

Secret-like patterns now scan clean in the working tree and Git history. Raw/source dumps and downloaded market data are ignored for public release. No private keys, `.env`, AWS keys, GitHub tokens, bearer tokens, database credentials, Terraform state, or credential JSON files were found.

## P1 - Strongly Recommended Before Public Announcement

- Choose and stage the canonical public release snapshot. The tree still has many modified/untracked files relative to the single initial commit.
- Decide whether to normalize absolute local paths in frozen artifacts, or document them as preserved provenance/checksum fields.
- Select the canonical public V5 artifact set and avoid publishing duplicate/intermediate A/B outputs as equally important.
- Confirm whether full downloaded market price files should remain ignored/excluded or be distributed separately under a license-compatible release artifact.
- Decide whether raw candidate/source dumps should remain local-only permanently.
- Consider adding a minimal CI workflow after the final release file set is staged.
- Keep README/API claims aligned: production `/analyze` is V4/V4.1; V5 is frozen through the Python/evaluation path.

## P2 - Nice To Have After Initial Release

- Add `CONTRIBUTING.md`, PR template, and issue templates if the project will invite outside contributions.
- Add a fixture/offline demo path that does not require Chroma/model bootstrap.
- Reorganize evaluation artifacts under `data/evaluation/v4/` and `data/evaluation/v5/` in a provenance-preserving cleanup.

## Secret / Credential Audit

Post-cleanup working-tree scan: 0 findings.

Git history scan: 0 findings across 1 commit.

Previously flagged key-shaped strings were sanitized in local ignored raw candidate files:

- `data/validation_v3/candidates/raw/cyber_critical_infrastructure.json`
- `data/validation_v3/candidates/raw/political_instability_exports.json`
- `data/validation_candidates/raw/cyber_critical_infrastructure.json`

These raw directories are also excluded from public release.

## Personal / Machine-Specific Path Audit

Post-cleanup path scan found 11 remaining `/Users/...` occurrences. They are concentrated in preserved frozen/provenance artifacts rather than runtime code:

- `data/transmission_context_v1.json:4287`
- `data/topk_sensitivity_v4/v4_final_freeze_manifest.json:69`, `:83`
- `data/topk_sensitivity_v4/v4_freeze_checksums.json:2`
- `data/topk_sensitivity_v4/v4_freeze_candidate_manifest.json:3`, `:57`
- `data/validation_v4/v4_heldout_protocol_manifest.json:49`
- `data/validation_v4/V4_HELDOUT_VALIDATION_PROTOCOL.md:14`
- Older untracked public-release notes still contain generic `/Users/...` references, not concrete local paths.

Classification: mostly harmless artifact provenance, but still a public polish issue. Normalize only in a dedicated cleanup that preserves or explicitly supersedes checksum expectations.

## Data Licensing / Provenance Audit

- `data/historical_cases.json`: curated concise historical case summaries; safe-looking derived data, but public docs should continue to frame them as analytical summaries.
- `data/asset_mapping.csv`: curated public ticker/asset mapping; safe-looking, with no investment advice claim.
- `data/transmission_context_v1.json`: generated sidecar from historical case context; safe-looking except preserved absolute source path.
- Public evaluation summaries/manifests: safe-looking generated artifacts.
- Raw candidate/source dumps: excluded by policy and ignore rules because scraped metadata/source snippets/URL tokens may have unclear redistribution terms.
- Downloaded market prices: excluded by policy and ignore rules unless redistribution terms are confirmed.

No legal guarantee is made.

## Large / Generated File Audit

Current policy:

- Keep canonical compact summaries, manifests, checksums, final evaluator CSVs, historical cases, asset mapping, and transmission context sidecar.
- Ignore/exclude raw candidate/source dumps and downloaded price files.
- Ignore/regenerate Chroma persistence and backups.
- Ignore Python/pytest caches.

Large generated raw predictions remain untracked and should be curated before staging. The final V5 public result should prefer compact summaries and trajectory/evaluation CSVs over every raw intermediate dump.

## .gitignore / .dockerignore Audit

`.gitignore` now covers:

- `.env`, `.env.*`, `!.env.example`
- Python caches and pytest/mypy/ruff caches
- virtualenvs
- Chroma DB and Chroma backup directories
- logs/tmp/cache/model directories
- OS/editor files
- raw candidate/source dumps
- downloaded market price files

`.dockerignore` now excludes the same high-risk/heavy local data classes from image build context.

## Dependency Audit

Dependency setup remains a single `requirements.txt`.

Improvements made:

- Added explicit `numpy`, `transformers`, `yfinance`, and `langgraph`.
- Added lower bounds for `fastapi`, `uvicorn`, and `openai`.

Remaining release consideration: most dependencies are still not fully pinned. This is acceptable for an MVP public release, but a lockfile or constraints file would improve long-term reproducibility.

LangGraph is present only as a thin orchestration adapter for frozen V5. The adapter does not add checkpoint persistence, external state stores, new model providers, or product behavior.

## Reproducibility Audit

A. Minimal application run: reproducible locally. Verified:

```bash
PYTHONPATH=. python -m src.pipeline --news "Red Sea shipping routes face disruption due to escalating regional conflict." --format concise --event-analyzer rule
```

B. Clean-machine retrieval bootstrap: documented/configurable. Use:

```bash
GEORISK_LOCAL_MODEL_FILES_ONLY=false python -m src.vector_store_health --rebuild
```

After the model is cached, the default local-only mode preserves stable offline/frozen-test behavior.

C. V4 evaluation: reproducible with checked-in artifacts and docs.

D. V5 evaluation: reproducible if the final public artifact set identifies `data/validation_v5/recovery_applicability_ab/condition_d_recovery_applicability_gate/` as the frozen V5 condition.

E. V4 vs V5 comparison: traceable to `src/validation/v5_node_repair_ab.py` and `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_experiment_summary.json`.

## Frozen V4/V5 Integrity Audit

V4 protections remain intact:

- `src/v4_config.py` defines frozen V4 retrieval depth, mechanism-compatible support, support threshold, sidecar versioning, ranking version, and `assert_v4_config`.
- `tests/test_v4_config_freeze.py` verifies V4 invariants.
- `data/topk_sensitivity_v4/v4_final_freeze_manifest.json` and `v4_freeze_checksums.json` exist.
- `data/validation_v4/execution_diagnostics/v4_post_freeze_production_fix_manifest.json` records non-methodology post-freeze production fixes.

Known checksum issue status:

- `src/pipeline.py` checksum matches the V3 frozen checksum.
- Wrapped checksum validation passes after declaring the vector-store reproducibility change as a post-freeze production implementation fix.
- Frozen evaluation outputs were not regenerated.

V5 protections remain intact:

- `src/v5_config.py` defines architecture, repair, specificity recovery, and current-event applicability policy versions.
- V5 bounds remain one repair attempt and five new candidates.
- V5 verification still routes through frozen V4 verification.
- Tests cover repair-disabled V4 equivalence, bounded repair, projection, specificity recovery, applicability gate, and no arbitrary ticker introduction.

## Frozen V5 Release Configuration Audit

Explicit in code:

- architecture version: `v5_agentic_discovery_mvp`
- node repair policy: `node_repair_v1`
- specificity recovery policy: `specificity_recovery_v1`
- applicability gate policy: `current_event_applicability_v1`
- repair budget: `max_repair_attempts = 1`
- candidate budget: `max_new_candidate_nodes = 5`
- support threshold: inherited from frozen V4
- verification boundary: `_run_frozen_v4_verify`

Recommendation: document `V5_RECOVERY_APPLICABILITY_CONFIG` as the frozen public V5 condition if that is the intended release configuration, because bare `V5_CONFIG` keeps specificity recovery and applicability gate disabled.

## Test-Suite Audit

Post-cleanup command outcomes:

- `pytest -q`: 318 passed, 0 failed, 0 skipped, 3 warnings.
- Minimal CLI smoke: passed.
- `docker compose config`: passed.
- Redacted secret scan: 0 findings.
- Git-history secret scan: 0 findings.
- `src/pipeline.py` checksum match: true.
- wrapped checksum validation: passed.

Warnings are local dependency warnings from pandas/opentelemetry, not release regressions.

## Benchmark Leakage / Overfitting Audit

No runtime logic was found using event IDs, GT labels, or benchmark labels. The current-context projection remains text-cue based.

Public-review-sensitive literals remain in runtime cue vocabulary:

- `hormuz`, `suez`, `bab el-mandeb` for maritime chokepoint cues.
- `dns`, `gru` for cyber infrastructure cues.

Assessment: these are mechanism cues, not event-ID or GT-label lookups, but public documentation should frame them as controlled mechanism vocabulary and avoid overstating statistical generality.

## Current-Context Projection Generality Audit

`src/agents/repaired_context_projection.py` delegates first to the V4 projector, then applies V5-only deterministic cue rules for repaired candidates. `Hormuz`, `DNS`, and `GRU` appear as cue tokens; `MT Settebello` does not appear in runtime logic.

The applicability gate uses current-event cues and proposal metadata, not GT labels or event IDs.

## Agentic Architecture Audit

Actual mapping:

- Observe: `_analyze_event`.
- Retrieve: `retrieve_cases`.
- Diagnose: `diagnose_evidence_state`.
- Decide: V5 diagnosis branch in `run_v5_pipeline`.
- Act: `propose_node_repairs`, `repaired_retrieved_cases`, `project_repaired_node_context`.
- Verify: `_run_frozen_v4_verify`.
- Finalize / Abstain: final `AnalysisState.status` and `V5AnalysisResult`.

Defensible claim: bounded agentic RAG with shared state, diagnosis, conditional routing, bounded repair, projection, verification, termination, trajectory, and conservative abstention.

## LangGraph Orchestration Audit

LangGraph is implemented in `src/orchestration/langgraph_v5.py` as a thin adapter around the existing frozen V5 workflow. It exposes nodes for current-event preparation, retrieval, initial frozen V4 verification, repair diagnosis, bounded node repair, repaired-context projection, repaired frozen V4 verification, specificity/applicability recovery, and finalization.

Behavioral-equivalence tests in `tests/test_langgraph_v5_equivalence.py` compare the frozen V5 runner with `run_v5_langgraph` on repair-disabled, repair-enabled, and specificity/applicability-gated fixtures. Timing-only latency metadata is canonicalized; methodology-relevant fields must match.

## Public API Audit

Actual endpoints:

- `GET /health`
- `GET /version`
- `POST /analyze`

`POST /analyze` runs `run_v4_pipeline`. `/version` reports V4/V4.1 configuration. README now states this clearly. V5 remains available through Python/evaluation paths.

## Docker Audit

`docker compose config` passed. Docker still depends on the same model/bootstrap reality as local runs: a clean image may need `GEORISK_LOCAL_MODEL_FILES_ONLY=false` for the first index rebuild or a pre-populated model cache.

## AWS / Deployment Audit

Only lightweight EC2 docs/scripts were found. No Terraform, `.tfstate`, AWS credentials, private keys, account IDs, or EC2 hostnames were found.

## README Truth Audit

README now includes:

- V4/V4.1 production boundary.
- Frozen V5 MVP result table.
- Data policy reference.
- Clean-machine vector-store bootstrap.
- License section.
- Working `pytest -q` test command.

Remaining README improvement: reduce length and move deeper V3/V4 history into docs before a polished announcement.

## Evaluation-Number Provenance Audit

V4 reliability:

- Artifact: `data/validation_general/results/v3_v4_paired_evaluation_summary.json`
- Evaluator: `src/validation/multiyear_paired_prediction.py`
- Benchmark: `georisk_multiyear_general_v1`
- Versions: V3 vs V4

V5 temporal:

- Artifact: `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_experiment_summary.json`
- Condition artifact: `data/validation_v5/recovery_applicability_ab/condition_d_recovery_applicability_gate/v5_node_repair_ab_summary.json`
- Evaluator: `src/validation/v5_node_repair_ab.py`
- Benchmark: `v4_temporal_heldout_v1`
- Versions: V4 Attempt 002 vs V5 recovery/applicability condition

All major requested public numbers are traceable.

## Public Evaluation Artifact Recommendation

Canonical public artifacts:

- `data/validation_general/results/v3_v4_paired_evaluation_summary.json`
- `data/validation_general/results/v3_v4_paired_node_comparison.csv`
- `data/validation_v4/results/attempt_002/v4_temporal_mechanism_evaluation_summary.json`
- `data/validation_v4/results/attempt_002/v4_temporal_compatible_node_funnel_summary.json`
- `data/validation_v5/recovery_applicability_ab/v5_recovery_applicability_experiment_summary.json`
- `data/validation_v5/recovery_applicability_ab/condition_d_recovery_applicability_gate/v5_node_repair_ab_summary.json`
- `data/validation_v5/recovery_applicability_ab/condition_d_recovery_applicability_gate/v5_node_repair_funnel.csv`
- `data/validation_v5/recovery_applicability_ab/condition_d_recovery_applicability_gate/v5_node_repair_mechanism_evaluation.csv`
- `data/validation_v5/recovery_applicability_ab/condition_d_recovery_applicability_gate/v5_node_repair_trajectory_review.csv`

Excluded/ignored:

- raw candidate/source dumps
- downloaded price files
- Chroma DBs and backups
- caches

Curate before staging:

- duplicate/intermediate V5 A/B directories
- large raw prediction dumps
- old validation attempts not cited by docs

## Open-Source Positioning Audit

Currently defensible:

- bounded agentic RAG
- adaptive node discovery repair
- evaluation-driven architecture
- deterministic evidence verification
- trajectory-based failure analysis
- FastAPI/Streamlit/Docker demo path
- temporal held-out evaluation
- no stock-price prediction and no investment advice

Do not claim yet:

- production-grade scale
- real-time trading
- investment prediction accuracy
- fully autonomous agent
- statistically significant general improvement
- V5 production API

## Recommended Next Task

Final release packaging: choose the exact public artifact set, stage only intended files, confirm ignored raw/price/cache directories stay out of Git, then create the public release commit.
