# GeoRisk Asset Relevance Ranking v1

Ranking version: `ranking_v1`

This spec freezes the first GeoRisk ranking layer for later validation. Ranking
is a **relative review-priority order** over assets GeoRisk already discovered.
It is not a price prediction, not a probability of market movement, and not
investment advice.

## Placement

```text
Event Analyst -> Historical Case Retrieval -> Transmission Builder
-> Market Mapper -> Evidence Agent -> Asset Relevance Ranker -> Report Agent
```

The ranker never removes candidates and never changes `evidence_level`,
`confidence`, `transmission_order`, `linkage_tier`, `linkage_rationale`, or
`supporting_case_ids`.

## Scope

Ranking v1 applies **only to second-order exposures**. First-order exposures are
**not ranked** and are **excluded from Top-K**; they are preserved as a separate
direct-exposure reference list.

- **Why only second-order:** first-order assets are named directly by the event
  and need no transmission reasoning; ranking them together would let their
  directness dominate Top-K and bury the system's actual differentiator
  (second-order discovery).
- **Why keep first-order:** it is the control for measuring second-order
  increment. GeoRisk's claim, surfacing reactive exposures a node-only lookup
  misses, is only testable against a preserved first-order baseline.
- **First-order presentation:** listed in descending `evidence_level` for
  readability only. It is not ranked for Top-K and does not enter any V4 Top-K
  metric.

## Ranking Method

Ranking v1 is **rank-based, not score-based**. Second-order exposures are sorted
by a fixed lexicographic key, compared in order; an earlier key decides, and
later keys only break ties. There are no tunable weights and no 0-100 composite
score.

| priority | key | direction | source |
| ---: | --- | --- | --- |
| 1 | `evidence_level` | historical_supported > sector_proxy > inference_only | Evidence Agent |
| 2 | independent supporting-case count, saturated at 3 | more first | `supporting_case_ids` |
| 3 | retrieval support = mean `1 / retrieval_rank` of supporting cases | higher first | retrieved-case order |
| 4 | `symbol` | alphabetical | tiebreak only |

Key 1 is the main ranking signal. Keys 2 and 3 are neutral evidence-strength
proxies. Key 4 exists solely so the order is reproducible.

## Signals Deliberately Excluded

- **`linkage_tier`**: excluded from the ranking key. It remains display
  metadata only.
- **`transmission_order`**: excluded from the ranking key. Every ranked exposure
  is second-order, so it carries no within-group information.
- **Raw retrieval distance**: not used for ranking. ChromaDB distances are
  backend-specific and not comparable across runs; only retrieved rank is used.

## Priority Tiers

Tier maps directly from `evidence_level`, so no unsupported score threshold is
introduced:

| evidence_level | tier |
| --- | --- |
| historical_supported | `high_priority` |
| sector_proxy | `medium_priority` |
| inference_only | `exploratory` |

First-order reference exposures are tagged `reference`. All candidates remain
in output regardless of tier.

## Output Fields

The ranker adds:

- `ranking_version`
- `ranking_scope`: `ranked_second_order` or `reference_first_order`
- `rank_within_order`
- `priority_tier`
- `ranking_key`
- `supporting_case_count`
- `supporting_case_details`
- `ranking_rationale`

## Pre-Registration Discipline

This ranking rule uses only ex-ante pipeline features: no CAR, SCAR, return, or
hit information. It is frozen here for evaluation on a fresh V4 held-out event
set.

## Future V4 Metrics

- Hit Rate @ Top 3
- Hit Rate @ Top 5
- Hit Rate @ Top 10
- mean and median absolute standardized CAR @ Top-K
- event Hit@K
- second-order Top-K
- lift versus matched-random Top-K controls

Learned or weighted ranking is deferred until a larger event set can validate
the relative value of each signal.
