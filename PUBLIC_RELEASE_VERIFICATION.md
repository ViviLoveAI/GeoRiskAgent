# Public Release Verification

Verification date: 2026-08-15

Purpose: verify that the public-release README commands and core repository workflows are reproducible without changing benchmark results or research logic.

## Environment

- Working directory: `<repo-root>`
- Python observed from local environment: Python 3.11 Anaconda runtime
- Docker Compose available: yes, `docker compose config` succeeded
- OpenAI credentials: not present in environment during verification
- Network-dependent checks: avoided except local server probes

Observed environment warnings:

- pandas warned that local `numexpr` and `bottleneck` versions are older than pandas prefers.
- These warnings did not fail tests or CLI/API runs.

## Commands Executed

| Command | Result | Notes |
| --- | --- | --- |
| `PYTHONPATH=. pytest -q` | PASS | `236 passed, 3 warnings in 4.35s`. |
| `PYTHONPATH=. python -m src.pipeline --news "Red Sea shipping routes face disruption due to escalating regional conflict." --format concise --event-analyzer rule` | PASS | Produced a GeoRisk Transmission Report with Red Sea shipping analogs and evidence-graded watchlist output. |
| `PYTHONPATH=. python scripts/evaluate_pipeline.py` | PASS | 20 cases; event type accuracy `0.95`, node recall `0.95`, retrieval recall@3 `1.00`. With no API key, the script attempted LLM mode because `USE_LLM_EVENT_ANALYST` defaults true, then safely fell back to rule-based analysis. |
| `PYTHONPATH=. python scripts/evaluate_hard_cases.py --event-analyzer rule` | PASS | 12 cases; event type accuracy `0.33`, node recall `0.45`, retrieval recall@1 `0.65`, retrieval recall@3 `0.95`, MRR `0.90`, negative limited-support rate `1.00`. |
| `PYTHONPATH=. uvicorn src.api:app --host 127.0.0.1 --port 8000` | PASS WITH LOCAL SERVER APPROVAL | Sandbox blocked binding without approval. With approval, server started successfully. |
| `curl -s http://127.0.0.1:8000/health` | PASS WITH LOCAL REQUEST APPROVAL | Returned `{"status":"ok"}`. |
| `PYTHONPATH=. python -m streamlit run app.py --server.headless true --server.address=127.0.0.1 --server.port=8501` | PASS WITH LOCAL SERVER APPROVAL | Streamlit started and announced `http://127.0.0.1:8501`. |
| `docker compose config` | PASS | Compose file parsed successfully for API and Streamlit services. Image build was not run. |
| Frozen V4 Python snippet from README | PASS | `run_v4_pipeline(..., event_analyzer="rule")` produced a GeoRisk Transmission Report. |

## Reproducibility Notes

### ChromaDB / Sentence Transformers

The local generated Chroma index was removed during cleanup and rebuilt successfully by the CLI smoke run. This confirms that the checked-in historical KB can initialize a fresh local Chroma collection in this environment.

Important limitation: `src/vector_store.py` sets `LOCAL_MODEL_FILES_ONLY = True`. A fully clean machine needs `sentence-transformers/all-MiniLM-L6-v2` available in its local model cache before the first run, or retrieval model loading can fail. This is now documented in the README.

### ChromaDB Concurrency

Running two index-building commands in parallel against the same generated `chroma_db/` caused a transient Chroma collection error:

- `chromadb.errors.NotFoundError: Error getting collection`
- `chromadb.errors.InternalError: Missing metadata segment`

After removing `chroma_db/` and rerunning commands sequentially, the CLI and evaluation commands passed. The README documents sequential commands only. Do not run multiple first-time index builders concurrently against the same local Chroma directory.

### LLM Event Analyst

No `OPENAI_API_KEY` was present. LLM-enabled paths reported missing credentials and fell back to rule-based analysis. This is an unavailable external dependency, not a core code failure.

### Docker

`docker compose config` passed. A full `docker compose up --build` was not executed because it is heavier and may depend on Docker daemon state and dependency build/network behavior. The Compose service definitions match the documented ports:

- FastAPI: `8000`
- Streamlit: `8501`

## README Command Check

| README command area | Status |
| --- | --- |
| Installation command shape | Checked against `requirements.txt`; not run in a fresh virtualenv in this pass. |
| Minimal CLI run | PASS |
| JSON CLI run | Not separately run; same entrypoint and options as passing concise run. |
| Frozen V4 Python snippet | PASS |
| FastAPI startup | PASS with local server approval |
| FastAPI `/health` | PASS with local request approval |
| Streamlit startup | PASS with local server approval |
| Docker Compose structure | PASS via `docker compose config` |
| Pytest command | PASS |
| Basic evaluation command | PASS |
| Hard-case rule evaluation command | PASS |

## Unresolved Issues

- Some frozen artifacts contain absolute local `/Users/...` paths. They are documented in `PUBLIC_RELEASE_AUDIT.md`; changing them may alter freeze checksums/provenance.
- `ARCHITECTURE.md` and `CHANGELOG.md` contain stale development-era counts and should be treated as historical docs unless updated.
- Full Docker image build was not executed.
- Fully clean-machine model bootstrap was not verified because the local environment already had the sentence-transformer model available.
- LLM path was not tested with a live OpenAI API key.

## Verification Conclusion

The repository passes core tests, the minimal end-to-end CLI run, sequential evaluation smoke checks, FastAPI startup, Streamlit startup, and Docker Compose validation.

Recommendation: READY WITH MINOR FIXES.

## Final Polish Addendum

Final polish date: 2026-08-15

Additional cleanup performed after the initial verification pass:

- Added historical-document notices to `ARCHITECTURE.md`, `CHANGELOG.md`, and `PROJECT_SPEC.md`.
- Condensed the README CAR/SCAR section while preserving provenance and caveats.
- Added a troubleshooting note for local-only embedding model loading.
- Sanitized the non-canonical execution-diagnostic traceback in `data/validation_v4/execution_diagnostics/v4_temporal_execution_failure_diagnostics.json`.
- Preserved frozen manifest/context/protocol path fields because rewriting them could affect provenance or checksum expectations.

Security checks:

- Current-tree high-signal credential scan: no obvious live credentials found.
- Git-history high-signal credential scan over reachable commits: no obvious OpenAI keys, AWS access keys, GitHub tokens, Slack tokens, private-key blocks, bearer-token assignments, or committed `.env` files found.

Final verification commands:

| Command | Result | Notes |
| --- | --- | --- |
| `PYTHONPATH=. pytest -q` | PASS | `236 passed, 3 warnings in 7.01s`. |
| `PYTHONPATH=. python -m src.pipeline --news "Red Sea shipping routes face disruption due to escalating regional conflict." --format concise --event-analyzer rule` | PASS | Produced the expected Red Sea GeoRisk Transmission Report. |
| `docker compose config` | PASS | Compose file parsed successfully. |

Final recommendation: READY TO PUBLIC.
