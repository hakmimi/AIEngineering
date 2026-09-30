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
