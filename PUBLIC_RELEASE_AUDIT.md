# Public Release Audit

Audit date: 2026-08-15

Scope: freeze the current GeoRisk repository for a public GitHub portfolio release without changing research behavior, benchmarks, labels, prompts, thresholds, retrieval depth, CAR windows, or historical data.

## Executive Summary

GeoRisk is releaseable as an evidence-grounded geopolitical risk transmission analysis project, but the public release needs careful framing. The repository contains a stable runtime pipeline, V3/V4 freeze artifacts, temporal validation artifacts, CAR validation artifacts, tests, FastAPI, Streamlit, and Docker support. It also contains many development experiments and generated local caches that should be either documented or ignored.

Recommended release stance:

- KEEP the runtime code, canonical data, tests, evaluation artifacts, and validation scripts.
- KEEP BUT DOCUMENT the many V3/V4 and market-validation artifacts as a hierarchy rather than presenting every artifact as equally important.
- REMOVE BEFORE PUBLIC RELEASE local caches (`__pycache__`, `.pytest_cache`, `.DS_Store`, `chroma_db/`) from the working tree.
- GITIGNORE local caches, environment files, logs, IDE files, and local model/cache directories.
- KEEP BUT DOCUMENT stale historical docs (`ARCHITECTURE.md`, `CHANGELOG.md`, `PROJECT_SPEC.md`) or update them later; they contain development history and some stale counts.
- DO NOT alter benchmark outputs or tune model behavior.

## 1. Repository Structure

### Core Production / Runtime Code

| Path | Role | Recommendation |
| --- | --- | --- |
| `src/pipeline.py` | Main orchestration; includes legacy/default, frozen V3, and frozen V4 entrypoints. | KEEP |
| `src/api.py` | FastAPI service. | KEEP |
| `app.py` | Streamlit demo UI. | KEEP |
| `src/schemas.py` | Pydantic data models. | KEEP |
| `src/config.py` | Project paths and runtime environment flags. | KEEP |
| `src/vector_store.py` | ChromaDB + sentence-transformer retrieval over `data/historical_cases.json`. | KEEP |
| `src/agents/` | Event analysis, retrieval, transmission, mapping, evidence grading, ranking, report generation. | KEEP |
| `src/mechanism_context.py` | Mechanism compatibility and canonical-family logic. | KEEP |
| `src/transmission_context_store.py` | Loads `transmission_context_v1`. | KEEP |
| `src/v3_config.py`, `src/v4_config.py` | Frozen configuration invariants. | KEEP |
| `Dockerfile`, `docker-compose.yml` | API and Streamlit container support. | KEEP |

### Evaluation / Validation Code

| Path | Role | Recommendation |
| --- | --- | --- |
| `src/validation/` | Validation and benchmark implementation modules. | KEEP BUT DOCUMENT |
| `src/eval/car/` | CAR validation implementation. | KEEP BUT DOCUMENT |
| `scripts/evaluate_pipeline.py`, `scripts/evaluate_hard_cases.py` | Basic and hard-case evaluation scripts. | KEEP |
| `scripts/build_v3_frozen_baseline.py`, `scripts/run_multiyear_paired_predictions.py`, `scripts/seal_multiyear_general_benchmark.py` | Multi-year freeze/evaluation workflow. | KEEP BUT DOCUMENT |
| `scripts/run_v4_temporal_predictions.py`, `scripts/run_v4_temporal_attempt_002.py`, `scripts/seal_v4_temporal_heldout.py` | V4 temporal held-out workflow. | KEEP BUT DOCUMENT |
| `scripts/run_car_validation_v3.py`, `scripts/run_broad_random_baseline.py`, `scripts/run_scar_continuous_test.py`, `scripts/run_curated_activation_test.py` | Optional downstream CAR validation workflow. | KEEP BUT DOCUMENT |
| `scripts/audit_*`, `scripts/review_*`, `scripts/prototype_mechanism_compatible_support.py` | Diagnostic/development analyses. | KEEP BUT DOCUMENT or ARCHIVE under a future `research/` hierarchy |

### Tests

| Path | Role | Recommendation |
| --- | --- | --- |
| `tests/` | Pytest suite for runtime, validation, CAR, freeze invariants, and diagnostics. | KEEP |
| `scripts/test_*.py` | Older script-style smoke tests. | KEEP BUT DOCUMENT; consider moving into `tests/` later |

### Benchmark / Knowledge-Base Data

| Path | Role | Recommendation |
| --- | --- | --- |
| `data/historical_cases.json` | Historical case KB; current count: 70 cases. | KEEP |
| `data/asset_mapping.csv` | Only allowed candidate asset source; current count: 82 rows, 78 unique tickers. | KEEP |
| `data/transmission_context_v1.json` | V4 node-level historical context sidecar. | KEEP |
| `data/evaluation_cases.json` | Basic evaluation cases; current count: 20. | KEEP |
| `data/hard_evaluation_cases.json` | Hard/paraphrased evaluation cases; current count: 12. | KEEP |
| `data/validation_general/` | Multi-year V3/V4 benchmark and paired results. | KEEP BUT DOCUMENT as primary V3/V4 evidence benchmark |
| `data/validation_v4/` | 2026 temporal held-out protocol, predictions, and results. | KEEP BUT DOCUMENT as temporal validation |
| `data/topk_sensitivity_v4/` | V4 freeze, top-k sensitivity, mechanism compatibility, and diagnostic artifacts. | KEEP BUT DOCUMENT as ablations/diagnostics |
| `data/market_validation/`, `data/car_results_v3/`, `data/eval/` | CAR/SCAR downstream validation artifacts. | KEEP BUT DOCUMENT as optional ex-post validation |

### Generated Outputs / Temporary Experiments

| Path | Role | Recommendation |
| --- | --- | --- |
| `data/validation_snapshots/` | Earlier candidate snapshots, including duplicate `_v2` files and placeholders. | ARCHIVE or KEEP BUT DOCUMENT |
| `data/validation_candidates/`, `data/validation_v3/candidates/` | Raw candidate collection artifacts. | KEEP BUT DOCUMENT; raw GDELT URLs may be noisy |
| `data/validation_selection/` | Validation event-selection audit artifacts. | KEEP BUT DOCUMENT |
| `data/baseline_v3/`, `data/analysis_v3/` | V3 baseline and analysis artifacts. | KEEP BUT DOCUMENT |
| `data/prices/` | Local price CSVs used by CAR validation. | KEEP BUT DOCUMENT; not used by basic runtime |
| `data/market_validation/broad_random/prices/` | Many local broad-universe price CSVs. | KEEP BUT DOCUMENT if reproducing market validation; otherwise consider external archive later |

### Obsolete / Duplicated / Local-Only

| Path | Issue | Recommendation |
| --- | --- | --- |
| `ARCHITECTURE.md` | Stale knowledge-base count: says 30 historical cases; current file has 70. Some language describes earlier project state. | KEEP BUT DOCUMENT or update before final public release |
| `CHANGELOG.md` | Development log references earlier 30-case state and older README updates. | KEEP BUT DOCUMENT as development history |
| `PROJECT_SPEC.md` | Initial-project spec, not full current architecture. | KEEP BUT DOCUMENT as project constraints |
| `data/validation_v4/predictions/` and `data/validation_v4/predictions/attempt_002/` | Similar temporal prediction artifacts; `attempt_002` appears canonical after execution-fix diagnostics. | KEEP BUT DOCUMENT; README should cite `attempt_002` for current temporal findings |
| `data/validation_snapshots/*_snapshot.json` and `*_snapshot_v2.json` | Duplicate historical candidate snapshots. | ARCHIVE later if reducing clutter |
| `assets/assets:red_sea_report.png`, `assets/assets:semiconductor_report.png` | Filenames contain colon-like path text and may look accidental. | MOVE / REORGANIZE later or KEEP BUT DOCUMENT |

### Caches / Model Artifacts / Development Artifacts

| Path | Issue | Recommendation |
| --- | --- | --- |
| `chroma_db/` | Generated local ChromaDB vector index. | GITIGNORE and REMOVE BEFORE PUBLIC RELEASE |
| `__pycache__/`, `src/**/__pycache__/`, `scripts/__pycache__/`, `tests/__pycache__/` | Python bytecode caches. | GITIGNORE and REMOVE BEFORE PUBLIC RELEASE |
| `.pytest_cache/` | Pytest cache. | GITIGNORE and REMOVE BEFORE PUBLIC RELEASE |
| `.DS_Store`, `data/.DS_Store`, `src/.DS_Store` | macOS metadata. | GITIGNORE and REMOVE BEFORE PUBLIC RELEASE |
| Local Hugging Face / transformer model caches | Not found in repo, but relevant to reproducibility. | GITIGNORE if created locally |

## 2. Security and Privacy Audit

Searches performed:

- Secret patterns: OpenAI keys, AWS access keys, private keys, GitHub tokens, Slack tokens, bearer tokens.
- Environment files and credential-named files.
- Absolute local paths and network/IP references.

Findings:

| Location | Finding | Risk | Recommendation |
| --- | --- | --- | --- |
| `README.md`, `ARCHITECTURE.md`, `EC2_DEPLOYMENT.md` | `OPENAI_API_KEY=...` placeholder only. | Low. | KEEP; placeholders are safe. |
| `src/agents/llm_event_analyst.py` | Logs whether `OPENAI_API_KEY` is detected, not the value. | Low. | KEEP. |
| `data/topk_sensitivity_v4/v4_freeze_candidate_manifest.json` | Absolute local path `<local-user>/Documents/.../data/transmission_context_v1.json`. | Privacy/polish issue. | KEEP BUT DOCUMENT or normalize in a later non-behavioral artifact cleanup. |
| `data/topk_sensitivity_v4/v4_freeze_checksums.json` | Absolute local path key. | Privacy/polish issue. | KEEP BUT DOCUMENT or normalize later. |
| `data/transmission_context_v1.json` | `source_historical_cases_path` contains absolute local `/Users/...` path. | Privacy/polish issue. | KEEP BUT DOCUMENT; changing it would alter frozen artifact checksum. |
| `data/topk_sensitivity_v4/v4_final_freeze_manifest.json` | Absolute local path fields. | Privacy/polish issue. | KEEP BUT DOCUMENT; changing it would alter frozen artifact checksum. |
| `data/validation_v4/V4_HELDOUT_VALIDATION_PROTOCOL.md` | Absolute local historical context sidecar path. | Privacy/polish issue. | KEEP BUT DOCUMENT; safe to update later if checksum expectations allow. |
| `data/validation_v4/execution_diagnostics/v4_temporal_execution_failure_diagnostics.json` | Non-canonical execution diagnostic originally included a full local traceback. | Privacy/polish issue resolved in final polish. | Sanitized traceback text while preserving diagnostic conclusion. |
| `data/validation_v4/v4_heldout_protocol_manifest.json` | Absolute local path field. | Privacy/polish issue. | KEEP BUT DOCUMENT. |
| Raw validation candidate JSON/CSV files | Public URLs from GDELT/news sources. | Low to medium clutter risk, not credential risk. | KEEP BUT DOCUMENT or archive raw collection artifacts. |

No live API keys, AWS credentials, GitHub tokens, private keys, `.env` files, or credential files were found in the working tree. Because no actual credentials were found, credential rotation is not indicated from this audit. If any credential-like value was committed in prior Git history, rotate it before public release; this audit only inspected the current checkout, not full history.

False positives:

- URL substrings containing `sk-` in public article image paths matched the generic OpenAI-key regex; these are not API keys.
- Many occurrences of `token` are ordinary code variable names.

## 3. README Accuracy Audit

Current README is closer to the frozen public story than the older architecture docs, but it is too long for a portfolio README and mixes primary evaluation with optional market validation.

Verified current counts:

- `data/historical_cases.json`: 70 cases.
- `data/asset_mapping.csv`: 82 rows, 78 unique non-empty tickers.
- `data/evaluation_cases.json`: 20 cases.
- `data/hard_evaluation_cases.json`: 12 cases.

README claims that appear supported:

- V4 top-k is 10 in `src/v4_config.py`.
- V3 top-k is 3 in `src/v3_config.py`.
- Mechanism-compatible support threshold is 2 via `MIN_CASE_SUPPORT_FOR_SECOND_ORDER`.
- Multi-year benchmark metrics match `data/validation_general/results/v3_v4_paired_evaluation_summary.json`.
- 2026 temporal metrics match `data/validation_v4/results/attempt_002/v4_temporal_mechanism_evaluation_summary.json`.
- Temporal funnel metrics match `data/validation_v4/results/attempt_002/v4_temporal_compatible_node_funnel_summary.json`.
- CAR/SCAR market validation metrics match `data/market_validation/broad_random/broad_random_summary.json`, `data/market_validation/scar_continuous_test/continuous_scar_summary.json`, and `data/market_validation/curated_activation/activation_summary.json`.
- CLI, FastAPI, Streamlit, and Docker command shapes match repository entrypoints.

README issues to fix:

- It is lengthy and reads partly like an internal research memo.
- It should more clearly distinguish:
  - frozen/current V4 evaluation,
  - V3 baseline comparison,
  - temporal held-out validation,
  - optional downstream CAR validation using legacy/V3 market snapshots.
- It should explicitly label the API and Streamlit paths as legacy/default `run_pipeline(top_k=3)` paths unless they are changed.
- It should avoid presenting external market validation as the main project result.
- It should include a source-artifact note for each metric table.
- It should document that the local sentence-transformer model may need to be available in the Hugging Face cache because `src/vector_store.py` uses `local_files_only=True`.

Other documentation accuracy issues:

- `ARCHITECTURE.md` says `historical_cases.json` contains 30 cases; current count is 70.
- `CHANGELOG.md` describes an earlier 30-case expansion; this is fine as development history but stale as current-state documentation.
- `PROJECT_SPEC.md` is an initial spec, not a current architecture description.

## 4. Evaluation Artifact Audit

Recommended public hierarchy:

### Primary Evaluation

| Artifact | Meaning | Recommendation |
| --- | --- | --- |
| `data/validation_general/results/v3_v4_paired_evaluation_summary.json` | Primary paired V3/V4 mechanism-support benchmark. | KEEP; cite in README |
| `data/validation_general/multiyear_general_benchmark_manifest.json` | Multi-year benchmark manifest. | KEEP; cite as benchmark provenance |
| `data/validation_general/predictions/v3/`, `data/validation_general/predictions/v4/` | Frozen paired prediction snapshots. | KEEP |

### Ablations / Diagnostics

| Artifact | Meaning | Recommendation |
| --- | --- | --- |
| `data/topk_sensitivity_v4/topk_sensitivity_summary.json` | Retrieval-depth/top-k sensitivity. | KEEP; cite selectively |
| `data/topk_sensitivity_v4/retrieval_guardrail_ablation_summary.json` | k=10 guardrail impact and broad-node removal. | KEEP; cite selectively |
| `data/topk_sensitivity_v4/mechanism_compatible_support_summary.json` | Mechanism compatibility diagnostic. | KEEP BUT DOCUMENT |
| `data/topk_sensitivity_v4/broad_node_ablation_summary.json` | Broad node noise analysis. | KEEP BUT DOCUMENT |
| `data/topk_sensitivity_v4/context_coverage_audit_summary.json` | TransmissionContext coverage. | KEEP BUT DOCUMENT |

### Temporal Validation

| Artifact | Meaning | Recommendation |
| --- | --- | --- |
| `data/validation_v4/v4_temporal_heldout_manifest.json` | Held-out benchmark manifest. | KEEP; cite |
| `data/validation_v4/temporal_final_heldout_events.csv` | 2026 held-out events. | KEEP |
| `data/validation_v4/temporal_heldout_ground_truth.csv` | Held-out annotations. | KEEP |
| `data/validation_v4/predictions/attempt_002/` | Canonical temporal predictions after execution fix. | KEEP; cite as frozen/current temporal predictions |
| `data/validation_v4/results/attempt_002/` | Canonical temporal mechanism evaluation and funnel. | KEEP; cite |
| `data/validation_v4/execution_diagnostics/` | Attempt-001 failure and execution-fix diagnostics. | KEEP BUT DOCUMENT or ARCHIVE |

### Optional Downstream Market Validation

| Artifact | Meaning | Recommendation |
| --- | --- | --- |
| `data/car_results_v3/car_pair_results.csv` | Frozen legacy/V3 CAR pair results. | KEEP; cite |
| `data/car_results_v3/v3_car_report.md` | CAR report. | KEEP BUT DOCUMENT |
| `data/market_validation/broad_random/broad_random_summary.json` | Broad-market random baseline. | KEEP; cite |
| `data/market_validation/scar_continuous_test/continuous_scar_summary.json` | Continuous SCAR analysis. | KEEP; cite |
| `data/market_validation/curated_activation/activation_summary.json` | Activated vs non-activated curated-pool test. | KEEP; cite |
| `data/market_validation/curated_filtering/` | Selected/rejected filter test; current frozen path has no explicit rejection stage. | KEEP BUT DOCUMENT as diagnostic/negative result |

### Obsolete or Development Experiments

Do not remove without a separate archival decision:

- `data/validation_snapshots/`
- `data/validation_candidates/`
- `data/validation_selection/`
- `data/baseline_v3/`
- `data/analysis_v3/`
- `data/car_results/` if superseded by `data/car_results_v3/`
- `data/validation_v4/predictions/` root-level files if `attempt_002` is canonical

## 5. Reproducibility Audit

### Python / Dependencies

- Docker uses Python 3.11.
- Local bytecode indicates Python 3.11 was used.
- `requirements.txt` includes runtime packages: `pydantic`, `python-dotenv`, `sentence-transformers`, `chromadb`, `pandas`, `streamlit`, `fastapi`, `uvicorn`, `openai`.
- `pytest` is required for tests but is not in `requirements.txt`.
- CAR price-fetching code may require `yfinance`; verify whether this is optional/import-guarded before documenting external price-download reproduction.

### Environment Variables

- Optional:
  - `OPENAI_API_KEY`
  - `USE_LLM_EVENT_ANALYST`
  - `LLM_EVENT_ANALYST_MODEL`
  - `USE_MECHANISM_COMPATIBLE_SUPPORT`
- Basic rule-based runs should not require API keys.
- LLM mode falls back to rule-based analysis if unavailable.

### Chroma / Vector DB

- `src/vector_store.py` creates `chroma_db/` at runtime.
- `LOCAL_MODEL_FILES_ONLY = True` means the sentence-transformer model must already exist in the local Hugging Face cache. A clean clone on a new machine may fail until the model is downloaded or that flag is changed/documented.
- `chroma_db/` should not be committed; it is a generated index.

### Startup / Runtime

- CLI path exists: `PYTHONPATH=. python -m src.pipeline --news ... --format concise --event-analyzer rule`.
- FastAPI path exists: `PYTHONPATH=. uvicorn src.api:app --reload`; docs at `http://127.0.0.1:8000/docs`.
- Streamlit path exists: `PYTHONPATH=. python -m streamlit run app.py`.
- Docker Compose defines API on 8000 and Streamlit on 8501.

### Tests / Evaluation Commands

Likely commands to verify:

- `PYTHONPATH=. pytest -q`
- `PYTHONPATH=. python -m src.pipeline --news "Red Sea shipping routes face disruption due to escalating regional conflict." --format concise --event-analyzer rule`
- `PYTHONPATH=. python scripts/evaluate_pipeline.py`
- `PYTHONPATH=. python scripts/evaluate_hard_cases.py --event-analyzer rule`
- `PYTHONPATH=. uvicorn src.api:app --host 127.0.0.1 --port 8000`
- `PYTHONPATH=. python -m streamlit run app.py --server.headless true`

Known reproducibility risk: the sentence-transformer model may not be downloadable in restricted/offline environments because the code forces local-only loading.

## 6. Public-Release Risks

| Risk | Severity | Recommendation |
| --- | --- | --- |
| Local caches are present in the working tree. | Medium | Remove and gitignore. |
| Absolute `/Users/...` paths in frozen artifacts. | Medium | Document now; normalize only if preserving checksums is not required. |
| README and older docs mix V3/V4/V5 history with current release facts. | Medium | Rewrite README around frozen current version; label V5 as future work only. |
| `ARCHITECTURE.md` stale count says 30 historical cases. | Medium | Update later or mark as development history. |
| Many evaluation artifacts are presented at the same directory level. | Medium | Use README hierarchy: primary evaluation, diagnostics, temporal validation, optional CAR validation. |
| `requirements.txt` lacks `pytest` for tests. | Medium | Add test dependency or document `pip install pytest`. |
| Local-only sentence-transformer loading may fail on new machines. | High for clean-clone reproducibility | Document clearly; consider adding a separate bootstrap note if public users report failures. |
| `data/market_validation/broad_random/prices/` is many CSVs and can distract. | Low to medium | Keep for reproducibility, but document as optional downstream validation data. |
| `EC2_DEPLOYMENT.md` may imply live deployment readiness. | Low | Keep, but README should present it as optional demo deployment. |
| `data/validation_v4/execution_diagnostics/*` contains full tracebacks and local paths. | Low to medium | Archive or keep documented as diagnostics. |

## Recommended Phase-2 Actions

1. Remove generated local caches and OS files.
2. Expand `.gitignore` for public-release hygiene.
3. Rewrite `README.md` into a concise public technical README with metric provenance.
4. Add `PUBLIC_RELEASE_VERIFICATION.md` after verification commands.
5. Add `RELEASE_NOTES.md`.
6. Avoid deleting or rewriting evaluation artifacts unless a separate archival plan is approved.
