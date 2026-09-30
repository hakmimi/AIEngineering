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


# --- shared building blocks (Day 49) - tests use these instead of re-declaring their own copies ------------------------------------
BASE_TX = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
           "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
           "prior_chargebacks": 0}


@pytest.fixture
def tx_payload():
    """A dict factory for a valid, ordinary transaction: tx_payload(country="KP", amount=50)."""
    return lambda **changes: {**BASE_TX, **changes}


@pytest.fixture
def make_tx(tx_payload):
    """A Transaction factory (validated model) with the same overrides."""
    from schemas import Transaction
    return lambda **changes: Transaction(**tx_payload(**changes))


@pytest.fixture
def stub_llm(monkeypatch):
    """Replace the LLM in both pipelines. stub_llm(review=..., explanation=...) -> list of calls made. No network, ever."""
    import ai_decision
    import decision_graph
    calls = []
    state = {"review": {"explanation": "Explained.", "agrees_with_baseline": True, "concerns": [], "escalate_to_review": False, "confidence": 0.9},
             "explanation": "Check."}

    def fake(prompt, schema, name):
        calls.append(name)
        return state["review"] if name == "decision_review" else {"explanation": state["explanation"]}

    async def afake(prompt, schema, name):
        return fake(prompt, schema, name)

    monkeypatch.setattr(decision_graph, "get_structured", fake)
    monkeypatch.setattr(decision_graph, "aget_structured", afake)
    monkeypatch.setattr(ai_decision, "get_structured", fake)

    def configure(review=None, explanation=None):
        if review is not None:
            state["review"] = {**state["review"], **review}
        if explanation is not None:
            state["explanation"] = explanation
        return calls
    configure.calls = calls
    return configure


@pytest.fixture
def api():
    from fastapi.testclient import TestClient

    import main
    with TestClient(main.app) as client:
        yield client


@pytest.fixture(scope="session", autouse=True)
def stored_data_is_never_modified():
    """Guard for the whole run: no test may write to the committed data files (providers, risk tables, policies, transactions, databases)."""
    watched = [settings.providers_path, settings.risk_tables_path, settings.policies_path, settings.transactions_path]
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in watched if p.exists()}
    yield
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in watched if p.exists()}
    assert before == after, "a test modified stored data files"
