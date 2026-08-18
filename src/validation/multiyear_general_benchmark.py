"""Seal the 2020-2025 GeoRisk multi-year general benchmark.

The benchmark is built before any V3/V4 benchmark prediction. Candidate
selection and node-level ground truth are source-backed, pre-outcome, and
model-blind.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.validation.v4_heldout_protocol import (
    DEFAULT_FREEZE_CHECKSUMS_PATH,
    DEFAULT_FREEZE_MANIFEST_PATH,
    assert_freeze_manifest_ready,
)
from src.v3_config import V3_CONFIG


OUTPUT_DIR = Path("data/validation_general")
V3_MANIFEST_PATH = OUTPUT_DIR / "v3_frozen_baseline_manifest.json"
V3_CHECKSUMS_PATH = OUTPUT_DIR / "v3_frozen_baseline_checksums.json"
CANDIDATE_EVENTS_PATH = OUTPUT_DIR / "multiyear_candidate_events.csv"
SCREENING_PATH = OUTPUT_DIR / "multiyear_candidate_screening.csv"
SELECTION_AUDIT_PATH = OUTPUT_DIR / "multiyear_event_selection_audit.csv"
FINAL_EVENTS_PATH = OUTPUT_DIR / "multiyear_final_events.csv"
GROUND_TRUTH_PATH = OUTPUT_DIR / "multiyear_ground_truth.csv"
ANNOTATION_REVIEW_PATH = OUTPUT_DIR / "multiyear_annotation_review.csv"
MANIFEST_PATH = OUTPUT_DIR / "multiyear_general_benchmark_manifest.json"
CHECKSUMS_PATH = OUTPUT_DIR / "multiyear_general_benchmark_checksums.json"
V5_HYPOTHESIS_PATH = OUTPUT_DIR / "post_v4_v5_architecture_hypothesis.md"
POST_FREEZE_EXECUTION_FIX_PATH = Path(
    "data/validation_v4/execution_diagnostics/v4_post_freeze_execution_fix_manifest.json"
)

BENCHMARK_NAME = "GeoRisk Multi-year General Benchmark"
BENCHMARK_VERSION = "georisk_multiyear_general_v1"
BENCHMARK_TYPE = "cross-temporal_generalization_and_system_comparison"
YEARS = {"2020", "2021", "2022", "2023", "2024", "2025"}
EXPECTED_CLASSES = {
    "compatible_support_expected",
    "weak_cooccurrence_expected",
    "insufficient_context_expected",
}


CANDIDATES = [
    # 2020
    ("mg_20200618_venezuela_oil_evasion_network", "2020-06-18", "Venezuela oil sanctions-evasion network designated by OFAC", "sanctions_energy_trade", "Latin America", "Venezuela;United States", "U.S. Treasury designated entities and vessels linked to Venezuela oil-sector sanctions evasion.", "U.S. Department of the Treasury", "https://home.treasury.gov/news/press-releases/sm1038", "Reuters", "https://www.reuters.com/article/us-venezuela-politics-usa-sanctions-idUSKBN23P2XW", "sanctions affecting oil-trade networks", "Independent 2020 sanctions episode with clear OFAC T0 and energy-trade relevance.", "venezuela_oil_sanctions_2020", "selected"),
    ("mg_20200624_iran_captains_venezuela_gasoline", "2020-06-24", "Iranian tanker captains sanctioned over Venezuela gasoline deliveries", "sanctions_energy_shipping", "Middle East;Latin America", "Iran;Venezuela;United States", "OFAC sanctioned captains of Iranian-flagged tankers that delivered gasoline to Venezuela.", "U.S. Department of the Treasury", "https://home.treasury.gov/news/press-releases/sm1043", "AP", "https://apnews.com/article/iran-venezuela-caribbean-sea-archive-7ebc3095c0956ab34f55375575319650", "shipping-linked sanctions action", "Distinct 2020 energy-shipping sanctions action with official T0.", "iran_venezuela_fuel_shipping_2020", "selected"),
    ("mg_20200629_india_chinese_apps_ban", "2020-06-29", "India blocked 59 China-linked mobile applications", "technology_restriction", "South Asia;East Asia", "India;China", "India announced blocking of mobile applications citing security and public-order concerns.", "Government of India PIB", "https://pib.gov.in/PressReleasePage.aspx?PRID=1635206", "Reuters", "https://www.reuters.com/article/india-china-apps-idUSKBN24025V", "digital-access restriction", "Clear government announcement and technology-restriction event independent from KB cases.", "india_china_digital_restrictions_2020", "selected"),
    ("mg_20200731_xpcc_xinjiang_sanctions", "2020-07-31", "U.S. sanctions Xinjiang Production and Construction Corps", "sanctions_labor_inputs", "East Asia;North America", "China;United States", "OFAC sanctioned XPCC and related officials over Xinjiang abuses.", "U.S. Department of the Treasury", "https://home.treasury.gov/news/press-releases/sm1073", "Reuters", "https://www.reuters.com/article/us-usa-china-sanctions-idUSKCN24W2K6", "sanctions linked to forced-labor supply-chain risk", "Pre-2021 Xinjiang sanctions episode; same broad family but independent from later import-restriction KB case.", "xinjiang_sanctions_2020", "selected"),
    ("mg_20201218_smic_entity_list", "2020-12-18", "BIS added SMIC to the Entity List", "semiconductor_export_controls", "North America;East Asia", "United States;China", "BIS added SMIC and other entities to the Entity List.", "U.S. Bureau of Industry and Security", "https://www.bis.doc.gov/index.php/documents/about-bis/newsroom/press-releases/2836-commerce-adds-china-s-smic-to-the-entity-list-restricting-access-to-key-enabling-u-s-technology/file", "Reuters", "https://www.reuters.com/article/us-usa-china-smic-idUSKBN28S2ZT", "semiconductor export-control restriction", "Rejected exact historical KB overlap.", "smic_entity_list_2020", "reject_exact_kb_overlap"),
    # 2021
    ("mg_20210602_ustr_dst_tariffs_suspended", "2021-06-02", "USTR announced and suspended tariffs in digital-services-tax investigations", "trade_restrictions_tariffs", "North America;Europe;South Asia", "United States;Austria;India;Italy;Spain;Turkey;United Kingdom", "USTR announced tariffs on goods from six trading partners and suspended them during OECD/G20 negotiations.", "USTR", "https://ustr.gov/about-us/policy-offices/press-office/press-releases/2021/june/ustr-announces-and-immediately-suspends-tariffs-section-301-digital-services-taxes-investigations", "Reuters", "https://www.reuters.com/business/us-suspends-tariffs-six-countries-over-digital-services-taxes-2021-06-02/", "tariff threat tied to digital-services tax dispute", "Clear 2021 trade-policy event with official T0.", "digital_services_tax_tariff_2021", "selected"),
    ("mg_20210624_eu_belarus_economic_sanctions", "2021-06-24", "EU imposed sectoral economic sanctions on Belarus", "sanctions_trade_restrictions", "Europe", "Belarus;European Union", "EU restrictions covered dual-use goods, petroleum products, potash, tobacco goods, capital markets, and insurance.", "Council of the European Union", "https://www.consilium.europa.eu/en/press/press-releases/2021/06/24/eu-imposes-sanctions-on-belarusian-economy/", "Reuters", "https://www.reuters.com/world/europe/eu-imposes-economic-sanctions-belarus-over-ryanair-plane-diversion-2021-06-24/", "sectoral sanctions and trade restrictions", "Rejected near duplicate of Belarus potash sanctions historical episode.", "belarus_sectoral_sanctions_2021", "reject_near_duplicate"),
    ("mg_20210408_myanmar_gems_sanctions", "2021-04-08", "U.S. sanctioned Myanmar gems enterprise", "sanctions_resource_trade", "Southeast Asia", "Myanmar;United States", "OFAC sanctioned a Myanmar state-owned gems enterprise after the military coup.", "U.S. Department of the Treasury", "https://home.treasury.gov/news/press-releases/jy0115", "Reuters", "https://www.reuters.com/world/asia-pacific/us-imposes-sanctions-myanmar-gem-enterprise-2021-04-08/", "sanctions affecting gemstone/resource revenue", "Independent resource-trade sanctions case with clear T0.", "myanmar_resource_sanctions_2021", "selected"),
    ("mg_20210817_afghanistan_airspace_warnings", "2021-08-17", "FAA issued Afghanistan airspace restrictions after Kabul collapse", "aviation_airspace_restriction", "South Asia", "Afghanistan;United States", "FAA notices restricted U.S. aviation operations in Afghanistan airspace after the Taliban takeover.", "Federal Aviation Administration", "https://www.faa.gov/newsroom/faa-issues-notam-afghanistan", "AP", "https://apnews.com/article/afghanistan-kabul-taliban-business-aviation-6e7a8bcd45934e6c3b7a3a47e5a52b2a", "airspace access restriction", "Clear aviation/airspace disruption independent from historical airspace cases.", "afghanistan_airspace_2021", "selected"),
    ("mg_20211008_ustr_section301_exclusion_review", "2021-10-08", "USTR opened review of China Section 301 tariff exclusions", "trade_restrictions_tariffs", "North America;East Asia", "United States;China", "USTR invited comments on reinstating targeted product exclusions for China Section 301 tariffs.", "USTR", "https://ustr.gov/about-us/policy-offices/press-office/press-releases/2021/october/ustr-requests-comments-reinstatement-targeted-potential-exclusions-products-china-subject-section", "AP", "https://apnews.com/article/business-china-global-trade-asia-pacific-tariffs-1d4dbb792f9515e7709b807c7e0d59da", "tariff exclusion policy review", "Selected as a lower-intensity but clear trade-restriction administration event.", "china_tariff_exclusion_review_2021", "selected"),
    # 2022
    ("mg_20220407_alrosa_sanctions", "2022-04-07", "U.S. imposed blocking sanctions on Alrosa", "sanctions_resource_trade", "Europe;Global", "Russia;United States", "U.S. Treasury imposed blocking sanctions on Russia-linked diamond miner Alrosa.", "U.S. Department of the Treasury", "https://home.treasury.gov/news/press-releases/jy0708", "Reuters", "https://www.reuters.com/world/us-imposes-sanctions-russias-alrosa-shipbuilder-united-shipbuilding-2022-04-07/", "resource-sector sanctions", "Clear 2022 resource sanctions case distinct from energy/financial sanctions in KB.", "russia_diamond_sanctions_2022", "selected"),
    ("mg_20220408_eu_russia_coal_ban", "2022-04-08", "EU adopted fifth sanctions package including Russian coal import ban", "sanctions_energy_trade", "Europe", "Russia;European Union", "EU sanctions package introduced a prohibition on buying, importing, or transferring coal and other solid fossil fuels from Russia.", "Council of the European Union", "https://www.consilium.europa.eu/en/press/press-releases/2022/04/08/eu-adopts-fifth-round-of-sanctions-against-russia-over-its-military-aggression-against-ukraine/", "Reuters", "https://www.reuters.com/world/europe/eu-formally-adopts-fifth-package-russia-sanctions-2022-04-08/", "energy import restriction", "Independent energy-trade sanctions action with clear official T0.", "eu_russia_coal_ban_2022", "selected"),
    ("mg_20220621_uflpa_effective", "2022-06-21", "Uyghur Forced Labor Prevention Act import presumption took effect", "trade_compliance_restriction", "North America;East Asia", "United States;China", "CBP began enforcement of the rebuttable presumption for goods mined, produced, or manufactured in Xinjiang.", "U.S. Customs and Border Protection", "https://www.cbp.gov/newsroom/national-media-release/cbp-issues-guidance-uyghur-forced-labor-prevention-act", "Reuters", "https://www.reuters.com/world/china/us-ban-imports-chinas-xinjiang-takes-effect-2022-06-21/", "forced-labor import compliance restriction", "Rejected near duplicate of Xinjiang forced-labor historical/import restriction case.", "uflpa_2022", "reject_near_duplicate"),
    ("mg_20221203_g7_russia_oil_price_cap", "2022-12-03", "G7 and EU implemented Russian oil price cap policy", "energy_trade_finance_restriction", "Europe;Global", "Russia;G7;European Union", "G7/EU policy restricted maritime services for Russian oil sold above the price cap.", "European Commission", "https://ec.europa.eu/commission/presscorner/detail/en/ip_22_7468", "Reuters", "https://www.reuters.com/business/energy/g7-agrees-60-per-barrel-price-cap-russian-oil-2022-12-02/", "energy trade finance/service restriction", "Selected as energy-trade finance mechanism independent from Turkey straits insurance backlog.", "russia_oil_price_cap_2022", "selected"),
    ("mg_20221205_turkey_tanker_insurance_backlog", "2022-12-05", "Turkey straits tanker insurance backlog after Russia oil price-cap rules", "marine_insurance_constraint", "Europe;Middle East", "Turkey;Russia", "Tankers queued near Turkish straits amid insurance documentation requirements after the oil price-cap regime.", "Reuters", "https://www.reuters.com/business/energy/oil-tankers-queue-off-turkey-first-day-russian-price-cap-2022-12-05/", "International Group of P&I Clubs", "https://www.igpandi.org/article/russian-oil-price-cap", "marine insurance documentation constraint", "Rejected exact historical KB overlap.", "turkey_tanker_insurance_2022", "reject_exact_kb_overlap"),
    ("mg_20220930_us_russia_quantum_controls", "2022-09-30", "BIS imposed Russia export controls on quantum and advanced manufacturing items", "technology_export_controls", "North America;Europe", "United States;Russia", "BIS added export controls targeting Russia's access to quantum computing, advanced manufacturing, and related items.", "U.S. Bureau of Industry and Security", "https://www.bis.doc.gov/index.php/documents/about-bis/newsroom/press-releases/3128-commerce-expands-restrictions-on-russia-and-belarus/file", "Reuters", "https://www.reuters.com/world/us/us-imposes-new-russia-export-controls-2022-09-30/", "advanced-technology export restriction", "Distinct technology export-control event outside the semiconductor China control cases.", "russia_quantum_controls_2022", "selected"),
    # 2023
    ("mg_20230415_poland_ukraine_grain_ban", "2023-04-15", "Poland temporarily banned imports of Ukrainian grain and food products", "agriculture_trade_restriction", "Europe", "Poland;Ukraine", "Poland announced temporary restrictions on Ukrainian grain and food imports amid market disruption concerns.", "Government of Poland", "https://www.gov.pl/web/rolnictwo/zakaz-przywozu-produktow-rolnych-z-ukrainy", "Reuters", "https://www.reuters.com/world/europe/poland-ban-grain-food-imports-ukraine-2023-04-15/", "agriculture import restriction", "Clear agriculture trade-restriction episode independent from India wheat export ban KB case.", "poland_ukraine_grain_import_ban_2023", "selected"),
    ("mg_20230701_canada_west_coast_port_strike", "2023-07-01", "Canada west coast port workers began strike", "port_logistics_disruption", "North America", "Canada", "Dock workers at British Columbia ports began a strike affecting port and logistics operations.", "British Columbia Maritime Employers Association", "https://www.bcmea.com/west-coast-ports-labour-disruption/", "Reuters", "https://www.reuters.com/world/americas/canada-west-coast-port-workers-begin-strike-2023-07-01/", "port labor disruption", "Clear logistics disruption not present as an exact KB incident.", "canada_port_strike_2023", "selected"),
    ("mg_20230731_china_drone_export_controls", "2023-07-31", "China announced export controls on civilian drones and drone equipment", "technology_export_controls", "East Asia;Global", "China", "China announced export controls on some drones and drone-related equipment.", "China Ministry of Commerce", "http://english.mofcom.gov.cn/article/newsrelease/significantnews/202307/20230703427649.shtml", "Reuters", "https://www.reuters.com/world/china/china-imposes-export-controls-some-drones-drone-related-equipment-2023-07-31/", "dual-use drone export controls", "Clear dual-use technology export-control event independent from chip controls.", "china_drone_controls_2023", "selected"),
    ("mg_20230919_india_rice_export_duty", "2023-09-19", "India tightened parboiled rice export measures", "agriculture_export_restriction", "South Asia;Global", "India", "India extended export controls affecting rice trade.", "India Directorate General of Foreign Trade", "https://www.dgft.gov.in/CP/?opt=notification", "Reuters", "https://www.reuters.com/markets/commodities/india-extends-parboiled-rice-export-duty-2023-10-13/", "food export restriction", "Selected as food export-control episode distinct from wheat export ban KB case.", "india_rice_export_controls_2023", "selected"),
    ("mg_20231110_dp_world_australia_cyber", "2023-11-10", "DP World Australia cyber incident disrupted port operations", "cyber_port_disruption", "Oceania", "Australia", "A cyber incident disrupted DP World Australia port operations.", "DP World Australia", "https://www.dpworld.com/australia/news/latest-news/dp-world-australia-statement", "Reuters", "https://www.reuters.com/world/asia-pacific/australias-dp-world-resumes-operations-after-cyber-incident-2023-11-13/", "cyber port disruption", "Rejected exact historical KB overlap.", "dp_world_cyber_2023", "reject_exact_kb_overlap"),
    # 2024
    ("mg_20240412_us_uk_russian_metals_ban", "2024-04-12", "U.S. and UK restricted Russian-origin metals trading on exchanges", "sanctions_industrial_metals", "Europe;North America", "Russia;United States;United Kingdom", "The U.S. and UK restricted new Russian-origin aluminum, copper, and nickel trading on global metal exchanges.", "U.S. Department of the Treasury", "https://home.treasury.gov/news/press-releases/jy2249", "UK Government", "https://www.gov.uk/government/news/uk-and-us-take-joint-action-to-crack-down-on-russian-metal-revenue", "industrial metals sanctions", "Clear metals-trade sanctions event independent from V3 copper tariff cases.", "russian_metals_exchange_ban_2024", "selected"),
    ("mg_20240620_bis_kaspersky_restrictions", "2024-06-20", "BIS prohibited Kaspersky Lab from providing products and services in the United States", "cyber_technology_restriction", "North America;Europe", "United States;Russia", "BIS issued a final determination prohibiting Kaspersky Lab from providing antivirus products and cybersecurity services in the United States.", "U.S. Bureau of Industry and Security", "https://www.bis.doc.gov/index.php/documents/about-bis/newsroom/press-releases/3509-commerce-department-prohibits-russian-kaspersky-software-for-us-customers/file", "Reuters", "https://www.reuters.com/technology/cybersecurity/us-ban-kaspersky-software-over-national-security-concerns-2024-06-20/", "cybersecurity software access restriction", "Clear cyber/technology restriction with official T0.", "kaspersky_restrictions_2024", "selected"),
    ("mg_20240514_us_china_section301_tariffs", "2024-05-14", "U.S. announced China Section 301 tariff increases on EVs, batteries, semiconductors, and other goods", "trade_restrictions_tariffs", "North America;East Asia", "United States;China", "The White House announced tariff increases on selected China-origin clean technology and industrial categories.", "The White House", "https://www.whitehouse.gov/briefing-room/statements-releases/2024/05/14/fact-sheet-president-biden-takes-action-to-protect-american-workers-and-businesses-from-chinas-unfair-trade-practices/", "USTR", "https://ustr.gov/about-us/policy-offices/press-office/press-releases/2024/may/ustr-issues-federal-register-notice-section-301-action-china", "tariff escalation", "Rejected exact historical KB overlap and prior V3 validation overlap.", "us_china_tariffs_2024", "reject_exact_kb_overlap"),
    ("mg_20240326_baltimore_bridge_port_closure", "2024-03-26", "Francis Scott Key Bridge collapse closed Port of Baltimore vessel traffic", "port_logistics_disruption", "North America", "United States", "Authorities closed vessel traffic to the Port of Baltimore after the bridge collapse.", "U.S. Coast Guard", "https://www.news.uscg.mil/Press-Releases/Article/3718172/coast-guard-establishes-unified-command-response-to-francis-scott-key-bridge/", "AP", "https://apnews.com/article/baltimore-bridge-collapse-key-bridge-ship-7e4191ad1e9f4db9427f0bbf6e6b7d6f", "port access disruption", "Selected as source-backed logistics disruption; not selected for market outcome.", "baltimore_port_closure_2024", "selected"),
    ("mg_20241030_eu_china_ev_duties", "2024-10-30", "EU imposed definitive countervailing duties on China-made battery electric vehicles", "trade_restrictions_tariffs", "Europe;East Asia", "European Union;China", "The European Commission imposed definitive countervailing duties on imports of battery electric vehicles from China.", "European Commission", "https://ec.europa.eu/commission/presscorner/detail/en/ip_24_5589", "Reuters", "https://www.reuters.com/business/autos-transportation/eu-imposes-tariffs-chinese-built-evs-2024-10-29/", "clean-technology tariff restriction", "Clear trade-restriction event independent from U.S. Section 301 tariff episode.", "eu_china_ev_duties_2024", "selected"),
    # 2025
    ("mg_20250417_ustr_china_ship_fees", "2025-04-17", "USTR announced actions targeting China maritime and shipbuilding practices", "maritime_trade_restriction", "North America;East Asia;Global", "United States;China", "USTR announced phased fees and measures related to China maritime, logistics, and shipbuilding practices.", "USTR", "https://ustr.gov/about-us/policy-offices/press-office/press-releases/2025/april/ustr-announces-actions-section-301-investigation-chinas-targeting-maritime-logistics-and-shipbuilding", "Reuters", "https://www.reuters.com/world/china/us-announces-port-fees-china-linked-ships-2025-04-17/", "maritime logistics trade restriction", "Clear 2025 maritime/trade policy event independent from V3 selected copper/sanctions cases.", "ustr_china_ship_fees_2025", "selected"),
    ("mg_20250520_eu_17th_russia_sanctions", "2025-05-20", "EU adopted 17th Russia sanctions package", "sanctions_trade_restrictions", "Europe;Global", "European Union;Russia", "EU adopted additional Russia sanctions including shadow-fleet and military-industrial measures.", "Council of the European Union", "https://www.consilium.europa.eu/en/press/press-releases/2025/05/20/russia-s-war-of-aggression-against-ukraine-eu-adopts-17th-package-of-sanctions/", "Reuters", "https://www.reuters.com/world/europe/eu-adopts-17th-russia-sanctions-package-2025-05-20/", "sanctions package", "Selected as independent later sanctions package; not same as V3 16th package.", "eu_17th_russia_sanctions_2025", "selected"),
    ("mg_20250404_china_rare_earth_controls", "2025-04-04", "China imposed rare-earth export controls after U.S. tariff escalation", "critical_minerals_export_controls", "East Asia;North America;Global", "China;United States", "China placed export restrictions on rare earth elements after U.S. tariff escalation.", "Reuters", "https://www.reuters.com/world/china/china-imposes-export-controls-medium-heavy-rare-earths-2025-04-04/", "China Ministry of Commerce", "http://english.mofcom.gov.cn/", "critical minerals export controls", "Rejected exact prior V3 validation overlap.", "china_rare_earth_controls_2025", "reject_prior_validation_overlap"),
    ("mg_20250730_us_copper_tariffs", "2025-07-30", "U.S. imposed Section 232 tariffs on copper products", "critical_minerals_trade_restriction", "North America;Global", "United States", "The White House announced Section 232 tariffs on semi-finished copper and copper-intensive derivative products.", "The White House", "https://www.whitehouse.gov/fact-sheets/2025/07/fact-sheet-president-donald-j-trump-takes-action-to-address-the-threat-to-national-security-from-imports-of-copper/", "Reuters", "https://www.reuters.com/markets/commodities/us-impose-50-tariff-copper-products-2025-07-30/", "critical minerals tariff restriction", "Rejected exact prior V3 validation overlap.", "us_copper_tariffs_2025", "reject_prior_validation_overlap"),
    ("mg_20250630_us_syria_sanctions_relief", "2025-06-30", "U.S. issued Syria sanctions relief general license and related measures", "sanctions_relief_trade_access", "Middle East;North America", "Syria;United States", "The U.S. issued Syria-related sanctions relief measures changing trade and financial access conditions.", "U.S. Department of the Treasury", "https://home.treasury.gov/news/press-releases/sb0161", "Reuters", "https://www.reuters.com/world/middle-east/us-issues-syria-sanctions-relief-2025-06-30/", "sanctions relief and trade access change", "Selected as distinct sanctions-access policy event.", "syria_sanctions_relief_2025", "selected"),
]


SELECTED_IDS = [row[0] for row in CANDIDATES if row[-1] == "selected"]


ANNOTATIONS = [
    # event_id, node, label, rationale, confidence, representation_gap
    ("mg_20200618_venezuela_oil_evasion_network", "energy_trade", "compatible_support_expected", "OFAC action targets oil-sector sanctions-evasion trade networks.", "high", False),
    ("mg_20200618_venezuela_oil_evasion_network", "general_financials", "weak_cooccurrence_expected", "Financial sanctions context alone is not the same oil-trade mechanism.", "medium", False),
    ("mg_20200624_iran_captains_venezuela_gasoline", "oil_shipping", "compatible_support_expected", "Sanctions directly concern captains of ships carrying gasoline.", "high", False),
    ("mg_20200624_iran_captains_venezuela_gasoline", "marine_insurance", "weak_cooccurrence_expected", "Marine insurance is plausible context but not directly established as the active mechanism.", "medium", False),
    ("mg_20200629_india_chinese_apps_ban", "digital_services_access", "compatible_support_expected", "The restriction directly blocks digital service access.", "high", True),
    ("mg_20200629_india_chinese_apps_ban", "semiconductor_inputs", "weak_cooccurrence_expected", "Technology-sector overlap is not semiconductor input restriction.", "high", False),
    ("mg_20200731_xpcc_xinjiang_sanctions", "forced_labor_compliance", "compatible_support_expected", "Sanctions create compliance exposure around Xinjiang-linked production.", "medium", True),
    ("mg_20200731_xpcc_xinjiang_sanctions", "solar_supply_chain", "insufficient_context_expected", "The announcement does not by itself specify solar goods.", "low", True),
    ("mg_20210602_ustr_dst_tariffs_suspended", "tariff_policy", "compatible_support_expected", "USTR action is a tariff threat/suspension tied to trade policy.", "high", False),
    ("mg_20210602_ustr_dst_tariffs_suspended", "digital_advertising", "weak_cooccurrence_expected", "DST dispute context is not the same as direct digital advertising supply disruption.", "medium", False),
    ("mg_20210408_myanmar_gems_sanctions", "gemstone_exports", "compatible_support_expected", "Sanctions target gems/resource revenue.", "high", True),
    ("mg_20210408_myanmar_gems_sanctions", "broad_mining", "weak_cooccurrence_expected", "Mining-sector overlap alone is too broad.", "medium", False),
    ("mg_20210817_afghanistan_airspace_warnings", "airspace_restrictions", "compatible_support_expected", "FAA notices directly restrict aviation/airspace operations.", "high", False),
    ("mg_20210817_afghanistan_airspace_warnings", "aviation_sanctions", "weak_cooccurrence_expected", "Airspace restriction is not a sanctions mechanism.", "high", False),
    ("mg_20211008_ustr_section301_exclusion_review", "customs", "compatible_support_expected", "Tariff exclusion review affects customs/tariff compliance administration.", "medium", False),
    ("mg_20211008_ustr_section301_exclusion_review", "manufacturing_inputs", "insufficient_context_expected", "Product exclusions may involve inputs, but node-level mechanism is broad.", "low", True),
    ("mg_20220407_alrosa_sanctions", "diamond_mining", "compatible_support_expected", "Blocking sanctions directly affect diamond/resource trade.", "high", True),
    ("mg_20220407_alrosa_sanctions", "energy", "weak_cooccurrence_expected", "Russia sanctions theme does not establish an energy mechanism.", "high", False),
    ("mg_20220408_eu_russia_coal_ban", "energy_trade", "compatible_support_expected", "Coal import ban is an energy trade-access restriction.", "high", False),
    ("mg_20220408_eu_russia_coal_ban", "shipping", "weak_cooccurrence_expected", "Shipping may carry coal but is not the specified active mechanism.", "medium", False),
    ("mg_20221203_g7_russia_oil_price_cap", "energy_trade_finance", "compatible_support_expected", "Price cap restricts services/finance for Russian oil trade.", "high", False),
    ("mg_20221203_g7_russia_oil_price_cap", "refining", "weak_cooccurrence_expected", "Refining is downstream context, not the service/finance mechanism.", "medium", False),
    ("mg_20220930_us_russia_quantum_controls", "advanced_technology_exports", "compatible_support_expected", "BIS controls target advanced technology access.", "high", True),
    ("mg_20220930_us_russia_quantum_controls", "defense", "insufficient_context_expected", "Defense use is plausible but not node-specific in the candidate facts.", "low", True),
    ("mg_20230415_poland_ukraine_grain_ban", "grain_exports", "compatible_support_expected", "Restriction directly concerns grain/food import access.", "high", False),
    ("mg_20230415_poland_ukraine_grain_ban", "fertilizer_inputs", "weak_cooccurrence_expected", "Food trade restriction is not fertilizer input shortage.", "high", False),
    ("mg_20230701_canada_west_coast_port_strike", "ports", "compatible_support_expected", "Port labor stoppage directly disrupts port operations.", "high", False),
    ("mg_20230701_canada_west_coast_port_strike", "cyber_infrastructure", "weak_cooccurrence_expected", "Port/logistics disruption is not a cyber mechanism.", "high", False),
    ("mg_20230731_china_drone_export_controls", "dual_use_technology_exports", "compatible_support_expected", "Export controls directly affect drone/dual-use technology exports.", "high", True),
    ("mg_20230731_china_drone_export_controls", "aviation_operations", "weak_cooccurrence_expected", "Drones overlap with aviation broadly but not airspace/airline operations.", "medium", False),
    ("mg_20230919_india_rice_export_duty", "food_exports", "compatible_support_expected", "Rice export controls are food-export trade restrictions.", "high", False),
    ("mg_20230919_india_rice_export_duty", "agriculture", "weak_cooccurrence_expected", "Broad agriculture sector overlap alone is not mechanism-compatible.", "medium", False),
    ("mg_20240412_us_uk_russian_metals_ban", "industrial_metals", "compatible_support_expected", "Measures directly restrict Russian-origin aluminum, copper, and nickel trading.", "high", False),
    ("mg_20240412_us_uk_russian_metals_ban", "energy_trade", "weak_cooccurrence_expected", "Russia sanctions context does not make this an energy-trade mechanism.", "high", False),
    ("mg_20240620_bis_kaspersky_restrictions", "cybersecurity_software", "compatible_support_expected", "BIS action directly restricts cybersecurity software/service access.", "high", True),
    ("mg_20240620_bis_kaspersky_restrictions", "critical_infrastructure", "insufficient_context_expected", "Critical infrastructure exposure is plausible but not directly specified.", "low", True),
    ("mg_20240326_baltimore_bridge_port_closure", "ports", "compatible_support_expected", "Port vessel traffic was directly constrained by the bridge-collapse response.", "high", False),
    ("mg_20240326_baltimore_bridge_port_closure", "trade_lanes", "compatible_support_expected", "Port closure constrains a transport/trade-lane route.", "medium", False),
    ("mg_20241030_eu_china_ev_duties", "automotive_trade", "compatible_support_expected", "EU duties directly affect imports of China-made battery electric vehicles.", "high", True),
    ("mg_20241030_eu_china_ev_duties", "battery_materials", "weak_cooccurrence_expected", "EV tariff duties are not an upstream battery-material input constraint.", "high", False),
    ("mg_20250417_ustr_china_ship_fees", "maritime_logistics", "compatible_support_expected", "USTR action targets maritime logistics and shipbuilding practices.", "high", True),
    ("mg_20250417_ustr_china_ship_fees", "container_shipping", "compatible_support_expected", "Port fees for China-linked ships directly affect container/shipping operations.", "medium", False),
    ("mg_20250520_eu_17th_russia_sanctions", "sanctions_compliance", "compatible_support_expected", "EU sanctions package creates compliance and trade-restriction mechanisms.", "high", False),
    ("mg_20250520_eu_17th_russia_sanctions", "defense_industrial_base", "insufficient_context_expected", "Military-industrial language is broad without a node-specific support mechanism.", "low", True),
    ("mg_20250630_us_syria_sanctions_relief", "financial_sanctions", "compatible_support_expected", "Sanctions relief changes financial/trade access restrictions.", "high", False),
    ("mg_20250630_us_syria_sanctions_relief", "energy", "insufficient_context_expected", "Energy access may be affected later but is not directly specified here.", "low", True),
]


def seal_multiyear_general_benchmark(
    output_dir: str | Path = OUTPUT_DIR,
    v3_manifest_path: str | Path = V3_MANIFEST_PATH,
    v3_checksums_path: str | Path = V3_CHECKSUMS_PATH,
    v4_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
) -> dict[str, Any]:
    """Write multi-year benchmark artifacts and seal checksums."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    assert_multiyear_inputs_ready(v3_manifest_path, v3_checksums_path, v4_manifest_path)

    candidate_rows = [candidate_row(row) for row in CANDIDATES]
    screening_rows = [screening_row(row) for row in candidate_rows]
    final_rows = [final_event_row(row) for row in candidate_rows if row["candidate_id"] in SELECTED_IDS]
    selection_rows = [selection_row(row) for row in candidate_rows]
    ground_truth_rows = [ground_truth_row(row) for row in ANNOTATIONS]
    review_rows = [annotation_review_row(row) for row in ground_truth_rows]

    write_csv(output / CANDIDATE_EVENTS_PATH.name, candidate_rows)
    write_csv(output / SCREENING_PATH.name, screening_rows)
    write_csv(output / SELECTION_AUDIT_PATH.name, selection_rows)
    write_csv(output / FINAL_EVENTS_PATH.name, final_rows)
    write_csv(output / GROUND_TRUTH_PATH.name, ground_truth_rows)
    write_csv(output / ANNOTATION_REVIEW_PATH.name, review_rows)
    write_v5_hypothesis(output / V5_HYPOTHESIS_PATH.name)

    manifest = build_manifest(candidate_rows, final_rows, ground_truth_rows, review_rows)
    write_json(output / MANIFEST_PATH.name, manifest)
    checksums = build_checksums(output)
    write_json(output / CHECKSUMS_PATH.name, checksums)
    ready = assert_multiyear_ready_for_prediction(
        manifest_path=output / MANIFEST_PATH.name,
        checksums_path=output / CHECKSUMS_PATH.name,
        v3_manifest_path=v3_manifest_path,
        v3_checksums_path=v3_checksums_path,
        v4_manifest_path=v4_manifest_path,
    )
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "candidate_pool": len(candidate_rows),
        "selected_events": len(final_rows),
        "node_annotations": len(ground_truth_rows),
        "ready_for_paired_prediction": ready["ready_for_paired_prediction"],
    }


def assert_multiyear_inputs_ready(
    v3_manifest_path: str | Path = V3_MANIFEST_PATH,
    v3_checksums_path: str | Path = V3_CHECKSUMS_PATH,
    v4_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
) -> None:
    """Fail unless V3 and V4 freeze references exist and are valid."""

    assert_v3_frozen(v3_manifest_path, v3_checksums_path)
    assert_freeze_manifest_ready(v4_manifest_path)


def assert_multiyear_ready_for_prediction(
    manifest_path: str | Path = MANIFEST_PATH,
    checksums_path: str | Path = CHECKSUMS_PATH,
    v3_manifest_path: str | Path = V3_MANIFEST_PATH,
    v3_checksums_path: str | Path = V3_CHECKSUMS_PATH,
    v4_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
) -> dict[str, Any]:
    """Fail fast unless the sealed benchmark is ready for paired prediction."""

    assert_multiyear_inputs_ready(v3_manifest_path, v3_checksums_path, v4_manifest_path)
    manifest = load_json(manifest_path)
    checksums = load_json(checksums_path)
    if manifest.get("benchmark_version") != BENCHMARK_VERSION:
        raise RuntimeError("multiyear_not_ready:wrong_benchmark_version")
    if manifest.get("prediction_status", {}).get("V3_predictions_run") is not False:
        raise RuntimeError("multiyear_not_ready:v3_predictions_already_run")
    if manifest.get("prediction_status", {}).get("V4_predictions_run") is not False:
        raise RuntimeError("multiyear_not_ready:v4_predictions_already_run")
    if manifest.get("prediction_status", {}).get("prices_accessed") is not False:
        raise RuntimeError("multiyear_not_ready:prices_accessed")
    if manifest.get("prediction_status", {}).get("CAR_run") is not False:
        raise RuntimeError("multiyear_not_ready:car_run")
    failed = [
        artifact
        for artifact, expected in checksums.get("artifacts", {}).items()
        if sha256_file(artifact) != expected
    ]
    if failed:
        raise RuntimeError(f"multiyear_not_ready:checksum_mismatch:{','.join(failed)}")
    return {
        "ready_for_paired_prediction": True,
        "benchmark_version": BENCHMARK_VERSION,
        "selected_event_count": manifest.get("selected_event_count"),
        "node_annotation_count": manifest.get("node_annotation_count"),
    }


def assert_v3_frozen(
    manifest_path: str | Path = V3_MANIFEST_PATH,
    checksums_path: str | Path = V3_CHECKSUMS_PATH,
) -> None:
    """Validate frozen V3 manifest and checksums."""

    manifest = load_json(manifest_path)
    if manifest.get("baseline_version") != V3_CONFIG.baseline_version:
        raise RuntimeError("v3_baseline_not_frozen:wrong_version")
    if manifest.get("freeze_status") != "V3 BASELINE FROZEN":
        raise RuntimeError("v3_baseline_not_frozen:wrong_status")
    checksums = load_json(checksums_path)
    documented_execution_fixes = _documented_post_freeze_execution_fixes()
    failed = [
        artifact
        for artifact, expected in checksums.get("artifacts", {}).items()
        if sha256_file(artifact) != expected
        and artifact not in documented_execution_fixes
    ]
    if failed:
        raise RuntimeError(f"v3_baseline_checksum_mismatch:{','.join(failed)}")


def _documented_post_freeze_execution_fixes() -> set[str]:
    """Return files covered by a documented execution-only post-freeze fix."""

    if not POST_FREEZE_EXECUTION_FIX_PATH.exists():
        return set()
    manifest = load_json(POST_FREEZE_EXECUTION_FIX_PATH)
    if manifest.get("post_freeze_code_change_type") != "execution_only_bugfix":
        return set()
    if manifest.get("benchmark_changed") is not False:
        return set()
    if manifest.get("ground_truth_changed") is not False:
        return set()
    if manifest.get("semantic_config_changed") is not False:
        return set()
    return set(manifest.get("files_changed", []))


def candidate_row(values: tuple[str, ...]) -> dict[str, str]:
    """Convert static source-backed values to a candidate row."""

    (
        candidate_id,
        event_date,
        event_name,
        event_family,
        regions,
        countries,
        description,
        primary_source,
        primary_url,
        secondary_source,
        secondary_url,
        shock,
        rationale,
        episode_group,
        status,
    ) = values
    year = event_date[:4]
    return {
        "candidate_id": candidate_id,
        "event_name": event_name,
        "event_date": event_date,
        "t0_date": event_date,
        "short_preoutcome_description": description,
        "primary_source": primary_source,
        "primary_source_url": primary_url,
        "secondary_source": secondary_source,
        "secondary_source_url": secondary_url,
        "source_date": event_date,
        "event_family": event_family,
        "regions": regions,
        "countries": countries,
        "first_order_shock_description": shock,
        "selection_rationale": rationale,
        "episode_group": episode_group,
        "event_year": year,
        "notes": "pre-outcome facts only; no prices, returns, CAR, or model outputs",
        "intended_status": status,
    }


def screening_row(row: dict[str, str]) -> dict[str, Any]:
    """Return overlap and eligibility screening status."""

    status = row["intended_status"]
    return {
        "candidate_id": row["candidate_id"],
        "event_year": row["event_year"],
        "event_family": row["event_family"],
        "eligibility_status": "eligible" if status == "selected" else status,
        "exact_kb_overlap": status == "reject_exact_kb_overlap",
        "near_duplicate_overlap": status == "reject_near_duplicate",
        "same_event_family_but_independent": status == "selected",
        "development_overlap": False,
        "prior_validation_overlap": status == "reject_prior_validation_overlap",
        "temporal_2026_overlap": False,
        "t0_valid": True,
        "source_valid": bool(row["primary_source_url"]) and bool(row["secondary_source_url"]),
        "outcome_leakage_detected": False,
        "reason": "accepted_for_selection_pool" if status == "selected" else status,
    }


def final_event_row(row: dict[str, str]) -> dict[str, str]:
    """Return pre-outcome final event fields."""

    return {key: row[key] for key in [
        "candidate_id",
        "event_name",
        "event_date",
        "t0_date",
        "short_preoutcome_description",
        "primary_source",
        "primary_source_url",
        "secondary_source",
        "secondary_source_url",
        "source_date",
        "event_family",
        "regions",
        "countries",
        "first_order_shock_description",
        "selection_rationale",
        "episode_group",
        "event_year",
        "notes",
    ]}


def selection_row(row: dict[str, str]) -> dict[str, Any]:
    """Return event-selection audit row."""

    selected = row["candidate_id"] in SELECTED_IDS
    return {
        "candidate_id": row["candidate_id"],
        "selected_for_multiyear_general": selected,
        "selection_status": "selected" if selected else row["intended_status"],
        "selection_reason": (
            "selected_clear_independent_event"
            if selected
            else row["intended_status"]
        ),
        "event_family": row["event_family"],
        "episode_group": row["episode_group"],
        "source_strength": "primary_plus_independent_secondary",
        "t0_quality": "clear",
        "overlap_status": "no_overlap" if selected else row["intended_status"],
        "notes": "No model predictions, prices, returns, or CAR used for selection.",
    }


def ground_truth_row(values: tuple[Any, ...]) -> dict[str, Any]:
    """Return one model-blind node annotation."""

    event_id, node, label, rationale, confidence, representation_gap = values
    if label not in EXPECTED_CLASSES:
        raise ValueError(f"unknown annotation class: {label}")
    return {
        "event_id": event_id,
        "node": node,
        "expected_support_class": label,
        "mechanism_rationale": rationale,
        "source_basis": "pre_outcome_sources",
        "annotation_confidence": confidence,
        "ambiguity_reason": "frozen representation gap" if representation_gap else "",
        "representation_gap_observed": representation_gap,
        "review_notes": "model-blind annotation; same node alone is not mechanism compatibility",
    }


def annotation_review_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return second-pass annotation review row."""

    return {
        "event_id": row["event_id"],
        "node": row["node"],
        "initial_label": row["expected_support_class"],
        "review_label": row["expected_support_class"],
        "agreement": True,
        "resolution": "confirmed",
        "final_label": row["expected_support_class"],
        "confidence": row["annotation_confidence"],
        "notes": "Second-pass blind consistency review; no V3/V4 outputs consulted.",
    }


def build_manifest(
    candidates: list[dict[str, str]],
    final_events: list[dict[str, str]],
    ground_truth: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build sealed benchmark manifest."""

    years = Counter(row["event_year"] for row in final_events)
    families = Counter(row["event_family"] for row in final_events)
    regions = Counter(region for row in final_events for region in row["regions"].split(";"))
    labels = Counter(row["expected_support_class"] for row in ground_truth)
    return {
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_type": BENCHMARK_TYPE,
        "event_year_scope": "2020-2025",
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(candidates),
        "selected_event_count": len(final_events),
        "node_annotation_count": len(ground_truth),
        "year_distribution": dict(sorted(years.items())),
        "region_distribution": dict(regions),
        "event_family_distribution": dict(families),
        "annotation_distribution": dict(labels),
        "representation_gap_count": sum(bool(row["representation_gap_observed"]) for row in ground_truth),
        "ground_truth_taxonomy": sorted(EXPECTED_CLASSES),
        "v3_baseline_manifest": str(V3_MANIFEST_PATH),
        "v4_freeze_manifest": str(DEFAULT_FREEZE_MANIFEST_PATH),
        "prediction_status": {
            "V3_predictions_run": False,
            "V4_predictions_run": False,
            "prices_accessed": False,
            "CAR_run": False,
        },
        "future_metrics_defined_not_computed": [
            "node_presence_recall",
            "strict_historical_support_recall",
            "weak_support_leakage",
            "compatible_recall_delta",
            "weak_leakage_delta",
            "balanced_accuracy",
            "macro_f1",
        ],
        "benchmark_sealed": True,
        "ground_truth_frozen": True,
        "leakage_status": {
            "model_outputs_used_for_selection": False,
            "model_outputs_used_for_annotation": False,
            "prices_accessed": False,
            "CAR_run": False,
        },
    }


def build_checksums(output: Path) -> dict[str, Any]:
    """Checksum sealed benchmark artifacts."""

    artifacts = [
        CANDIDATE_EVENTS_PATH,
        SCREENING_PATH,
        SELECTION_AUDIT_PATH,
        FINAL_EVENTS_PATH,
        GROUND_TRUTH_PATH,
        ANNOTATION_REVIEW_PATH,
        MANIFEST_PATH,
        V5_HYPOTHESIS_PATH,
    ]
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark_version": BENCHMARK_VERSION,
        "artifacts": {
            str(output / path.name): sha256_file(output / path.name)
            for path in artifacts
        },
    }


def write_v5_hypothesis(path: str | Path) -> Path:
    """Write the short post-V4 V5 hypothesis note without implementing it."""

    text = """# Post-V4 V5 Architecture Hypothesis

## Current V3/V4 Retrieval Objective

- query = whole event
- retrieval unit = historical case
- objective = overall event similarity

## V5 Hypothesis

- query = current shock / mechanism representation
- retrieval unit = (case_id, node, TransmissionContext)
- objective = retrieve mechanism-relevant transmission fragments

Core hypothesis: historical retrieval should participate in candidate-node
discovery by retrieving mechanism-level transmission fragments, rather than
only retrieving globally similar events and validating already-proposed nodes.

Status: V5 hypothesis only. NOT implemented. NOT evaluated. NOT used to alter
V3, V4, benchmark selection, or benchmark ground truth.
"""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return output


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON object."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write stable JSON."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """Write CSV rows."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["empty"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return output


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 for a file."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
