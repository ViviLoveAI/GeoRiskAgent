# Data Policy

GeoRisk runs from a small, auditable set of repository inputs. The public
product repository contains only data required by the application; research
experiments and generated evaluation outputs remain local.

## Public Runtime Data

The public repository contains only these runtime inputs:

- `data/historical_cases.json`: curated historical-case summaries used by retrieval;
- `data/asset_mapping.csv`: the controlled candidate-asset universe;
- `data/transmission_context_v1.json`: the transmission-context sidecar used by the product.

These files are analytical project inputs. They are not investment
recommendations and do not authorize redistribution of third-party source text
beyond the concise derived summaries already present.

## Private Research Workspace

The following categories are intentionally excluded from the public product
repository and should be regenerated or retained only in a private research
workspace:

- validation candidates, annotations, held-out sets, and prediction snapshots;
- V3, V4, and V5 experiment outputs;
- CAR, market-price, baseline, activation, and sensitivity-analysis results;
- retrieval audits, frozen experiment manifests, and intermediate diagnostics;
- raw news/source collections and provider metadata.

Any future public benchmark should be released separately with a documented
license, concise event descriptions, and source citations.

## Market Data

Downloaded prices and market-validation outputs must not be committed. They
should be regenerated privately with the user's own provider access.

## Generated Runtime State

Chroma databases, embedding models, caches, logs, and temporary files are local
runtime state and must not be committed. Rebuild the vector index from the
public historical cases with:

```bash
python -m src.vector_store_health --rebuild
```

On a clean machine, copy `.env.example` to `.env` or export
`GEORISK_LOCAL_MODEL_FILES_ONLY=false` before the first rebuild so the embedding
model can be downloaded once.
