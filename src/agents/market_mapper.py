"""CSV-backed market exposure mapper for the MVP."""

import pandas as pd

from src.config import ASSET_MAPPING_PATH
from src.schemas import CandidateAsset, EventAnalysis, TransmissionChain


ALLOWED_LINKAGE_TIERS = {"direct_exposure", "related_exposure", "broad_proxy"}
REQUIRED_MAPPING_COLUMNS = {
    "supply_chain_node",
    "sector",
    "ticker",
    "asset_name",
    "asset_type",
    "region",
    "notes",
    "linkage_tier",
    "linkage_rationale",
}


def map_assets(
    event: EventAnalysis,
    transmission_chain: TransmissionChain,
) -> list[CandidateAsset]:
    """Map normalized supply-chain nodes to risk exposure candidates.

    Candidate assets come only from ``data/asset_mapping.csv``. Returned assets
    are mapped supply-chain exposure candidates, not buy/sell recommendations.
    """

    asset_mapping = pd.read_csv(ASSET_MAPPING_PATH)
    validate_asset_mapping_schema(asset_mapping)
    nodes = _dedupe([*event.supply_chain_nodes, *transmission_chain.affected_nodes])
    if not nodes:
        return []

    matched_rows = asset_mapping[asset_mapping["supply_chain_node"].isin(nodes)]

    candidates: list[CandidateAsset] = []
    seen_tickers: set[str] = set()
    for row in matched_rows.to_dict(orient="records"):
        ticker = str(row["ticker"])
        if ticker in seen_tickers:
            continue

        seen_tickers.add(ticker)
        candidates.append(
            CandidateAsset(
                asset_id=ticker,
                name=str(row["asset_name"]),
                category=str(row["sector"]),
                region=str(row["region"]),
                supply_chain_node=str(row["supply_chain_node"]),
                sector=str(row["sector"]),
                ticker=ticker,
                asset_name=str(row["asset_name"]),
                asset_type=str(row["asset_type"]),
                notes=str(row["notes"]),
                linkage_tier=str(row["linkage_tier"]),
                linkage_rationale=str(row["linkage_rationale"]),
                mapping_rationale=(
                    "Mapped supply-chain exposure from normalized node "
                    f"{row['supply_chain_node']}; risk exposure candidate only."
                ),
            )
        )

    return candidates


def validate_asset_mapping_schema(asset_mapping: pd.DataFrame) -> None:
    """Validate linkage metadata required for deterministic mapping output."""

    missing_columns = REQUIRED_MAPPING_COLUMNS - set(asset_mapping.columns)
    if missing_columns:
        raise ValueError(f"asset_mapping.csv missing required columns: {sorted(missing_columns)}")

    linkage_tiers = asset_mapping["linkage_tier"].fillna("").astype(str).str.strip()
    invalid_tiers = sorted(set(linkage_tiers) - ALLOWED_LINKAGE_TIERS)
    if invalid_tiers:
        raise ValueError(f"asset_mapping.csv has unknown linkage_tier values: {invalid_tiers}")

    empty_rationales = asset_mapping["linkage_rationale"].fillna("").astype(str).str.strip() == ""
    if empty_rationales.any():
        tickers = asset_mapping.loc[empty_rationales, "ticker"].astype(str).tolist()
        raise ValueError(f"asset_mapping.csv has empty linkage_rationale for: {tickers}")


def _dedupe(values: list[str]) -> list[str]:
    """Preserve order while removing empty strings and duplicates."""

    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
