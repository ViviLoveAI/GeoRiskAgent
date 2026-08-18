# GeoRisk V3 Evaluation Report

## 1. Executive Summary

V3 uses 12 frozen held-out geopolitical events. The accepted V3 event set has no V1/V2 overlap recorded in the V3 design artifacts and no exact-event knowledge-base leakage. Predictions were frozen before CAR evaluation, and the CAR layer is an ex-post exposure-validation check, not price-prediction performance.

Full GeoRisk produced 186 evaluated exposures: 132 first-order exposures and 54 incremental second-order exposures. Of the 54 second-order exposures, 8 reached the strict magnitude-based CAR threshold, for a second-order hit rate of 14.81%. The matched-random second-order mean hit rate was 9.59%, and the GeoRisk second-order hit rate ranked at the 93.9th percentile of matched random controls. Five of 12 events had at least one second-order hit.

This is evidence of second-order exposure-discovery signal. It is not statistically proven alpha, does not show that GeoRisk predicts stock movements, and should not be interpreted as investment performance.

## 2. Experimental Design

Candidate events were screened before market-outcome evaluation. The V3 design artifacts report 25 candidate events, 12 accepted events, and 2 rejected events. Rejection reasons were: duplicate_of_candidate:v3_20240624_eu_russian_lng_transshipment_ban=1, same_incident_in_kb=1.

The accepted V3 events are:

| event_id | date | headline | event_type |
| --- | --- | --- | --- |
| v3_20250404_china_rare_earth_export_controls | 2025-04-04 | China imposes rare-earth export controls after U.S. tariff escalation | critical_minerals_export_controls |
| v3_20250225_copper_import_investigation | 2025-02-25 | U.S. launches Section 232 investigation into copper import dependence | critical_minerals_trade_restriction |
| v3_20240624_eu_russian_lng_transshipment_ban | 2024-06-24 | EU sanctions package bans Russian LNG transshipment services through EU territory | energy_sanctions |
| v3_20240306_true_confidence_attack | 2024-03-06 | Houthi anti-ship missile strikes M/V True Confidence in Gulf of Aden | maritime_security_disruption |
| v3_20241203_iran_shadow_fleet_sanctions | 2024-12-03 | U.S. sanctions Iranian shadow-fleet petroleum transport entities and vessels | sanctions_energy_shipping |
| v3_20240223_sovcomflot_sanctions | 2024-02-23 | U.S. sanctions Sovcomflot and tankers tied to Russian oil shipping | shipping_sanctions |
| v3_20240913_ustr_section301_tariffs_final | 2024-09-13 | USTR finalizes China Section 301 tariff modifications after four-year review | trade_policy_and_tariffs |
| v3_20250730_copper_tariffs | 2025-07-30 | U.S. imposes Section 232 tariffs on copper products | critical_minerals_trade_restriction |
| v3_20240821_sounion_tanker_attack | 2024-08-21 | MV Sounion oil tanker attacked in the Red Sea | maritime_security_disruption |
| v3_20250110_us_russia_oil_sanctions | 2025-01-10 | U.S. sanctions Russian oil producers and shadow-fleet vessels | sanctions_energy_shipping |
| v3_20250224_eu_16th_russia_sanctions | 2025-02-24 | EU adopts 16th Russia sanctions package targeting shadow fleet and military suppliers | sanctions_energy_shipping |
| v3_20250201_canada_mexico_china_tariffs | 2025-02-01 | U.S. imposes tariffs on imports from Canada, Mexico and China | trade_policy_and_tariffs |

Design integrity recorded in the frozen artifacts:

- Manifest hash: `d67ae3db74eb150acf94d41985f28a04f4bd97a5837597a3800384110ebf2010`
- KB case count: 70
- KB hash: `1cb2016153efa08d8b40897ab272543de9c64507387104d924bdb39e8730525b`
- Exact KB leakage in final set: []
- Prior V1/V2 overlap in final set: []
- Snapshot failures: []
- Outcome data used during design: False

All prediction snapshots came from the full GeoRisk pipeline and were frozen before the CAR evaluation. The V3 report does not relabel, refit, or tune any model component from CAR results.

## 3. CAR Methodology

- Benchmark: SPY
- Estimation window: [-130, -10]
- Event window: [-1, +1]
- Market model: `asset_return = alpha + beta * benchmark_return`
- Hit definition: `abs(SCAR) >= 1.96`

CAR/SCAR measures abnormal market reaction around the event after accounting for benchmark behavior. A non-hit does not necessarily mean the economic exposure is false. It only means the asset did not cross the strict short-window abnormal-return threshold.

## 4. Overall V3 Results

| Metric | GeoRisk |
| --- | --- |
| Evaluated pairs | 186 |
| Hits | 22 |
| Hit rate | 11.83% |
| Mean abs(SCAR) | 0.9443 |
| Median abs(SCAR) | 0.7431 |

The fixed ETF control is not used as the primary model-quality comparison because it is not event matched or node matched. Matched-random and node-only ablation baselines are more informative for exposure-selection diagnostics.

## 5. First-Order vs Second-Order

| Transmission order | Evaluated | Hits | Hit rate | Mean abs(SCAR) | Median abs(SCAR) |
| --- | --- | --- | --- | --- | --- |
| first_order | 132 | 14 | 10.61% | 0.9441 | 0.7431 |
| second_order | 54 | 8 | 14.81% | 0.9449 | 0.7453 |

The 54 second-order exposures are the incremental exposures added beyond the node-only first-order mapping baseline. The second-order rows had a higher descriptive hit rate than first-order rows in this frozen run, but this should not be read as causal superiority.

## 6. Primary Second-Order Finding

- Second-order exposures: 54
- Second-order hits: 8
- Second-order hit rate: 14.81%
- Events with at least one second-order hit: 5/12
- Events with at least one first-order hit: 6/12
- Events where node-only first-order exposures had no hit but an incremental second-order GeoRisk exposure did: 2 (v3_20241203_iran_shadow_fleet_sanctions, v3_20250224_eu_16th_russia_sanctions)

This supports the descriptive claim that historical transmission reasoning can surface market-reactive secondary exposures that a direct node-only lookup misses. It does not prove that every second-order exposure is economically valid or that the method generates tradable signals.

## 7. Matched-Random Baseline

The random-matched baseline used the same 12-event set and the same `data/asset_mapping.csv` candidate universe. Each deterministic Monte Carlo run matched the event-level GeoRisk asset count and asset-type composition as closely as possible, excluded event-specific GeoRisk symbols and SPY, and did not use CAR, SCAR, return, linkage, evidence label, or hit-outcome information during sampling.

Overall matched-random results:

- Random mean hit rate: 10.06%
- GeoRisk hit rate: 11.83%
- GeoRisk hit-rate percentile: 87.1%
- GeoRisk mean abs(SCAR) percentile: 79.4%
- GeoRisk median abs(SCAR) percentile: 93.7%

Second-order matched-random results:

- Random mean hit rate: 9.59%
- Random 95% interval: 3.70% - 15.09%
- GeoRisk second-order hit rate: 14.81%
- GeoRisk second-order percentile rank: 93.9%

GeoRisk shows stronger concentration than most matched-random selections, especially for second-order exposures, but the second-order hit rate remains inside the random 95% interval and should not be described as statistically significant outperformance.

## 8. Node-Only Ablation

The node-only baseline uses this restricted path:

`Event Analyst -> directly extracted first-order nodes -> Market Mapper`

It does not use historical retrieval, Transmission Builder, second-order expansion, Evidence Agent, supporting case IDs, evidence labels, or confidence values derived from historical support.

Node-only and incremental comparison:

- Node-only: 132 evaluated, 14 hits, 10.61%
- Full GeoRisk: 186 evaluated, 22 hits, 11.83%
- Incremental second-order: 54 evaluated, 8 hits, 14.81%

The incremental exposures are exactly the second-order additions from the full pipeline.

## 9. Fixed ETF Control

The legacy fixed ETF control assigns QQQ, XLF, and XLV to every event. It is outcome-independent and fixed, but it is not event matched, not node matched, and not random. It is included for completeness only and should not be interpreted as a fair head-to-head exposure-selection benchmark.

Existing V3 fixed ETF control numbers:

- Evaluated: 36
- Hits: 6
- Hit rate: 16.67%
- Mean abs(SCAR): 1.0080
- Median abs(SCAR): 0.6281

## 10. Evidence-Confidence Analysis

| Scope | Group | Evaluated | Hits | Hit Rate | Mean abs(SCAR) | Median abs(SCAR) |
| --- | --- | --- | --- | --- | --- | --- |
| all | high confidence | 38 | 5 | 13.16% | 1.1339 | 0.9479 |
| all | lower confidence | 148 | 17 | 11.49% | 0.8957 | 0.6156 |
| first_order | high confidence | 32 | 3 | 9.38% | 1.0739 | 1.0010 |
| first_order | lower confidence | 100 | 11 | 11.00% | 0.9026 | 0.5916 |
| second_order | high confidence | 6 | 2 | 33.33% | 1.4540 | 0.7972 |
| second_order | lower confidence | 48 | 6 | 12.50% | 0.8812 | 0.7453 |

Evidence confidence appears promising as a ranking signal for second-order exposures, but the high-confidence second-order sample is only n=6 and is too small for calibration claims. Confidence remains evidence strength, not movement probability.

## 11. Linkage-Tier Analysis

Second-order linkage-tier results:

| linkage_tier | evaluated | hits | hit_rate | mean_abs(SCAR) | median_abs(SCAR) | max_abs(SCAR) |
| --- | --- | --- | --- | --- | --- | --- |
| broad_proxy | 17 | 4 | 23.53% | 0.8675 | 0.5065 | 2.3748 |
| direct_exposure | 23 | 2 | 8.70% | 1.0217 | 0.7845 | 3.6337 |
| related_exposure | 14 | 2 | 14.29% | 0.9127 | 0.7627 | 2.2940 |

The strict hit-rate ordering did not support the hypothesis that `direct_exposure > related_exposure > broad_proxy`: broad proxies had the highest second-order hit rate in this run. Typical reaction magnitude showed some ordering in mean/median, so linkage remains useful interpretability metadata, but V3 does not validate it as a standalone precision feature.

## 12. Baseline Comparison Table

| System | Evaluated | Hits | Hit rate | Mean abs(SCAR) | Median abs(SCAR) |
| --- | --- | --- | --- | --- | --- |
| Full GeoRisk | 186 | 22 | 11.83% | 0.9443 | 0.7431 |
| Node-Only Baseline | 132 | 14 | 10.61% | 0.9441 | 0.7431 |
| Fixed ETF Control | 36 | 6 | 16.67% | 1.0080 | 0.6281 |
| Random-Matched Baseline mean over 1000 runs | 185.342 | 18.639 | 10.06% | 0.9056 | 0.6663 |

The random-matched row reports Monte Carlo means over 1000 deterministic runs, not one single baseline run.

## 13. Event-Level CAR Summary

| event_id | first eval | first hits | second eval | second hits | second mean abs(SCAR) | second median abs(SCAR) |
| --- | --- | --- | --- | --- | --- | --- |
| v3_20240223_sovcomflot_sanctions | 10 | 1 | 8 | 0 | 0.475372 | 0.308176 |
| v3_20240306_true_confidence_attack | 14 | 0 | 2 | 0 | 0.256374 | 0.256374 |
| v3_20240624_eu_russian_lng_transshipment_ban | 10 | 0 | 4 | 0 | 0.577471 | 0.619459 |
| v3_20240821_sounion_tanker_attack | 14 | 0 | 2 | 0 | 1.485528 | 1.485528 |
| v3_20240913_ustr_section301_tariffs_final | 10 | 1 | 2 | 0 | 0.526918 | 0.526918 |
| v3_20241203_iran_shadow_fleet_sanctions | 14 | 0 | 8 | 1 | 0.805292 | 0.548553 |
| v3_20250110_us_russia_oil_sanctions | 10 | 2 | 8 | 2 | 1.361408 | 0.838333 |
| v3_20250201_canada_mexico_china_tariffs | 10 | 1 | 2 | 0 | 0.344690 | 0.344690 |
| v3_20250224_eu_16th_russia_sanctions | 10 | 0 | 8 | 3 | 1.337246 | 0.832218 |
| v3_20250225_copper_import_investigation | 10 | 0 | 2 | 0 | 0.762654 | 0.762654 |
| v3_20250404_china_rare_earth_export_controls | 10 | 7 | 2 | 1 | 1.781239 | 1.781239 |
| v3_20250730_copper_tariffs | 10 | 2 | 6 | 1 | 1.093879 | 0.932071 |

These rows are clustered within 12 geopolitical events, so asset-event rows should not be treated as fully independent observations.

## 14. What V3 Supports

Supported descriptively:

- GeoRisk finds second-order exposures that show real abnormal market reactions.
- Second-order exposures were not systematically weaker than first-order ones.
- The second-order selection outperformed most matched-random controls.
- Historical evidence strength shows a promising second-order ranking signal.

Not established:

- statistical significance over random
- calibrated market-movement probabilities
- reliable superiority of linkage tier
- trading alpha
- investment performance

## 15. Limitations

- Only 12 independent events were evaluated.
- Asset rows are clustered within events.
- The CAR window is a strict short [-1, +1] event window.
- CAR captures short-horizon abnormal market reaction only.
- Some exposures may be priced in earlier or transmit with delay.
- The historical-supported second-order sample is small.
- The candidate universe is limited by `data/asset_mapping.csv`.
- V3 does not include a learned ranking model.
- V3 should be used for diagnosis, not future ranking-weight optimization.

## 16. Next Step

Ranking v1 should be designed from ex-ante pipeline features and then frozen before a new V4 held-out evaluation. V3 CAR outcomes should not be used to tune numeric ranking weights.

Future V4 metrics should include:

- Hit Rate @ Top 3
- Hit Rate @ Top 5
- Hit Rate @ Top 10
- mean/median abs(SCAR) @ Top-K
- second-order Top-K
- matched-random Top-K lift

## 17. Artifact Index

Validation design:

- `data/validation_v3/accepted_events.csv`
- `data/validation_v3/v3_manifest.json`
- `data/validation_v3/v3_snapshot_summary.json`
- `data/validation_v3/prediction_snapshots/`

CAR results:

- `data/car_results_v3/car_summary.json`
- `data/car_results_v3/car_pair_results.csv`
- `data/car_results_v3/linkage_analysis.csv`
- `data/car_results_v3/evidence_analysis.csv`
- `data/car_results_v3/event_level_analysis.csv`
- `data/car_results_v3/skipped_pairs.json`

Baselines:

- `data/baseline_v3/random_matched_summary.json`
- `data/baseline_v3/baseline_comparison.csv`
- `data/baseline_v3/incremental_value_analysis.csv`
- `data/baseline_v3/node_only_summary.json`
- `data/baseline_v3/random_matched_event_summary.csv`
- `data/baseline_v3/event_level_baseline_comparison.csv`
- `data/baseline_v3/integrity_report.json`

Confidence analysis:

- `data/analysis_v3/confidence_summary.json`
- `data/analysis_v3/confidence_overall.csv`
- `data/analysis_v3/confidence_first_order.csv`
- `data/analysis_v3/confidence_second_order.csv`
- `data/analysis_v3/confidence_event_level.csv`
- `data/analysis_v3/confidence_linkage_crosstab.csv`
- `data/analysis_v3/confidence_integrity_report.json`

## 18. Final Integrity Check

- V3 manifest hash matches expected: yes (`d67ae3db74eb150acf94d41985f28a04f4bd97a5837597a3800384110ebf2010`)
- Accepted event count: 12
- Frozen snapshot count: 12
- Snapshot exposure reconciliation: 186 = 132 first_order + 54 second_order
- CAR hit reconciliation: 22 = 14 first_order + 8 second_order
- Pair accounting: 222 total rows = 186 GeoRisk + 36 baseline; skipped pairs = 0
- Duplicate event/symbol/node rows reported by integrity artifacts: 0
- Manifest unchanged during CAR run: True
- Snapshots unchanged during CAR run: True
- Baseline integrity errors: []
- Confidence integrity errors: []
- V1/V2 artifacts were not used as sources and were not written by this consolidation step.

Generated from existing artifacts only. Report generated at 2026-08-05T06:03:46.204883+00:00.
