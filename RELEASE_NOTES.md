# GeoRisk v1.0 — Public Portfolio Release

## Highlights

- First stable public portfolio release of GeoRisk Transmission Analyzer.
- Provides a structured, evidence-grounded pipeline for geopolitical event analysis, historical analog retrieval, transmission-chain construction, mechanism-aware evidence qualification, asset mapping, and watchlist reporting.
- Includes a 70-case structured historical knowledge base.
- Keeps candidate assets constrained to `data/asset_mapping.csv` and historical cases constrained to `data/historical_cases.json`.
- Preserves frozen V4 evaluation protocol and reproducible evaluation artifacts.
- Includes 2026 temporal held-out validation.
- Supports CLI, FastAPI, Streamlit, and Docker Compose interfaces.
- Documents the system as decision-support analysis, not stock-price prediction or investment advice.

## Evaluation

- Primary V3/V4 paired benchmark: 23 events and 46 `(event, node)` annotations.
- Frozen V4 improves weak-support rejection from 73.33% to 93.33% and reduces weak leakage from 26.67% to 6.67% versus the frozen V3 baseline.
- Compatible-support recall remains low at 8.00% in the paired benchmark.
- Temporal held-out validation covers 16 real 2026 events and 32 annotations.
- Temporal validation shows 100.00% weak rejection and 14.29% compatible retention, with misses concentrated in current-event node proposal and retrieval/vocabulary coverage.
- Optional CAR/SCAR artifacts provide ex-post market-response validation for a frozen legacy/V3 market snapshot; they are not V4 market predictions or trading-performance claims.

## Interfaces

- CLI: `src.pipeline`
- FastAPI: `src.api:app`
- Streamlit demo: `app.py`
- Docker Compose: API on port `8000`, Streamlit on port `8501`

## Reproducibility

- Full pytest suite verified: `236 passed`.
- Minimal rule-based CLI run verified.
- Frozen V4 Python snippet verified.
- FastAPI `/health` verified locally.
- Streamlit startup verified locally.
- Docker Compose configuration validated.
- Local ChromaDB index is generated at runtime and ignored by Git.
- Some frozen provenance artifacts intentionally preserve historical machine-local path fields because rewriting them could disturb checksum/provenance records.

## Known Limitations

- Historical case coverage is finite and curated.
- Current-event node proposal can limit recall.
- Mechanism compatibility uses structured heuristics and a context sidecar, not causal proof.
- Some frozen provenance artifacts include absolute local paths; they are retained to avoid rewriting frozen artifacts.
- `sentence-transformers/all-MiniLM-L6-v2` must be available locally because the retrieval loader uses local-only model loading.
- LLM Event Analyst mode requires an OpenAI API key and was not verified with live credentials for this release pass.
- CAR/SCAR validation is ex-post and does not imply price prediction, causality, or investment performance.

## Future Work

- Improve current-event node proposal recall.
- Improve node vocabulary and representation alignment.
- Explore mechanism-level fragment retrieval.
- Expand temporal validation coverage.
- Separate diagnostic compatible-support logic from final-retention decisions.
- Improve clean-machine model bootstrap documentation or tooling.
