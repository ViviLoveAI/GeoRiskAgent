# Changelog

> **Historical development document. Some architecture details, metrics, and dataset counts reflect earlier GeoRisk versions. See `README.md` for the current frozen public release.**

Recent project changes for GeoRisk Transmission Analyzer.

## Public Release Cleanup

### Fixed

- Preserved Chroma `RetrievedCase.supply_chain_nodes` carry-through.
- Added boundary-aware rule matching in the Event Analyst.
- Added boundary-aware current-event context keyword matching.
- Clarified node qualification support versus asset-level evidence presentation.

### Changed

- Added production/report provenance versioning: V4 methodology, V4.1 production implementation.
- Kept frozen V4 evaluation artifacts unchanged and documented post-freeze production fixes separately.
- Updated the asset report to show Ranked Second-Order Exposures plus Direct Exposure References.
- Simplified custom-event input to Event plus optional Additional Context.
- Moved backend/service failures to a global service-level frontend message.

## 1. Event Analyst

### What changed

- Added support for a selectable Event Analyst mode in the pipeline: rule-based or LLM-backed.
- Kept the deterministic rule-based Event Analyst as the stable baseline and fallback.
- Added CLI support for selecting the event analyzer with `--event-analyzer rule` or `--event-analyzer llm`.

### Why it was added

- The rule-based analyzer is stable and reproducible, but hard paraphrased cases exposed limitations in semantic event classification.
- A selectable analyzer makes it possible to compare deterministic and semantic extraction without changing downstream retrieval, mapping, or evidence logic.

### Files modified

- `src/pipeline.py`
- `src/agents/event_analyst.py`
- `src/agents/event_analyzer.py`

### How to verify

```bash
PYTHONPATH=. python -m src.pipeline \
  --news "Red Sea shipping routes face disruption due to escalating regional conflict." \
  --format concise \
  --event-analyzer rule
```

## 2. LLM Integration

### What changed

- Added an optional GPT-4.1-mini Event Analyst.
- Added runtime logging for LLM mode, including API key detection, model selection, API-call attempts, fallback status, and fallback reason.
- Added safe fallback to the rule-based analyzer if the LLM path fails.

### Why it was added

- The hard evaluation set includes paraphrased and implicit geopolitical events where semantic event understanding is useful.
- Runtime logging makes it clear whether the LLM was actually used or whether the system fell back.

### Files modified

- `src/agents/llm_event_analyst.py`
- `src/config.py`
- `src/pipeline.py`
- `requirements.txt`

### How to verify

```bash
PYTHONPATH=. python -m src.pipeline \
  --news "Commercial vessels are diverting away from waters off Yemen." \
  --format concise \
  --event-analyzer llm
```

Expected observability output includes:

```text
[llm_event_analyst] OPENAI_API_KEY detected: ...
[llm_event_analyst] USE_LLM_EVENT_ANALYST: True
[llm_event_analyst] LLM event analyst model: gpt-4.1-mini
[llm_event_analyst] OpenAI API call attempted: yes
```

## 3. Schema Validation / Normalization

### What changed

- Added strict validation for LLM Event Analyst output:
  - `EventAnalysis` Pydantic schema validation
  - allowed event-type vocabulary
  - allowed supply-chain-node vocabulary
  - no invented tickers
  - no investment-advice or price-prediction language
  - required supporting phrases
  - grounding checks against the original news text
- Added normalization for `supporting_phrases` so LLM responses with string values are converted into lists before validation.

### Why it was added

- LLM output must be structured, auditable, and safe before entering the downstream pipeline.
- The normalization fix prevents valid single-phrase LLM responses from failing only because they returned a string instead of a list.

### Files modified

- `src/agents/llm_event_analyst.py`
- `scripts/test_llm_event_analyst_normalization.py`

### How to verify

```bash
PYTHONPATH=. python scripts/test_llm_event_analyst_normalization.py
```

Expected output:

```text
LLM supporting phrase normalization check passed.
```

## 4. Hard-Case Evaluation

### What changed

- Added a hard generalization evaluation set with paraphrased, ambiguous, out-of-domain, and negative non-geopolitical cases.
- Added metrics for:
  - event type accuracy
  - node recall
  - retrieval recall@1
  - retrieval recall@3
  - MRR
  - negative limited-support rate
- Added comparison mode for rule-based vs LLM Event Analyst.
- Added verbose error analysis for per-case expected vs predicted event types, nodes, supporting phrases, fallback state, and mismatch reasons.

### Why it was added

- The MVP regression set checks stable known scenarios, but it does not fully test generalization.
- Hard cases reveal whether the analyzer can handle paraphrases and whether negative examples avoid unsupported strong claims.

### Files modified

- `data/hard_evaluation_cases.json`
- `scripts/evaluate_hard_cases.py`

### How to verify

```bash
PYTHONPATH=. python scripts/evaluate_hard_cases.py --event-analyzer both
```

For detailed diagnostics:

```bash
PYTHONPATH=. python scripts/evaluate_hard_cases.py --event-analyzer llm --verbose
```

## 5. README / Documentation

### What changed

- Updated README with:
  - Event Analyst modes
  - optional GPT-4.1-mini configuration
  - hard generalization evaluation results
  - interpretation of LLM vs rule-based performance
  - current limitations
  - API key handling guidance

### Why it was added

- The project now has multiple usage and evaluation modes, so the README needed to explain how to run and interpret them.
- The documentation now better frames the project as a reusable risk knowledge-base pipeline rather than a simple RAG demo.

### Files modified

- `README.md`

### How to verify

Open `README.md` and confirm it includes:

- `Event Analyst Modes`
- `Hard Generalization Evaluation`
- `OPENAI_API_KEY`
- `USE_LLM_EVENT_ANALYST=true`
- `LLM_EVENT_ANALYST_MODEL=gpt-4.1-mini`

## 6. Knowledge Base / Seed Cases

### What changed

- Expanded the historical geopolitical knowledge base to 30 structured cases.
- Expanded asset mapping coverage for additional supply-chain nodes.
- Expanded the MVP evaluation set to 20 cases.

### Why it was added

- Broader coverage improves semantic retrieval and supports more geopolitical domains beyond the original MVP scenarios.
- The expanded evaluation set provides a larger regression baseline for exposure discovery and retrieval quality.

### Files modified

- `data/historical_cases.json`
- `data/asset_mapping.csv`
- `data/evaluation_cases.json`

### How to verify

Count historical cases:

```bash
python - <<'PY'
import json
from pathlib import Path
cases = json.loads(Path("data/historical_cases.json").read_text())
print(len(cases))
PY
```

Expected output:

```text
30
```

Run the MVP regression evaluation:

```bash
PYTHONPATH=. python scripts/evaluate_pipeline.py
```

## 7. Remaining TODOs

### What remains

- Improve supply-chain node recall, especially for second-order exposure nodes.
- Improve taxonomy alignment between historical cases, event analysis, and asset mapping.
- Add richer alias mapping for paraphrased node and event terminology.
- Compare GPT-4.1-mini with stronger models on the hard evaluation set.
- Add more human evaluation for evidence-level calibration.
- Improve UI reporting for deeper event-detail and historical-case explanations.

### Why it matters

- Event type classification improved substantially with the LLM analyzer, but node recall remains the main bottleneck.
- Better node expansion and alias mapping would improve the downstream asset watchlist without changing the core retrieval architecture.

### Files likely to change next

- `src/agents/llm_event_analyst.py`
- `src/agents/event_analyst.py`
- `src/agents/transmission_builder.py`
- `data/historical_cases.json`
- `data/asset_mapping.csv`
- `data/hard_evaluation_cases.json`

### How to verify future work

```bash
PYTHONPATH=. python scripts/evaluate_pipeline.py
PYTHONPATH=. python scripts/evaluate_hard_cases.py --event-analyzer both
```
