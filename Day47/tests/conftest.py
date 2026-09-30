import pytest

from config import settings


@pytest.fixture
def settings_override():
    """Temporarily change fields of the frozen settings object; always restored."""
    saved = {}

    def apply(**changes):
        for key, value in changes.items():
            saved.setdefault(key, getattr(settings, key))
            object.__setattr__(settings, key, value)

    yield apply
    for key, value in saved.items():
        object.__setattr__(settings, key, value)


@pytest.fixture(autouse=True)
def fast_path_off_by_default(settings_override):
    """Most tests exercise the LLM review, so the fast path is switched off unless a test opts in (tests/test_fast_path.py)."""
    settings_override(fast_path_enabled=False)


class MemoryAuditStore:
    """Same interface as audit.AuditStore but in memory: bulk tests run hundreds of decisions and SQLite file opens are slow on Windows."""

    def __init__(self):
        self.rows = {}

    def save(self, record):
        self.rows[record.decision_id] = record

    def get(self, decision_id):
        from audit import AuditNotFound
        if decision_id not in self.rows:
            raise AuditNotFound(decision_id)
        return self.rows[decision_id]

    def for_transaction(self, transaction_id):
        return [r.decision_id for r in self.rows.values() if r.transaction_id == transaction_id]

    def verify(self, decision_id):
        self.get(decision_id)
        return True

    def count(self):
        return len(self.rows)


@pytest.fixture(autouse=True)
def isolated_audit(monkeypatch):
    """Default: an in-memory audit store, so tests never touch data/audit.db. tests/test_audit.py overrides this with a real SQLite file."""
    import audit
    import decision_graph
    import main
    store = MemoryAuditStore()
    for module in (audit, decision_graph, main):
        monkeypatch.setattr(module, "audit_store", store)
    return store


@pytest.fixture(autouse=True)
def isolated_jobs_db(tmp_path, settings_override):
    """The app's lifespan opens a job database; tests must never touch data/jobs.db."""
    settings_override(jobs_db_path=tmp_path / "jobs.db")
