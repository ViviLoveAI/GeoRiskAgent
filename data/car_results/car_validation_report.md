# CAR Validation Report

This is ex-post exposure validation, not price prediction or investment advice.
Hit detection is magnitude-based: `abs(standardized_car) >= significance_threshold`.

## Configuration

- Run timestamp: `2026-08-05T01:53:43.059299+00:00`
- Benchmark: `SPY`
- Estimation window: `[-130, -10]`
- Event window: `[-1, 1]`
- Significance threshold: `1.96`
- Event IDs: `candidate_d41a5f82d14a, candidate_355782516069, candidate_03b2368e1784, candidate_fba3f59c71da, candidate_ff6378fbb36b, candidate_130fb98e42bb, candidate_2bd2cdbf5b54, candidate_eaccce38b750, candidate_a126990eefca, candidate_4ead99ff6140`

## Summary

- Held-out events: 10
- Evaluated asset-event pairs: 147
- Skipped pairs: 1
- GeoRisk flagged hit rate: 0.08 (n=117)
- Baseline hit rate: 0.07 (n=30)
- Difference: 0.01

## Hit Rate By Evidence Label

| Group | Hit Rate | n |
| --- | ---: | ---: |
| historical_supported | 0.00 | 2 |
| inference_only | 0.00 | 3 |
| sector_proxy | 0.08 | 112 |

## Hit Rate By Event Type

| Group | Hit Rate | n |
| --- | ---: | ---: |
| critical minerals resource restrictions | 0.08 | 53 |
| cyberattack critical infrastructure | 0.07 | 81 |
| trade restrictions tariffs | 0.08 | 13 |

## Standardized CAR Distribution

| Metric | Value |
| --- | ---: |
| n | 147 |
| mean | 0.2000 |
| median | 0.1288 |
| std | 1.0415 |
| min | -2.1926 |
| max | 3.5214 |

## Price Preparation

- Reused symbols: 4
- Downloaded symbols: 0
- Failed symbols: 46
- Invalid event dates: none

## Skipped Pairs

| Event ID | Symbol | Reason |
| --- | --- | --- |
| candidate_ff6378fbb36b | SPY | asset_equals_benchmark |

