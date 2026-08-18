import json

from src.pipeline import run_v4_pipeline


def test_embedding_model_loads_from_local_cache_only(monkeypatch):
    import src.vector_store as vector_store

    calls = []

    class FakeModel:
        def encode(self, texts, convert_to_numpy=True):
            class FakeEmbeddings:
                def tolist(self_inner):
                    return [[0.1, 0.2, 0.3] for _ in texts]

            return FakeEmbeddings()

    def fake_sentence_transformer(model_name, **kwargs):
        calls.append((model_name, kwargs))
        return FakeModel()

    monkeypatch.setattr(vector_store, "_embedding_model", None)
    monkeypatch.setattr(vector_store, "SentenceTransformer", fake_sentence_transformer)

    assert vector_store._embed_texts(["one"]) == [[0.1, 0.2, 0.3]]
    assert vector_store._embed_texts(["two"]) == [[0.1, 0.2, 0.3]]

    assert calls == [
        (
            "all-MiniLM-L6-v2",
            {"local_files_only": True},
        )
    ]


def test_two_sequential_v4_smoke_calls_succeed_without_closed_client():
    first = run_v4_pipeline(
        "Red Sea shipping routes face disruption due to escalating regional conflict.",
        event_analyzer="rule",
    )
    second = run_v4_pipeline(
        "Government announces export restrictions on critical minerals used in battery supply chains.",
        event_analyzer="rule",
    )

    assert len(first.retrieved_cases) == 10
    assert len(second.retrieved_cases) == 10
    assert len(first.evidence_results) >= 1
    assert len(second.evidence_results) >= 1


def test_v4_semantic_config_remains_frozen_after_execution_fix():
    from src.v4_config import V4_CONFIG

    assert V4_CONFIG.retrieval_top_k == 10
    assert V4_CONFIG.use_mechanism_compatible_support is True
    assert V4_CONFIG.compatible_support_threshold == 2
    assert V4_CONFIG.transmission_context_version == "transmission_context_v1"
    assert V4_CONFIG.canonical_family_version == "canonical_family_v1"
    assert V4_CONFIG.mechanism_compatibility_version == "mechanism_compatibility_candidate_v1"
    assert V4_CONFIG.asset_ranker_version == "ranking_v1"


def test_attempt_001_manifest_preserves_runtime_failure_snapshot():
    payload = json.loads(
        open(
            "data/validation_v4/execution_diagnostics/temporal_prediction_attempt_001_manifest.json",
            encoding="utf-8",
        ).read()
    )

    assert payload["attempt_id"] == "temporal_prediction_attempt_001"
    assert payload["attempt_status"] == "runtime_failure"
    assert payload["semantic_prediction_available"] is False
    assert payload["valid_prediction_snapshot_available"] is False
    assert payload["runtime_failure_count"] == 16


def test_execution_diagnostics_identify_huggingface_http_client():
    payload = json.loads(
        open(
            "data/validation_v4/execution_diagnostics/v4_temporal_execution_failure_diagnostics.json",
            encoding="utf-8",
        ).read()
    )
    failure = payload["representative_failure"]

    assert payload["original_attempt"] == "temporal_prediction_attempt_001"
    assert failure["exception_message"] == "Cannot send a request, as the client has been closed."
    assert failure["failing_file"] == "src/vector_store.py"
    assert failure["failing_function"] == "_load_sentence_transformer_quietly"
    assert failure["client_class"] == "httpx.Client"
