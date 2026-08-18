"""Collect candidate geopolitical events for CAR validation.

This stage runs before held-out selection and before CAR evaluation. It reads
public historical news records, normalizes and deduplicates them into candidate
incidents, and writes ``data/validation_event_candidates.json``. It must not
inspect price files, returns, CAR outputs, hit labels, or baseline performance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.validation.validation_set_builder import (
    extract_case_entities,
    jaccard,
    load_historical_cases,
    normalize_text,
    score_candidate_case_overlap,
)


DEFAULT_OUTPUT_PATH = Path("data/validation_event_candidates.json")
DEFAULT_COLLECTION_DIR = Path("data/validation_candidates")
DEFAULT_RAW_DIR = DEFAULT_COLLECTION_DIR / "raw"
DEFAULT_KB_PATH = Path("data/historical_cases.json")
DEFAULT_START_DATE = "2018-01-01"
DEFAULT_END_DATE = "2025-12-31"
DEFAULT_TARGET_CANDIDATES = 30
DEFAULT_RECORDS_PER_QUERY = 75
DEFAULT_POST_EVENT_BUFFER_DAYS = 7
GDELT_DOC_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
KB_OVERLAP_FLAG_SCORE = 0.58
INCIDENT_SIMILARITY_THRESHOLD = 0.62

FetchFn = Callable[[str, str, str, int], list[dict[str, Any]]]


@dataclass(frozen=True)
class QueryFamily:
    """A reproducible GDELT retrieval query family."""

    family_id: str
    event_type_hint: str
    query: str
    regions_hint: list[str]


QUERY_FAMILIES = [
    QueryFamily(
        "maritime_chokepoint_shipping",
        "maritime security disruption",
        '(shipping OR vessel OR tanker OR container) (chokepoint OR canal OR "Red Sea" OR Hormuz OR Suez OR "Panama Canal") (attack OR disruption OR blockade OR restriction OR diversion)',
        ["Global", "Middle East"],
    ),
    QueryFamily(
        "sanctions",
        "sanctions",
        '(sanctions OR sanctioned OR embargo) (Russia OR Iran OR China OR North Korea OR Venezuela OR Myanmar) (announced OR imposed OR expanded)',
        ["Global"],
    ),
    QueryFamily(
        "export_controls",
        "technology export controls",
        '("export controls" OR "export restrictions" OR blacklist OR "Entity List") (semiconductor OR chips OR technology OR equipment)',
        ["Global", "Asia"],
    ),
    QueryFamily(
        "military_escalation_conflict",
        "military escalation conflict",
        '(invasion OR missile OR airstrike OR "military escalation" OR conflict) (border OR strait OR region OR capital)',
        ["Global"],
    ),
    QueryFamily(
        "energy_infrastructure",
        "energy infrastructure disruption",
        '("energy infrastructure" OR pipeline OR refinery OR LNG OR oilfield) (attack OR explosion OR shutdown OR sabotage OR disruption)',
        ["Global"],
    ),
    QueryFamily(
        "trade_tariffs",
        "trade restrictions tariffs",
        '(tariff OR tariffs OR "trade restrictions" OR customs) (announced OR imposed OR raised OR banned)',
        ["Global"],
    ),
    QueryFamily(
        "critical_minerals",
        "critical minerals resource restrictions",
        '("critical minerals" OR rare earths OR graphite OR gallium OR germanium OR lithium OR nickel) (export OR restriction OR ban OR controls)',
        ["Global"],
    ),
    QueryFamily(
        "agriculture_food_fertilizer",
        "agriculture food fertilizer shock",
        '(grain OR wheat OR fertilizer OR food exports OR agriculture) (export ban OR restriction OR disruption OR blockade)',
        ["Global"],
    ),
    QueryFamily(
        "cyber_critical_infrastructure",
        "cyberattack critical infrastructure",
        '(cyberattack OR ransomware OR hack) (pipeline OR port OR grid OR railway OR critical infrastructure)',
        ["Global"],
    ),
    QueryFamily(
        "political_instability_exports",
        "political instability strategic exports",
        '(coup OR unrest OR protests OR political instability) (mine OR port OR exports OR oil OR copper OR lithium)',
        ["Global"],
    ),
    QueryFamily(
        "aerospace_defense_supply_chain",
        "aerospace defense supply-chain disruption",
        '(aerospace OR aviation OR defense) (sanctions OR export controls OR supply chain OR parts shortage)',
        ["Global"],
    ),
]


def collect_validation_candidates(
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    target_candidates: int = DEFAULT_TARGET_CANDIDATES,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    collection_dir: str | Path = DEFAULT_COLLECTION_DIR,
    kb_path: str | Path = DEFAULT_KB_PATH,
    records_per_query: int = DEFAULT_RECORDS_PER_QUERY,
    refresh: bool = False,
    fetch_fn: FetchFn | None = None,
) -> dict[str, Any]:
    """Collect, deduplicate, and write validation candidate incidents."""

    retrieved_at = datetime.now(timezone.utc).isoformat()
    start = parse_date(start_date)
    end = parse_date(end_date)
    max_event_date = max_allowed_event_date(end)
    output = Path(output_path)
    collection_path = Path(collection_dir)
    raw_dir = collection_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    queries_used: list[dict[str, Any]] = []
    fetch = fetch_fn or fetch_gdelt_doc_records
    for family in QUERY_FAMILIES:
        raw_payload = load_or_fetch_family_records(
            family=family,
            start_date=start_date,
            end_date=end_date,
            records_per_query=records_per_query,
            raw_dir=raw_dir,
            refresh=refresh,
            fetch_fn=fetch,
            retrieved_at=retrieved_at,
        )
        queries_used.append(
            {
                "family_id": family.family_id,
                "event_type_hint": family.event_type_hint,
                "query": family.query,
                "raw_cache_path": str(raw_dir / f"{family.family_id}.json"),
            }
        )
        for raw_record in raw_payload.get("records", []):
            normalized = normalize_source_record(raw_record, family, retrieved_at)
            if normalized and source_record_is_eligible(normalized, start, max_event_date):
                records.append(normalized)

    incidents = deduplicate_source_records(records)
    kb_cases = load_historical_cases(kb_path)
    candidates = [
        candidate_from_incident(incident, kb_cases)
        for incident in incidents
    ]
    candidates = sorted(
        candidates,
        key=lambda candidate: (
            str(candidate["event_type_hint"]),
            str(candidate["event_date"]),
            str(candidate["candidate_id"]),
        ),
    )[:target_candidates]

    write_candidates(output, candidates)
    write_collection_artifacts(
        collection_path=collection_path,
        output_path=output,
        candidates=candidates,
        records=records,
        incidents=incidents,
        queries_used=queries_used,
        start_date=start_date,
        end_date=end_date,
        max_event_date=max_event_date,
        records_per_query=records_per_query,
        retrieved_at=retrieved_at,
        kb_cases=kb_cases,
        refresh=refresh,
    )
    return {
        "candidate_count": len(candidates),
        "deduplicated_incident_count": len(incidents),
        "raw_article_count": sum(len(load_json(raw_dir / f"{family.family_id}.json").get("records", [])) for family in QUERY_FAMILIES),
        "eligible_source_record_count": len(records),
        "possible_kb_overlap_count": sum(1 for candidate in candidates if candidate["possible_kb_overlap"]),
        "output_path": str(output),
        "collection_dir": str(collection_path),
    }


def load_or_fetch_family_records(
    family: QueryFamily,
    start_date: str,
    end_date: str,
    records_per_query: int,
    raw_dir: Path,
    refresh: bool,
    fetch_fn: FetchFn,
    retrieved_at: str,
) -> dict[str, Any]:
    """Load cached raw GDELT records or fetch and cache them."""

    cache_path = raw_dir / f"{family.family_id}.json"
    if cache_path.exists() and not refresh:
        return load_json(cache_path)

    try:
        records = fetch_fn(family.query, start_date, end_date, records_per_query)
        error = None
    except Exception as exc:
        records = []
        error = f"{type(exc).__name__}: {exc}"

    payload = {
        "retrieval_source": "GDELT DOC 2.0",
        "endpoint": GDELT_DOC_ENDPOINT,
        "family_id": family.family_id,
        "event_type_hint": family.event_type_hint,
        "query": family.query,
        "start_date": start_date,
        "end_date": end_date,
        "retrieved_at": retrieved_at,
        "error": error,
        "records": records,
    }
    write_json(cache_path, payload)
    return payload


def fetch_gdelt_doc_records(
    query: str,
    start_date: str,
    end_date: str,
    max_records: int,
) -> list[dict[str, Any]]:
    """Fetch raw article records from the public GDELT DOC API."""

    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "startdatetime": f"{compact_date(start_date)}000000",
        "enddatetime": f"{compact_date(end_date)}235959",
        "maxrecords": str(max_records),
        "sort": "hybridrel",
    }
    url = f"{GDELT_DOC_ENDPOINT}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "GeoRisk-CAR-validation/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    articles = payload.get("articles", [])
    return articles if isinstance(articles, list) else []


def normalize_source_record(
    raw: dict[str, Any],
    family: QueryFamily,
    retrieved_at: str,
) -> dict[str, Any] | None:
    """Normalize a GDELT-like article into a source record."""

    headline = str(raw.get("title") or raw.get("headline") or "").strip()
    url = str(raw.get("url") or raw.get("source_url") or "").strip()
    publication_date = parse_source_date(raw)
    if not headline or publication_date is None:
        return None
    event_text = " ".join(
        value
        for value in [
            headline,
            str(raw.get("seendate") or "").strip(),
            str(raw.get("domain") or raw.get("source") or "").strip(),
        ]
        if value
    )
    record_id = stable_id("source", [url, headline, publication_date])
    return {
        "source_record_id": record_id,
        "publication_date": publication_date,
        "headline": headline,
        "event_text": event_text,
        "source": raw.get("domain") or raw.get("source") or "GDELT",
        "source_url": url,
        "gdelt_reference": {
            "url": url,
            "seendate": raw.get("seendate"),
            "language": raw.get("language"),
            "sourceCountry": raw.get("sourceCountry"),
        },
        "retrieval_query": family.query,
        "retrieval_family": family.family_id,
        "retrieved_at": retrieved_at,
        "event_type_hint": family.event_type_hint,
        "regions_hint": list(family.regions_hint),
        "entities_hint": extract_entities_from_text(headline),
    }


def source_record_is_eligible(
    record: dict[str, Any],
    start: pd.Timestamp,
    max_event_date: pd.Timestamp,
) -> bool:
    """Apply basic pre-outcome geopolitical/news-quality filters."""

    date = parse_date(record["publication_date"])
    if date < start or date > max_event_date:
        return False
    text = f"{record.get('headline', '')} {record.get('event_text', '')}"
    if len(text.split()) < 10:
        return False
    if not has_discrete_shock_language(text):
        return False
    return True


def deduplicate_source_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster article records into incident-level candidates."""

    ordered = sorted(
        records,
        key=lambda record: (
            record["event_type_hint"],
            record["publication_date"],
            record["headline"],
            record["source_url"],
        ),
    )
    clusters: list[list[dict[str, Any]]] = []
    for record in ordered:
        matched_cluster = None
        for cluster in clusters:
            if records_describe_same_incident(record, cluster[0]):
                matched_cluster = cluster
                break
        if matched_cluster is None:
            clusters.append([record])
        else:
            matched_cluster.append(record)

    incidents = [incident_from_cluster(cluster) for cluster in clusters]
    return sorted(
        incidents,
        key=lambda incident: (
            incident["event_type_hint"],
            incident["event_date"],
            incident["canonical_headline"],
        ),
    )


def records_describe_same_incident(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Return whether two articles likely refer to the same incident."""

    if left["event_type_hint"] != right["event_type_hint"]:
        return False
    days = abs((parse_date(left["publication_date"]) - parse_date(right["publication_date"])).days)
    if days > 5:
        return False
    entity_score = jaccard(
        set(left.get("entities_hint", [])),
        set(right.get("entities_hint", [])),
    )
    title_score = SequenceMatcher(
        None,
        normalize_text(left["headline"]),
        normalize_text(right["headline"]),
    ).ratio()
    return (0.55 * title_score + 0.45 * entity_score) >= INCIDENT_SIMILARITY_THRESHOLD


def incident_from_cluster(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """Create one incident record from duplicate article coverage."""

    canonical = choose_canonical_record(cluster)
    source_refs = [
        {
            "source": record["source"],
            "source_url": record["source_url"],
            "headline": record["headline"],
            "publication_date": record["publication_date"],
            "source_record_id": record["source_record_id"],
        }
        for record in sorted(cluster, key=lambda item: (source_quality_rank(item), item["headline"]))
    ]
    return {
        "event_date": canonical["publication_date"],
        "canonical_headline": canonical["headline"],
        "event_text": canonical["event_text"],
        "source": canonical["source"],
        "source_url": canonical["source_url"],
        "retrieval_query": canonical["retrieval_query"],
        "retrieved_at": canonical["retrieved_at"],
        "event_type_hint": canonical["event_type_hint"],
        "regions_hint": canonical["regions_hint"],
        "entities_hint": sorted(
            set().union(*(set(record.get("entities_hint", [])) for record in cluster))
        ),
        "supporting_sources": source_refs,
    }


def choose_canonical_record(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """Select the best source representation for an incident deterministically."""

    return sorted(
        cluster,
        key=lambda record: (
            source_quality_rank(record),
            -len(record.get("headline", "")),
            record.get("publication_date", ""),
            record.get("source_url", ""),
        ),
    )[0]


def candidate_from_incident(
    incident: dict[str, Any],
    kb_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert a deduplicated incident into builder-compatible candidate JSON."""

    candidate_id = stable_id(
        "candidate",
        [
            incident["event_date"],
            incident["event_type_hint"],
            incident["canonical_headline"],
        ],
    )
    candidate = {
        "candidate_id": candidate_id,
        "event_id": candidate_id,
        "event_date": incident["event_date"],
        "headline": incident["canonical_headline"],
        "event_text": incident["event_text"],
        "source": incident["source"],
        "source_url": incident["source_url"],
        "retrieval_query": incident["retrieval_query"],
        "retrieved_at": incident["retrieved_at"],
        "event_type_hint": incident["event_type_hint"],
        "event_type": incident["event_type_hint"],
        "regions_hint": incident["regions_hint"],
        "entities": incident["entities_hint"],
        "status": "candidate",
        "supporting_sources": incident["supporting_sources"],
    }
    closest = [
        score_candidate_case_overlap(candidate, case)
        for case in kb_cases
    ]
    closest.sort(key=lambda item: item["score"], reverse=True)
    candidate["possible_kb_overlap"] = bool(closest and closest[0]["score"] >= KB_OVERLAP_FLAG_SCORE)
    candidate["kb_overlap_evidence"] = closest[:3]
    return candidate


def write_candidates(path: str | Path, candidates: list[dict[str, Any]]) -> Path:
    """Write the processed candidate pool."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, {"candidates": candidates})
    return output


def write_collection_artifacts(
    collection_path: Path,
    output_path: Path,
    candidates: list[dict[str, Any]],
    records: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    queries_used: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    max_event_date: pd.Timestamp,
    records_per_query: int,
    retrieved_at: str,
    kb_cases: list[dict[str, Any]],
    refresh: bool,
) -> None:
    """Write collection metadata and CSV audit artifacts."""

    collection_path.mkdir(parents=True, exist_ok=True)
    metadata = {
        "retrieval_source": "GDELT DOC 2.0",
        "date_range": {"start_date": start_date, "end_date": end_date},
        "max_event_date_after_post_event_buffer": max_event_date.date().isoformat(),
        "queries_used": queries_used,
        "raw_article_count": sum(len(load_json(Path(item["raw_cache_path"])).get("records", [])) for item in queries_used),
        "eligible_source_record_count": len(records),
        "deduplicated_incident_count": len(incidents),
        "candidate_count": len(candidates),
        "possible_kb_overlap_count": sum(1 for candidate in candidates if candidate["possible_kb_overlap"]),
        "collection_timestamp": retrieved_at,
        "configuration": {
            "records_per_query": records_per_query,
            "target_output": str(output_path),
            "refresh": refresh,
            "kb_case_count": len(kb_cases),
            "no_market_outcome_inputs": True,
            "forbidden_inputs": [
                "data/prices",
                "data/car_results",
                "CAR",
                "standardized_car",
                "returns",
                "hit_labels",
                "baseline_performance",
            ],
        },
    }
    write_json(collection_path / "collection_metadata.json", metadata)
    write_candidate_audit_csv(collection_path / "candidate_audit.csv", candidates)


def write_candidate_audit_csv(path: str | Path, candidates: list[dict[str, Any]]) -> Path:
    """Write a concise candidate audit CSV."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "candidate_id",
                "event_date",
                "event_type_hint",
                "headline",
                "source",
                "source_url",
                "possible_kb_overlap",
                "supporting_source_count",
            ],
        )
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "candidate_id": candidate["candidate_id"],
                    "event_date": candidate["event_date"],
                    "event_type_hint": candidate["event_type_hint"],
                    "headline": candidate["headline"],
                    "source": candidate["source"],
                    "source_url": candidate["source_url"],
                    "possible_kb_overlap": candidate["possible_kb_overlap"],
                    "supporting_source_count": len(candidate.get("supporting_sources", [])),
                }
            )
    return output


def parse_source_date(raw: dict[str, Any]) -> str | None:
    """Parse common GDELT/article date fields into YYYY-MM-DD."""

    for field in ["seendate", "date", "publication_date", "event_date"]:
        value = raw.get(field)
        if not value:
            continue
        text = str(value)
        if re.match(r"^\d{8}T\d{6}Z$", text):
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
        parsed = pd.to_datetime(text, errors="coerce")
        if not pd.isna(parsed):
            return pd.Timestamp(parsed).date().isoformat()
    return None


def parse_date(value: str) -> pd.Timestamp:
    """Parse an ISO date into a normalized timestamp."""

    parsed = pd.to_datetime(value, errors="raise")
    return pd.Timestamp(parsed).normalize()


def max_allowed_event_date(end_date: pd.Timestamp) -> pd.Timestamp:
    """Exclude events too recent for a post-event CAR window."""

    now_limit = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None).normalize()
    now_limit = now_limit - pd.Timedelta(days=DEFAULT_POST_EVENT_BUFFER_DAYS)
    return min(end_date, now_limit)


def compact_date(value: str) -> str:
    """Return YYYYMMDD for GDELT datetime parameters."""

    return parse_date(value).strftime("%Y%m%d")


def has_discrete_shock_language(text: str) -> bool:
    """Favor identifiable actions over vague long-running topics."""

    normalized = normalize_text(text)
    action_terms = [
        "announced",
        "imposed",
        "launched",
        "attack",
        "attacks",
        "strike",
        "strikes",
        "invaded",
        "invasion",
        "banned",
        "ban",
        "restricted",
        "restriction",
        "controls",
        "sanctions",
        "seized",
        "blocked",
        "shutdown",
        "sabotage",
        "cyberattack",
        "coup",
        "tariff",
        "export",
    ]
    vague_phrases = [
        "tensions continued",
        "concerns continued",
        "ongoing tensions",
        "continued uncertainty",
    ]
    return any(term in normalized for term in action_terms) and not any(
        phrase in normalized for phrase in vague_phrases
    )


def extract_entities_from_text(text: str) -> list[str]:
    """Extract deterministic entity-like tokens from a headline."""

    tokens = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b|\b[A-Z]{2,}\b", text)
    return sorted({token for token in tokens if token.lower() not in {"the", "and", "for"}})


def source_quality_rank(record: dict[str, Any]) -> int:
    """Rank established/primary sources ahead of lower-quality duplicates."""

    source_text = f"{record.get('source', '')} {record.get('source_url', '')}".lower()
    preferred = [
        "reuters",
        "apnews",
        "ap.org",
        "bbc",
        "ft.com",
        "wsj",
        "bloomberg",
        "gov",
        "europa.eu",
        "un.org",
        "nato.int",
    ]
    for index, marker in enumerate(preferred):
        if marker in source_text:
            return index
    return len(preferred)


def stable_id(prefix: str, parts: list[str]) -> str:
    """Return a deterministic short ID."""

    raw = "|".join(normalize_text(str(part)) for part in parts if part)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON object from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> Path:
    """Write JSON with stable formatting."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for candidate collection."""

    parser = argparse.ArgumentParser(
        description="Collect GDELT-backed candidate events for CAR validation.",
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--target-candidates", type=int, default=DEFAULT_TARGET_CANDIDATES)
    parser.add_argument("--records-per-query", type=int, default=DEFAULT_RECORDS_PER_QUERY)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--collection-dir", default=str(DEFAULT_COLLECTION_DIR))
    parser.add_argument("--kb", default=str(DEFAULT_KB_PATH))
    parser.add_argument("--refresh", action="store_true", help="Ignore raw cache and refetch GDELT records.")
    return parser.parse_args()


def main() -> None:
    """Run candidate collection and print a concise summary."""

    args = parse_args()
    result = collect_validation_candidates(
        start_date=args.start_date,
        end_date=args.end_date,
        target_candidates=args.target_candidates,
        output_path=args.output,
        collection_dir=args.collection_dir,
        kb_path=args.kb,
        records_per_query=args.records_per_query,
        refresh=args.refresh,
    )
    print("Validation candidate collection complete.")
    print("source: GDELT DOC 2.0")
    print(f"raw_articles: {result['raw_article_count']}")
    print(f"eligible_source_records: {result['eligible_source_record_count']}")
    print(f"deduplicated_incidents: {result['deduplicated_incident_count']}")
    print(f"candidates_written: {result['candidate_count']}")
    print(f"possible_kb_overlap: {result['possible_kb_overlap_count']}")
    print(f"output: {result['output_path']}")
    print(f"audit_dir: {result['collection_dir']}")


if __name__ == "__main__":
    main()
