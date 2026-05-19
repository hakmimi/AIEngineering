import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_ready_returns_dependency_checks():
    response = client.get("/ready")

    assert response.status_code == 200
    assert "checks" in response.json()


def test_search_rejects_empty_query_before_openai_call():
    response = client.post("/search", json={"query": "", "top_k": 4})

    assert response.status_code == 422


def test_search_rejects_too_large_top_k_before_openai_call():
    response = client.post("/search", json={"query": "Jerusalem", "top_k": 999})

    assert response.status_code == 422
