import os

os.environ.setdefault("RETRY_BASE_DELAY", "0")
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import assistant
import chat
import memory
import routes


@pytest.fixture(autouse=True)
def isolated_memory(tmp_path, monkeypatch):
    """Every test gets a fresh SQLite store in tmp_path, so tests never touch data/memory.db."""
    store = memory.SqliteMemoryStore(tmp_path / "memory.db")
    monkeypatch.setattr(chat, "memory", store)
    monkeypatch.setattr(routes, "memory", store)
    monkeypatch.setattr(assistant, "memory", store)
    monkeypatch.setattr(memory, "memory", store)      # graph.py reaches it as memory_module.memory
    return store


# --- Day 26: shared fixtures ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def fake_index():
    """(embedder, store) built once from the real documents with deterministic fake embeddings."""
    from tests.fakes import build_fake_index
    return build_fake_index()


@pytest.fixture
def real_retrieval(monkeypatch, fake_index):
    """Real retrieval code (FAISS, ranking, filters, sibling expansion) over real chunks; only embeddings are faked."""
    import retrieval
    embedder, store = fake_index
    monkeypatch.setattr(retrieval, "get_embedding", embedder)
    monkeypatch.setattr(retrieval, "get_store", lambda: store)
    original = retrieval.settings.min_chunk_score
    object.__setattr__(retrieval.settings, "min_chunk_score", 0.05)     # bag-of-words cosines are small; scale the floor
    yield retrieval
    object.__setattr__(retrieval.settings, "min_chunk_score", original)


@pytest.fixture
def settings_override():
    """Temporarily change fields of the (frozen) settings object; always restored."""
    from config import settings
    saved = {}

    def apply(**changes):
        for key, value in changes.items():
            saved.setdefault(key, getattr(settings, key))
            object.__setattr__(settings, key, value)

    yield apply
    for key, value in saved.items():
        object.__setattr__(settings, key, value)


# --- markers: `pytest -m unit`, `pytest -m "api or integration"` ------------------------------------------
_API_FILES = {"test_api.py", "test_assistant.py"}
_INTEGRATION_FILES = {"test_retrieval_relevance.py", "test_llm_and_data_paths.py", "test_vector_store.py"}


def pytest_collection_modifyitems(items):
    for item in items:
        name = item.path.name
        item.add_marker(pytest.mark.api if name in _API_FILES else
                        pytest.mark.integration if name in _INTEGRATION_FILES else pytest.mark.unit)
