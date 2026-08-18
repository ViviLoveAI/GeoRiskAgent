# V3 Pre-CAR Validation Design Report

This report covers event selection and prediction freezing only. It does not inspect prices, returns, CAR, standardized CAR, hit labels, or baseline performance.

## Event-Set Summary

- Candidate events collected: 25
- Accepted events: 12
- Rejected events: 2
- Snapshot failures: 0
- KB cases screened: 70
- V1/V2 overlap in final event IDs: none
- Exact KB leakage in final events: none

## Rejection Reasons

| reason | count |
| --- | ---: |
| duplicate_of_candidate:v3_20240624_eu_russian_lng_transshipment_ban | 1 |
| same_incident_in_kb | 1 |

## Prediction Coverage

- Total exposures: 186
- First-order exposures: 132
- Second-order exposures: 54

## Second-Order Linkage Distribution

| linkage_tier | count |
| --- | ---: |
| direct_exposure | 23 |
| related_exposure | 14 |
| broad_proxy | 17 |

## Second-Order Evidence Distribution

| evidence_level | count |
| --- | ---: |
| historical_supported | 6 |
| sector_proxy | 48 |
| inference_only | 0 |

## Linkage Tier x Evidence Level

| linkage_tier | historical_supported | sector_proxy | inference_only |
| --- | ---: | ---: | ---: |
| direct_exposure | 6 | 17 | 0 |
| related_exposure | 0 | 14 | 0 |
| broad_proxy | 0 | 17 | 0 |

## Event-Level Coverage

| event_id | second_order total | direct | related | broad_proxy |
| --- | ---: | ---: | ---: | ---: |
| v3_20250404_china_rare_earth_export_controls | 2 | 1 | 0 | 1 |
| v3_20250225_copper_import_investigation | 2 | 0 | 2 | 0 |
| v3_20240624_eu_russian_lng_transshipment_ban | 4 | 2 | 0 | 2 |
| v3_20240306_true_confidence_attack | 2 | 1 | 0 | 1 |
| v3_20241203_iran_shadow_fleet_sanctions | 8 | 3 | 3 | 2 |
| v3_20240223_sovcomflot_sanctions | 8 | 4 | 2 | 2 |
| v3_20240913_ustr_section301_tariffs_final | 2 | 1 | 0 | 1 |
| v3_20250730_copper_tariffs | 6 | 3 | 2 | 1 |
| v3_20240821_sounion_tanker_attack | 2 | 0 | 1 | 1 |
| v3_20250110_us_russia_oil_sanctions | 8 | 4 | 2 | 2 |
| v3_20250224_eu_16th_russia_sanctions | 8 | 4 | 2 | 2 |
| v3_20250201_canada_mexico_china_tariffs | 2 | 0 | 0 | 2 |

## Frozen CAR Methodology

- Benchmark: SPY
- Estimation window: [-130, -10]
- Event window: [-1, +1]
- Significance rule: abs(SCAR) >= 1.96
- Market model: asset_return = alpha + beta * benchmark_return
