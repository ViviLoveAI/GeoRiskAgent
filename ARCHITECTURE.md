# Architecture

> **Historical development document. Some architecture details, metrics, and dataset counts reflect earlier GeoRisk versions. See `README.md` for the current frozen public release.**

> **Release note:** Frozen V5 now also has a thin LangGraph orchestration adapter in `src/orchestration/langgraph_v5.py`. It wraps the existing V5 bounded repair workflow and preserves the frozen V4 verification boundary; it is not a V6 redesign.

GeoRisk Transmission Analyzer is a curated agentic RAG project for geopolitical risk exposure discovery. This document explains how the system is organized, what is implemented, and how to evaluate it.

The intended audience is a beginner full-stack / AI engineer or a technical interviewer who wants to understand the project design without reading every source file first.

## 1. Project Goal

The project analyzes geopolitical news and produces a structured risk transmission report.

Given a news headline or paragraph, the system:

1. Classifies the geopolitical event.
2. Identifies affected regions, industries, and supply-chain nodes.
3. Retrieves historically similar geopolitical cases.
4. Builds a qualitative transmission chain.
5. Maps affected supply-chain nodes to candidate public assets from a curated CSV.
6. Grades the evidence behind each mapped candidate.
7. Generates a risk watchlist report.

The project is designed for exposure discovery and decision-support analysis. It does not forecast prices, recommend trades, or provide investment advice.

## 2. Main Pipeline Flow

```text
News Input
  -> Event Analyst
  -> Historical Case Retrieval
  -> Transmission Chain Builder
  -> Market Mapping
  -> Evidence Grading
  -> Asset Relevance Ranking
  -> Report Generation
  -> CLI / Streamlit UI / FastAPI
```

The main orchestration layer is `src/pipeline.py`.

At a high level:

```python
event = analyze_event(news_text)
retrieved_cases = retrieve_cases(news_text, event)
transmission_chain = build_transmission_chain(event, retrieved_cases)
candidate_assets = map_assets(event, transmission_chain)
evidence_results = grade_evidence(event, candidate_assets, retrieved_cases, transmission_chain)
report = generate_report(event, retrieved_cases, transmission_chain, evidence_results)
```

## 3. Components

### Curated Seed Knowledge Base

The system uses local structured data rather than live market or news feeds.

Key files:

- `data/historical_cases.json`
- `data/asset_mapping.csv`
- `data/evaluation_cases.json`
- `data/hard_evaluation_cases.json`

`historical_cases.json` contains 30 curated geopolitical risk cases. Each case includes event metadata, regions, industries, supply-chain nodes, a summary, transmission-chain notes, affected asset types, and retrieval text.

`asset_mapping.csv` maps normalized supply-chain nodes to candidate public stocks, ADRs, and ETFs. Candidate assets are always selected from this file; the system should not invent tickers.

### Event Analyst

The Event Analyst converts raw news text into a structured `EventAnalysis` object.

It extracts:

- title
- summary
- event type
- regions
- industries
- supply-chain nodes
- shock direction
- risk factors

The project supports two Event Analyst modes:

- rule-based analyzer
- optional LLM analyzer

### Rule-Based Analyzer

File:

- `src/agents/event_analyst.py`

The rule-based analyzer uses deterministic keyword rules. It is the stable baseline and requires no API key.

Strengths:

- reproducible
- easy to inspect
- useful for regression tests
- safe fallback when LLM analysis fails

Limitations:

- struggles with paraphrased or indirect geopolitical language
- may miss implied event types
- conservative supply-chain node recall

### LLM Analyzer

File:

- `src/agents/llm_event_analyst.py`

The optional LLM Event Analyst uses GPT-4.1-mini to produce a candidate `EventAnalysis` JSON object.

It is designed to improve semantic event classification on hard cases such as paraphrased, indirect, or implicit geopolitical events.

The LLM analyzer is guarded by validation and fallback logic. If anything fails, the system falls back to the rule-based analyzer.

Runtime configuration:

```bash
OPENAI_API_KEY=...
USE_LLM_EVENT_ANALYST=true
LLM_EVENT_ANALYST_MODEL=gpt-4.1-mini
```

These values should be stored in `.env` or the shell environment and never committed.

### Schema Validation / Normalization

Core schemas live in:

- `src/schemas.py`

The LLM Event Analyst validates output using:

- Pydantic `EventAnalysis`
- allowed event-type vocabulary
- allowed supply-chain-node vocabulary
- required supporting phrases
- grounding checks against the original news text
- ticker leakage checks
- filters against investment-advice or price-prediction language

The analyzer also normalizes `supporting_phrases` before validation. This matters because LLMs may return:

```json
{
  "supporting_phrases": {
    "event_type": "shipping disruption",
    "supply_chain_nodes": "commercial vessels"
  }
}
```

The system converts those strings into lists:

```json
{
  "supporting_phrases": {
    "event_type": ["shipping disruption"],
    "supply_chain_nodes": ["commercial vessels"]
  }
}
```

This keeps validation strict without rejecting otherwise usable LLM responses.

### Retrieval / Historical Analogs

Files:

- `src/vector_store.py`
- `src/agents/case_retriever.py`

Historical cases are embedded using `sentence-transformers` with the `all-MiniLM-L6-v2` model. ChromaDB stores the persistent vector index under `chroma_db/`.

The retrieval agent builds a semantic query from:

- raw news text
- event type
- regions
- industries
- supply-chain nodes
- shock direction

It returns the top matching historical cases as `RetrievedCase` objects.

### Transmission Chain Builder

File:

- `src/agents/transmission_builder.py`

This component builds a qualitative risk transmission path using the analyzed event and retrieved historical analogs.

It does not forecast price movement. It describes potential channels such as shipping disruption, energy-flow constraints, export controls, or logistics bottlenecks.

### Market Mapping

File:

- `src/agents/market_mapper.py`

The market mapper matches normalized supply-chain nodes against `data/asset_mapping.csv`.

It returns candidate assets as risk exposure candidates, not trading signals.

### Evidence Grading

File:

- `src/agents/evidence_agent.py`

The evidence agent assigns one of three evidence levels:

- `historical_supported`
- `sector_proxy`
- `inference_only`

Confidence scores represent evidence strength, not probability of price movement.

### Asset Relevance Ranking

File:

- `src/agents/asset_ranker.py`

The ranker adds deterministic analyst-priority metadata after evidence grading.
It ranks only second-order exposures using a fixed lexicographic key. First-order
exposures are preserved as a direct-exposure reference list. The ranker
does not filter candidates and does not reinterpret evidence confidence as
market-movement probability.

### Report Generation

Files:

- `src/agents/report_agent.py`
- `src/report_formatter.py`

The report agent creates a structured `FinalReport`. The formatter turns it into a concise markdown report for CLI and UI use.

### Hard-Case Evaluation

Files:

- `scripts/evaluate_pipeline.py`
- `scripts/evaluate_hard_cases.py`
- `data/evaluation_cases.json`
- `data/hard_evaluation_cases.json`

The project has two evaluation tracks:

1. MVP regression evaluation
2. hard generalization evaluation

The MVP regression set checks known scenario behavior.

The hard set includes:

- paraphrased geopolitical events
- ambiguous maritime-energy cases
- out-of-domain examples
- negative non-geopolitical examples

Hard-case metrics include:

- event type accuracy
- node recall
- retrieval recall@1
- retrieval recall@3
- MRR
- negative limited-support rate

### API / Frontend

The project includes three usage modes.

CLI:

- `src/pipeline.py`

Streamlit UI:

- `app.py`

FastAPI backend:

- `src/api.py`

The Streamlit app provides an interactive event dashboard and report page. The FastAPI backend exposes the pipeline for external clients or future frontend integration.

## 4. What Is Currently Implemented

Implemented today:

- 30 curated historical geopolitical risk cases
- normalized supply-chain node vocabulary
- asset mapping from supply-chain nodes to public stocks, ADRs, and ETFs
- rule-based Event Analyst
- optional GPT-4.1-mini Event Analyst
- LLM schema validation and fallback
- supporting-phrase normalization
- ChromaDB semantic retrieval over historical cases
- transmission-chain builder
- market mapper
- evidence grader
- structured final report
- concise markdown report formatter
- CLI execution
- Streamlit dashboard
- FastAPI backend
- MVP regression evaluation
- hard generalization evaluation
- verbose hard-case error analysis

## 5. What Is Not Implemented

Not currently implemented:

- real-time news ingestion
- live market data ingestion
- price forecasting
- trade recommendation logic
- autonomous web research
- dynamic ticker discovery
- automated portfolio construction
- probabilistic event-impact modeling
- full human-in-the-loop labeling UI
- production authentication or deployment hardening

The system intentionally avoids price and return prediction. Candidate assets are risk watchlist items only.

## 6. Why the Project Is Curated / Offline

The project uses curated local data because the goal is controlled exposure reasoning, not real-time market automation.

This design makes the system:

- auditable: every historical case and asset mapping can be inspected
- reproducible: evaluation results are stable across runs
- safer: the system cannot invent tickers or silently rely on unverified external data
- interview-friendly: reviewers can trace how a news item becomes a report
- evaluation-ready: expected event types, nodes, and historical analogs can be manually labeled

A dynamic real-time version could be built later, but it would need additional safeguards:

- source-quality filters
- deduplication
- event clustering
- human review workflows
- data freshness tracking
- stronger evaluation around false positives

## 7. How to Run the Main Evaluation Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the MVP regression evaluation:

```bash
PYTHONPATH=. python scripts/evaluate_pipeline.py
```

Run the hard generalization evaluation for both analyzers:

```bash
PYTHONPATH=. python scripts/evaluate_hard_cases.py --event-analyzer both
```

Run verbose hard-case analysis:

```bash
PYTHONPATH=. python scripts/evaluate_hard_cases.py --event-analyzer llm --verbose
```

Run the CLI in rule mode:

```bash
PYTHONPATH=. python -m src.pipeline \
  --news "Red Sea shipping routes face disruption due to escalating regional conflict." \
  --format concise \
  --event-analyzer rule
```

Run the CLI in LLM mode:

```bash
PYTHONPATH=. python -m src.pipeline \
  --news "Commercial vessels are diverting away from waters off Yemen." \
  --format concise \
  --event-analyzer llm
```

Run the Streamlit UI:

```bash
PYTHONPATH=. python -m streamlit run app.py
```

Run the FastAPI backend:

```bash
PYTHONPATH=. uvicorn src.api:app --reload
```
