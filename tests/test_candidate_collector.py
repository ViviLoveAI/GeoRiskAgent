import json

import pandas as pd

from src.validation.candidate_collector import (
    QUERY_FAMILIES,
    QueryFamily,
    candidate_from_incident,
    collect_validation_candidates,
    deduplicate_source_records,
    load_or_fetch_family_records,
    normalize_source_record,
    source_record_is_eligible,
    stable_id,
)


def test_normalize_source_record_preserves_provenance():
    family = QueryFamily("sanctions", "sanctions", "sanctions announced", ["Global"])
    raw = {
        "title": "US announces new sanctions on Russian banks",
        "url": "https://example.com/story",
        "seendate": "20240201T120000Z",
        "domain": "reuters.com",
        "language": "English",
        "sourceCountry": "US",
    }

    record = normalize_source_record(raw, family, "2026-01-01T00:00:00+00:00")

    assert record["publication_date"] == "2024-02-01"
    assert record["headline"] == raw["title"]
    assert record["source"] == "reuters.com"
    assert record["source_url"] == raw["url"]
    assert record["retrieval_query"] == "sanctions announced"
    assert record["gdelt_reference"]["seendate"] == "20240201T120000Z"


def test_duplicate_articles_collapse_to_one_incident():
    records = [
        _record("Reuters: US announces sanctions on Russian banks", "2024-02-01", "reuters.com"),
        _record("AP: US announces sanctions on Russian banks", "2024-02-02", "apnews.com"),
    ]

    incidents = deduplicate_source_records(records)

    assert len(incidents) == 1
    assert len(incidents[0]["supporting_sources"]) == 2


def test_different_incidents_same_category_remain_separate():
    records = [
        _record("US announces sanctions on Russian banks", "2024-02-01", "reuters.com"),
        _record("EU imposes sanctions on Iranian drone makers", "2024-03-15", "reuters.com"),
    ]

    incidents = deduplicate_source_records(records)

    assert len(incidents) == 2


def test_deterministic_candidate_ids():
    parts = ["2024-02-01", "sanctions", "US announces sanctions"]

    assert stable_id("candidate", parts) == stable_id("candidate", parts)
    assert stable_id("candidate", parts).startswith("candidate_")


def test_kb_overlap_flagging():
    incident = {
        "event_date": "2021-03-23",
        "canonical_headline": "Ever Given blocks Suez Canal",
        "event_text": "Ever Given blocks Suez Canal shipping traffic.",
        "source": "reuters.com",
        "source_url": "https://example.com/suez",
        "retrieval_query": "shipping disruption",
        "retrieved_at": "2026-01-01T00:00:00+00:00",
        "event_type_hint": "shipping chokepoint disruption",
        "regions_hint": ["Middle East"],
        "entities_hint": ["Ever", "Given", "Suez", "Canal"],
        "supporting_sources": [],
    }
    kb_cases = [
        {
            "event_id": "case_2021_suez_blockage",
            "date": "2021-03-23",
            "event_name": "Suez Canal blockage by Ever Given",
            "event_type": "shipping chokepoint disruption",
            "summary": "Ever Given grounded in the Suez Canal.",
            "countries": ["Egypt"],
        }
    ]

    candidate = candidate_from_incident(incident, kb_cases)

    assert candidate["possible_kb_overlap"] is True
    assert candidate["kb_overlap_evidence"][0]["case_id"] == "case_2021_suez_blockage"


def test_date_range_filtering_excludes_out_of_range_and_too_recent():
    record = _record("US announces sanctions on Russian banks", "2024-02-01", "reuters.com")

    assert source_record_is_eligible(
        record,
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-12-31"),
    )
    assert not source_record_is_eligible(
        record,
        pd.Timestamp("2024-03-01"),
        pd.Timestamp("2024-12-31"),
    )


def test_cached_result_reuse(tmp_path):
    family = QueryFamily("test", "sanctions", "query", ["Global"])
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cache = raw_dir / "test.json"
    cache.write_text(
        json.dumps({"records": [{"title": "cached"}], "query": "query"}) + "\n",
        encoding="utf-8",
    )

    result = load_or_fetch_family_records(
        family=family,
        start_date="2024-01-01",
        end_date="2024-12-31",
        records_per_query=10,
        raw_dir=raw_dir,
        refresh=False,
        fetch_fn=lambda *args: (_ for _ in ()).throw(AssertionError("should not fetch")),
        retrieved_at="2026-01-01T00:00:00+00:00",
    )

    assert result["records"][0]["title"] == "cached"


def test_collect_validation_candidates_writes_audit_artifacts(tmp_path):
    kb = tmp_path / "historical_cases.json"
    kb.write_text("[]\n", encoding="utf-8")
    output = tmp_path / "validation_event_candidates.json"
    collection_dir = tmp_path / "validation_candidates"

    def fetch(query, start_date, end_date, max_records):
        return [
            {
                "title": f"US announces export controls after {query[:12]}",
                "url": f"https://example.com/{abs(hash(query))}",
                "seendate": "20240201T120000Z",
                "domain": "reuters.com",
            }
        ]

    result = collect_validation_candidates(
        start_date="2024-01-01",
        end_date="2024-12-31",
        target_candidates=3,
        output_path=output,
        collection_dir=collection_dir,
        kb_path=kb,
        records_per_query=1,
        fetch_fn=fetch,
        refresh=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result["candidate_count"] == 3
    assert len(payload["candidates"]) == 3
    assert (collection_dir / "collection_metadata.json").exists()
    assert (collection_dir / "candidate_audit.csv").exists()
    assert (collection_dir / "raw" / f"{QUERY_FAMILIES[0].family_id}.json").exists()


def test_collection_has_no_market_output_dependency(tmp_path):
    kb = tmp_path / "historical_cases.json"
    kb.write_text("[]\n", encoding="utf-8")
    (tmp_path / "data" / "prices").mkdir(parents=True)
    (tmp_path / "data" / "car_results").mkdir(parents=True)
    (tmp_path / "data" / "car_results" / "car_summary.json").write_text(
        '{"georisk_flagged_hit_rate": 1.0}\n',
        encoding="utf-8",
    )

    result = collect_validation_candidates(
        start_date="2024-01-01",
        end_date="2024-12-31",
        target_candidates=1,
        output_path=tmp_path / "validation_event_candidates.json",
        collection_dir=tmp_path / "validation_candidates",
        kb_path=kb,
        records_per_query=1,
        fetch_fn=lambda *args: [
            {
                "title": "US announces sanctions on Russian banks",
                "url": "https://example.com/sanctions",
                "seendate": "20240201T120000Z",
                "domain": "reuters.com",
            }
        ],
        refresh=True,
    )
    metadata = json.loads(
        (tmp_path / "validation_candidates" / "collection_metadata.json").read_text()
    )

    assert result["candidate_count"] == 1
    assert metadata["configuration"]["no_market_outcome_inputs"] is True


def _record(headline, date, source):
    return {
        "source_record_id": stable_id("source", [headline, date, source]),
        "publication_date": date,
        "headline": headline,
        "event_text": headline,
        "source": source,
        "source_url": f"https://{source}/{stable_id('url', [headline])}",
        "gdelt_reference": {},
        "retrieval_query": "sanctions",
        "retrieval_family": "sanctions",
        "retrieved_at": "2026-01-01T00:00:00+00:00",
        "event_type_hint": "sanctions",
        "regions_hint": ["Global"],
        "entities_hint": ["US", "Russian", "Banks"],
    }
