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
    """Every test gets a fresh MemoryStore in tmp_path, so tests never touch data/sessions.json."""
    store = memory.MemoryStore(tmp_path / "sessions.json")
    monkeypatch.setattr(chat, "memory", store)
    monkeypatch.setattr(routes, "memory", store)
    monkeypatch.setattr(assistant, "memory", store)
    return store
