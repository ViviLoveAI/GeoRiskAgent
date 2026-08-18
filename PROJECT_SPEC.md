# Project Specification

> **Historical development document. Some architecture details, metrics, and dataset counts reflect earlier GeoRisk versions. See `README.md` for the current frozen public release.**

## Purpose

GeoRisk Transmission Analyzer will help examine potential transmission channels
from geopolitical risk events to mapped assets using local, auditable data.

## Non-Goals

- The project does not predict stock prices.
- The project does not provide investment advice.
- The project does not recommend buying, selling, or holding securities.

## Required Data Sources

- Candidate assets: `data/asset_mapping.csv`
- Historical cases: `data/historical_cases.json`

Future implementations must preserve these source-of-truth constraints.

## Preferred Architecture

- Simple Python functions for pipeline steps.
- Pydantic models for structured inputs and outputs.
- Minimal dependencies.
- No complex agent framework unless a later requirement clearly justifies it.

## Initial Modules

- `src/config.py`: project paths and runtime settings.
- `src/schemas.py`: Pydantic models.
- `src/pipeline.py`: high-level analysis orchestration placeholders.
- `src/vector_store.py`: historical-case indexing and retrieval placeholders.
- `src/agents/`: simple coordination helpers for future agent-style workflows.
