# Final Held-Out Validation Audit

This audit covers event selection and snapshot freezing only. It does not inspect prices, returns, CAR, standardized CAR, hit labels, or baseline performance.

## Summary

- Raw candidates: 60
- Deduplicated incidents: 18
- Candidate records loaded: 18
- Candidates with valid event dates: 18
- Candidates with sufficient descriptions: 18
- Possible KB overlaps flagged at collection: 0
- Rejected candidates: 0
- Eligible candidates: 18
- Final selected events: 10
- KB case count: 70
- KB hash: `1cb2016153efa08d8b40897ab272543de9c64507387104d924bdb39e8730525b`
- Manifest hash: `4f14aba1341c81ec077a58ec6bd79475d15dd21ac40e23690bd716d3a8d42b63`
- Selection rule: event_type,event_date,event_id; one pass for event-type diversity, then fill remaining slots
- Random seed: 42

## Rejection Reasons

| Reason | Count |
| --- | ---: |
| none | 0 |

## Baseline Construction

Each accepted event receives the same fixed, outcome-independent baseline basket before market data is loaded: QQQ (broad growth/control ETF), XLF (financial-sector ETF), and XLV (healthcare-sector ETF). The basket is not selected from post-event returns, CAR, hit labels, or GeoRisk-vs-baseline performance.

## Final Events

| event_id | event_date | headline | mechanism | region | closest KB analog | held-out rationale | GeoRisk exposures | baseline exposures | snapshot path |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| candidate_d41a5f82d14a | 2025-10-10 | China Rare Earth Export Control List : What critical minerals are on China export control list now ?, ETAuto | critical minerals resource restrictions | Global | case_rare_earth_export_restriction_risk (score=0.207, date=2010-09-21) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 5498 days apart. | 10 | 3 | data/validation_snapshots/candidate_d41a5f82d14a_snapshot.json |
| candidate_355782516069 | 2025-10-03 | Cyberattack Shuts Down Production of Asahi , Japan Most Popular Beer | cyberattack critical infrastructure | Global | case_2023_dp_world_australia_cyber_port_disruption (score=0.1662, date=2023-11-10) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 693 days apart. | 12 | 3 | data/validation_snapshots/candidate_355782516069_snapshot.json |
| candidate_03b2368e1784 | 2025-10-14 | Goldman sees U . S . consumers paying more than half of Trump tariffs | trade restrictions tariffs | Global | case_2018_2019_us_china_tariffs (score=0.1389, date=2018-07-06) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 2657 days apart. | 10 | 3 | data/validation_snapshots/candidate_03b2368e1784_snapshot.json |
| candidate_fba3f59c71da | 2025-11-09 | International Business : China suspends ban on exports of gallium , germanium , antimony to US | critical minerals resource restrictions | Global | case_rare_earth_export_restriction_risk (score=0.185, date=2010-09-21) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 5528 days apart. | 10 | 3 | data/validation_snapshots/candidate_fba3f59c71da_snapshot.json |
| candidate_ff6378fbb36b | 2025-11-09 | China halts ban on export to US of dual - use metals , further easing tensions | critical minerals resource restrictions | Global | case_rare_earth_export_restriction_risk (score=0.1912, date=2010-09-21) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 5528 days apart. | 2 | 3 | data/validation_snapshots/candidate_ff6378fbb36b_snapshot.json |
| candidate_130fb98e42bb | 2025-11-10 | China Suspends Sanctions on Korean Shipbuilders , Pauses Export Controls After U . S . Trade Detente -- Update | critical minerals resource restrictions | Global | case_rare_earth_export_restriction_risk (score=0.1819, date=2010-09-21) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 5529 days apart. | 12 | 3 | data/validation_snapshots/candidate_130fb98e42bb_snapshot.json |
| candidate_2bd2cdbf5b54 | 2025-10-08 | Hack on Japan popular Asahi beer firm renews concerns over cyberattack readiness | cyberattack critical infrastructure | Global | case_2023_dp_world_australia_cyber_port_disruption (score=0.1656, date=2023-11-10) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 698 days apart. | 12 | 3 | data/validation_snapshots/candidate_2bd2cdbf5b54_snapshot.json |
| candidate_eaccce38b750 | 2025-10-21 | How Companies Can Emerge Stronger After Cyberattacks | cyberattack critical infrastructure | Global | case_2023_dp_world_australia_cyber_port_disruption (score=0.1735, date=2023-11-10) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 711 days apart. | 12 | 3 | data/validation_snapshots/candidate_eaccce38b750_snapshot.json |
| candidate_a126990eefca | 2025-10-25 | US infiltration against China National Time Service Center  proves once again it is the largest source of cyberattack : FM | cyberattack critical infrastructure | Global | case_2023_dp_world_australia_cyber_port_disruption (score=0.1808, date=2023-11-10) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 715 days apart. | 12 | 3 | data/validation_snapshots/candidate_a126990eefca_snapshot.json |
| candidate_4ead99ff6140 | 2025-11-05 | Report : Hackers entered system 3 months before Nevada cyberattack \| Nevada \| News | cyberattack critical infrastructure | Global | case_2023_dp_world_australia_cyber_port_disruption (score=0.1656, date=2023-11-10) | Distinct incident-level candidate; closest KB score below rejection threshold. Closest analog is 726 days apart. | 12 | 3 | data/validation_snapshots/candidate_4ead99ff6140_snapshot.json |
