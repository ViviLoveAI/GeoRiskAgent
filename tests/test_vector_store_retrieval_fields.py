from src import vector_store


class FakeCollection:
    def count(self):
        return 1

    def query(self, **kwargs):
        return {"ids": [["case_fixture"]], "distances": [[0.1234]]}


class FakeClient:
    def get_or_create_collection(self, name):
        return FakeCollection()


def test_query_cases_preserves_supply_chain_nodes(monkeypatch):
    monkeypatch.setattr(
        vector_store,
        "_load_historical_cases",
        lambda: [
            {
                "event_id": "case_fixture",
                "event_name": "Fixture case",
                "summary": "Fixture summary",
                "event_type": "fixture_event",
                "retrieval_text": "fixture retrieval text",
                "supply_chain_nodes": ["trade_lanes", "logistics"],
                "transmission_chain": ["Fixture chain"],
            }
        ],
    )
    monkeypatch.setattr(vector_store, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(vector_store, "_embed_texts", lambda texts: [[0.1, 0.2]])

    cases = vector_store.query_cases("fixture query", top_k=1)

    assert cases[0].supply_chain_nodes == ["trade_lanes", "logistics"]
