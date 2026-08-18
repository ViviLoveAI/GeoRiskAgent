import pandas as pd
import pytest

from src.agents.evidence_agent import grade_evidence
from src.agents.market_mapper import (
    ALLOWED_LINKAGE_TIERS,
    map_assets,
    validate_asset_mapping_schema,
)
from src.agents.asset_ranker import rank_assets
from src.agents.report_agent import generate_report
from src.schemas import EventAnalysis, TransmissionChain


def test_asset_mapping_linkage_metadata_is_complete():
    frame = pd.read_csv("data/asset_mapping.csv")

    validate_asset_mapping_schema(frame)
    assert set(frame["linkage_tier"]).issubset(ALLOWED_LINKAGE_TIERS)
    assert frame["linkage_rationale"].fillna("").str.strip().ne("").all()


def test_asset_mapping_validation_rejects_unknown_linkage_tier():
    frame = _mapping_frame()
    frame.loc[0, "linkage_tier"] = "not_a_tier"

    with pytest.raises(ValueError, match="unknown linkage_tier"):
        validate_asset_mapping_schema(frame)


def test_market_mapper_preserves_linkage_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.agents.market_mapper.ASSET_MAPPING_PATH",
        _write_mapping_csv(tmp_path),
    )
    event = EventAnalysis(
        title="Event",
        summary="Summary",
        event_type="test",
        supply_chain_nodes=["oil_shipping"],
        shock_direction="negative",
    )

    assets = map_assets(event, TransmissionChain(rationale="Chain"))

    assert len(assets) == 1
    assert assets[0].ticker == "FRO"
    assert assets[0].linkage_tier == "direct_exposure"
    assert assets[0].linkage_rationale == "Crude tanker operator directly tied to oil shipping."


def test_evidence_agent_preserves_linkage_without_changing_confidence(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.agents.market_mapper.ASSET_MAPPING_PATH",
        _write_mapping_csv(tmp_path),
    )
    event = EventAnalysis(
        title="Event",
        summary="Summary",
        event_type="test",
        supply_chain_nodes=["oil_shipping"],
        shock_direction="negative",
    )
    chain = TransmissionChain(
        affected_nodes=["oil_shipping"],
        node_supporting_case_ids={"oil_shipping": ["case_support"]},
        node_evidence_levels={"oil_shipping": "case_grounded"},
        rationale="Chain",
    )
    assets = map_assets(event, chain)

    result = grade_evidence(event, assets, [], chain)[0]

    assert result.evidence_level == "sector_proxy"
    assert result.confidence == 0.64
    assert result.linkage_tier == "direct_exposure"
    assert result.linkage_rationale == "Crude tanker operator directly tied to oil shipping."

    result = rank_assets([result], event, [], chain)[0]
    report = generate_report(event, [], chain, [result])
    watchlist_row = report.secondary_asset_watchlist["sector_proxy"][0]
    assert watchlist_row["linkage_tier"] == "direct_exposure"
    assert watchlist_row["linkage_rationale"] == "Crude tanker operator directly tied to oil shipping."
    assert watchlist_row["ranking_version"] == "ranking_v1"
    assert watchlist_row["priority_tier"] in {"high_priority", "medium_priority", "exploratory"}


def _mapping_frame():
    return pd.DataFrame(
        [
            {
                "supply_chain_node": "oil_shipping",
                "sector": "Shipping",
                "ticker": "FRO",
                "asset_name": "Frontline plc",
                "asset_type": "Stock",
                "region": "Global",
                "notes": "Crude tanker operator exposed to oil shipping routes.",
                "linkage_tier": "direct_exposure",
                "linkage_rationale": "Crude tanker operator directly tied to oil shipping.",
            }
        ]
    )


def _write_mapping_csv(tmpdir):
    path = tmpdir / "asset_mapping.csv"
    _mapping_frame().to_csv(path, index=False)
    return path
