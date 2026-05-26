# Agent Guidelines

These guidelines apply to future AI-assisted work in this repository.

## Core Constraints

- Do not build features that predict stock prices.
- Do not produce investment advice.
- Load candidate assets only from `data/asset_mapping.csv`.
- Load historical cases only from `data/historical_cases.json`.
- Prefer simple Python functions and Pydantic models over complex agent
  frameworks.

## Implementation Style

- Keep modules small and explicit.
- Add docstrings to public functions and models.
- Make data provenance visible in function names and documentation.
- Treat outputs as analytical explanations, not financial recommendations.

## Future Agent Design

If agent-like behavior is needed, implement it as plain Python orchestration
functions under `src/agents/`. Avoid adopting a large framework unless the
project requirements change.
