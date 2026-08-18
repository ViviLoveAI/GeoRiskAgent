import pytest

from src import vector_store_health


def test_validate_vector_store_reports_missing_persistence_dir(monkeypatch, tmp_path):
    missing_dir = tmp_path / "missing_chroma"
    monkeypatch.setattr(vector_store_health, "CHROMA_DB_DIR", missing_dir)

    health = vector_store_health.validate_vector_store()

    assert health.healthy is False
    assert health.collection_count is None
    assert "does not exist" in health.message


def test_validate_vector_store_rejects_empty_sqlite_file(monkeypatch, tmp_path):
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    (chroma_dir / "chroma.sqlite3").touch()
    monkeypatch.setattr(vector_store_health, "CHROMA_DB_DIR", chroma_dir)

    health = vector_store_health.validate_vector_store()

    assert health.healthy is False
    assert health.collection_count is None
    assert "empty" in health.message


def test_assert_vector_store_ready_raises_on_unhealthy_index(monkeypatch, tmp_path):
    monkeypatch.setattr(vector_store_health, "CHROMA_DB_DIR", tmp_path / "missing_chroma")

    with pytest.raises(vector_store_health.VectorStoreUnavailableError):
        vector_store_health.assert_vector_store_ready()
