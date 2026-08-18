import random

import pandas as pd
import pytest

from scripts import evaluate_v3_additional_baselines as baselines


def test_random_matched_draw_excludes_georisk_symbols_and_spy():
    universe_by_type = {
        "Stock": [
            {"ticker": "AAA", "asset_type": "Stock", "supply_chain_node": "node_a"},
            {"ticker": "BBB", "asset_type": "Stock", "supply_chain_node": "node_b"},
            {"ticker": "CCC", "asset_type": "Stock", "supply_chain_node": "node_c"},
        ],
        "ETF": [
            {"ticker": "SPY", "asset_type": "ETF", "supply_chain_node": "broad_etf"},
            {"ticker": "QQQ", "asset_type": "ETF", "supply_chain_node": "broad_etf"},
        ],
    }
    georisk = [
        {"symbol": "AAA", "asset_type": "Stock"},
        {"symbol": "SPY", "asset_type": "ETF"},
    ]

    sampled, mismatches = baselines.random_matched_draw(
        georisk,
        universe_by_type,
        random.Random(7),
        "SPY",
        run_id=0,
        event_id="event_1",
        scope="all",
    )

    symbols = {row["symbol"] for row in sampled}
    assert "AAA" not in symbols
    assert "SPY" not in symbols
    assert len(symbols) == len(sampled)
    assert mismatches == []


def test_random_matched_draw_records_feasible_mismatch():
    universe_by_type = {
        "ADR": [
            {"ticker": "ADR1", "asset_type": "ADR", "supply_chain_node": "node_a"},
        ],
    }
    georisk = [
        {"symbol": "ADR1", "asset_type": "ADR"},
        {"symbol": "ADR2", "asset_type": "ADR"},
    ]

    sampled, mismatches = baselines.random_matched_draw(
        georisk,
        universe_by_type,
        random.Random(7),
        "SPY",
        run_id=0,
        event_id="event_1",
        scope="all",
    )

    assert sampled == []
    assert {row["reason"] for row in mismatches} == {
        "insufficient_non_georisk_universe_for_asset_type",
        "insufficient_total_non_georisk_universe",
    }


def test_node_only_baseline_does_not_call_retrieval_transmission_or_evidence(monkeypatch, tmp_path):
    mapping = tmp_path / "asset_mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "supply_chain_node,sector,ticker,asset_name,asset_type,region,notes,linkage_tier,linkage_rationale",
                "trade_lanes,Logistics,AAA,Alpha Logistics,Stock,Global,Trade lane exposure,direct_exposure,Direct test rationale",
                "customs,Logistics,BBB,Beta Customs,Stock,Global,Customs exposure,direct_exposure,Direct test rationale",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.agents.market_mapper.ASSET_MAPPING_PATH", mapping)

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden pipeline stage was called")

    monkeypatch.setattr("src.agents.case_retriever.retrieve_cases", forbidden)
    monkeypatch.setattr("src.agents.transmission_builder.build_transmission_chain", forbidden)
    monkeypatch.setattr("src.agents.evidence_agent.grade_evidence", forbidden)

    dates = pd.date_range("2023-01-01", periods=220, freq="B")
    prices = pd.DataFrame(
        {
            "date": dates,
            "adj_close": [100 + index for index in range(len(dates))],
            "symbol": "AAA",
        }
    )
    cache = {
        "AAA": prices,
        "BBB": prices.assign(symbol="BBB"),
        "SPY": prices.assign(symbol="SPY"),
    }
    snapshots = [
        {
            "event_id": "event_1",
            "event_date": "2023-09-01",
            "event_description": "A tariff and customs trade restrictions announcement affects trade lanes.",
            "headline": "Tariff action affects trade lanes",
            "event_type": "trade_policy_and_tariffs",
        }
    ]

    result = baselines.evaluate_node_only_baseline(
        snapshots,
        cache,
        car_lookup={},
        benchmark_symbol="SPY",
        config=baselines.MarketModelConfig(),
    )

    assert result["summary"]["total_predictions"] == 2
    assert {row["baseline_type"] for row in result["prediction_rows"]} == {
        "node_only_direct_mapping"
    }


def test_integrity_report_flags_expected_manifest_identifier():
    manifest = {
        "manifest_hash": baselines.EXPECTED_MANIFEST_HASH,
        "event_ids": ["event_1"],
    }
    snapshot = {
        "_path": "unused",
        "event_id": "event_1",
        "snapshot_version": "v3_full_pipeline_linkage_ontology",
        "pipeline_mode": "full_georisk_pipeline",
        "predicted_exposures": [
            {
                "event_id": "event_1",
                "symbol": "AAA",
                "node": "trade_lanes",
                "linkage_tier": "direct_exposure",
                "linkage_rationale": "Direct test rationale",
                "evidence_label": "sector_proxy",
            }
        ],
    }

    report = baselines.v3_integrity(manifest, [snapshot], "raw-file-hash")

    assert report["errors"] == ["unexpected_event_count:1"]
    assert report["embedded_manifest_hash"] == baselines.EXPECTED_MANIFEST_HASH
