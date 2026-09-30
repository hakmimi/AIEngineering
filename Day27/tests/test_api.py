"""API-level tests: every endpoint through FastAPI's TestClient - validation, auth, rate limit, errors, contract."""
import pytest
from fastapi.testclient import TestClient

import routes
import security
from main import app

client = TestClient(app, raise_server_exceptions=False)
CHUNK = {"doc_id": 1, "chunk_id": 0, "topic": "Masada", "text": "Masada is a fortress.", "score": 0.9, "similarity": 0.9}


@pytest.fixture(autouse=True)
def clean_rate_limiter():
    security._requests_by_client.clear()
    yield
    security._requests_by_client.clear()


@pytest.fixture
def fake_graph(monkeypatch):
    monkeypatch.setattr(routes, "run_graph", lambda q, k, s=None: {"question": q, "answer": "ok", "source": "rag", "top_k": k})


# --- health / readiness -----------------------------------------------------------------------------------
def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_reports_checks_and_degrades_without_a_key(settings_override):
    settings_override(openai_api_key=None)
    body = client.get("/ready").json()
    assert body["status"] == "degraded" and body["checks"]["openai_api_key"] is False


def test_ready_is_ready_when_everything_exists(settings_override):
    settings_override(openai_api_key="sk-test")
    body = client.get("/ready").json()
    assert body["status"] == "ready" and body["checks"]["docs_file"] and body["checks"]["embedded_chunks_file"]


def test_docs_count():
    assert client.get("/docs-count").json()["documents"] == 53


# --- validation ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("payload", [
    {}, {"query": ""}, {"query": "x" * 1001}, {"query": "hi", "top_k": 0}, {"query": "hi", "top_k": 11},
    {"query": "hi", "top_k": "many"}, {"query": 123}, {"top_k": 3},
])
def test_invalid_payloads_return_422(payload, fake_graph):
    assert client.post("/rag/graph", json=payload).status_code == 422


def test_non_json_body_is_rejected(fake_graph):
    assert client.post("/rag/graph", content="not json", headers={"content-type": "application/json"}).status_code == 422


def test_unknown_route_and_wrong_method():
    assert client.get("/nope").status_code == 404
    assert client.get("/rag/graph").status_code == 405


def test_defaults_are_applied(fake_graph):
    assert client.post("/rag/graph", json={"query": "hello"}).json()["results"]["top_k"] == 4


# --- authentication -------------------------------------------------------------------------------------------
def test_auth_disabled_by_default(fake_graph, settings_override):
    settings_override(app_api_key=None)
    assert client.post("/rag/graph", json={"query": "hello"}).status_code == 200


def test_missing_or_wrong_key_is_rejected_when_auth_is_on(fake_graph, settings_override):
    settings_override(app_api_key="s3cret")
    assert client.post("/rag/graph", json={"query": "hello"}).status_code == 401
    assert client.post("/rag/graph", json={"query": "hello"}, headers={"X-API-Key": "wrong"}).status_code == 401


def test_correct_key_is_accepted(fake_graph, settings_override):
    settings_override(app_api_key="s3cret")
    assert client.post("/rag/graph", json={"query": "hello"}, headers={"X-API-Key": "s3cret"}).status_code == 200


def test_health_stays_public_when_auth_is_on(settings_override):
    settings_override(app_api_key="s3cret")
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("method,path,body", [
    ("post", "/search", {"query": "masada"}), ("post", "/rag", {"query": "masada"}), ("post", "/chat", {"session_id": "a", "query": "hi there"}),
    ("post", "/ask", {"session_id": "a", "query": "hi there"}), ("get", "/session/a", None), ("delete", "/session/a", None),
])
def test_every_protected_endpoint_requires_the_key(method, path, body, settings_override):
    settings_override(app_api_key="s3cret")
    response = getattr(client, method)(path, **({"json": body} if body else {}))
    assert response.status_code == 401


# --- rate limiting ----------------------------------------------------------------------------------------------
def test_rate_limit_returns_429_after_the_quota(fake_graph, settings_override):
    settings_override(rate_limit_per_minute=3)
    codes = [client.post("/rag/graph", json={"query": "hello"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_rate_limit_window_expires(fake_graph, settings_override, monkeypatch):
    settings_override(rate_limit_per_minute=1)
    now = [1000.0]
    monkeypatch.setattr(security.time, "time", lambda: now[0])
    assert client.post("/rag/graph", json={"query": "hello"}).status_code == 200
    assert client.post("/rag/graph", json={"query": "hello"}).status_code == 429
    now[0] += 61
    assert client.post("/rag/graph", json={"query": "hello"}).status_code == 200


# --- error handling & contract ----------------------------------------------------------------------------------
def test_unexpected_errors_never_leak_details(monkeypatch):
    monkeypatch.setattr(routes, "run_graph", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret internals")))
    response = client.post("/rag/graph", json={"query": "hello there"})
    assert response.status_code == 500 and "secret internals" not in response.text
    assert set(response.json()) == {"detail", "request_id"}


def test_app_errors_use_their_status_code(monkeypatch):
    from errors import ExternalServiceError
    monkeypatch.setattr(routes, "run_graph", lambda *a, **k: (_ for _ in ()).throw(ExternalServiceError()))
    assert client.post("/rag/graph", json={"query": "hello there"}).status_code == 503


def test_search_endpoint_returns_results(monkeypatch):
    monkeypatch.setattr(routes, "get_relevant_chunks", lambda q, k, f=None: [CHUNK])
    assert client.post("/search", json={"query": "masada", "category": "history"}).json() == {"results": [CHUNK]}


def test_openapi_lists_the_public_surface():
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {"/health", "/ready", "/rag/graph", "/rag", "/ask", "/chat", "/search", "/session/{session_id}"} <= paths


def test_responses_carry_tracing_headers():
    r = client.get("/health")
    assert r.headers["x-request-id"] and float(r.headers["x-process-time-ms"]) >= 0
