"""Response contracts: nothing the service returns is dropped by the response model, examples are valid, errors have one shape."""
import json

import pytest

from responses import DecisionResponse, ErrorResponse, ModeDecisionResponse
from schemas import Transaction


def assert_no_key_lost(payload: dict, model):
    """response_model silently drops undeclared keys - so every key the service produces must be declared."""
    dumped = json.loads(model.model_validate(payload).model_dump_json(exclude_unset=False))
    assert set(payload) <= set(dumped), f"undeclared keys would be dropped: {set(payload) - set(dumped)}"


@pytest.fixture(autouse=True)
def llm(stub_llm):
    stub_llm()


def test_decision_endpoint_matches_the_contract(api, tx_payload):
    body = api.post("/decision", json=tx_payload()).json()
    parsed = DecisionResponse.model_validate(body)
    assert parsed.decision.action.value == "route" and parsed.graph.trace[0] == "input" and parsed.decision_id.startswith("dec_")
    assert set(body) >= {"decision", "baseline_decision", "decision_id", "llm_status", "changed_by_ai", "latency_ms", "usage", "graph"}


def test_no_response_field_is_dropped_by_the_model_for_any_route(make_tx, tx_payload):
    from decision_graph import run_decision_graph
    for changes in ({}, {"country": "KP"}, {"country": "ZZ"}, {"amount": 90000.0}, {"customer_type": "new", "customer_age_days": 1, "amount": 5000.0}):
        assert_no_key_lost(run_decision_graph(make_tx(**changes)).to_dict(), DecisionResponse)


def test_async_endpoint_has_the_same_shape(api, tx_payload):
    sync, asynchronous = api.post("/decision", json=tx_payload()).json(), api.post("/decision/async", json=tx_payload()).json()
    assert set(sync) == set(asynchronous)


def test_decide_endpoint_keeps_mode_specific_fields(api, tx_payload, settings_override):
    settings_override(allowed_modes="baseline,ai,graph")
    baseline = api.post("/decide?mode=baseline", json=tx_payload()).json()
    ModeDecisionResponse.model_validate(baseline)
    assert baseline["mode"] == "baseline" and "risk" in baseline and "candidates" in baseline           # extras pass through
    graph = api.post("/decide", json=tx_payload()).json()
    assert graph["mode"] == "graph" and "graph" in graph and graph["safety_layers"][0] == "policy_gate"


def test_documented_examples_validate():
    schema = DecisionResponse.model_json_schema()["examples"][0]
    DecisionResponse.model_validate({**schema, "baseline_decision": schema["decision"]})
    Transaction.model_validate(Transaction.model_json_schema()["examples"][0])


@pytest.mark.parametrize("path,method,kwargs,status", [
    ("/decision", "post", {"json": {"transaction_id": "x"}}, 422),
    ("/decide?mode=turbo", "post", {"json": "tx"}, 422),
])
def test_validation_errors_share_the_error_shape(api, tx_payload, path, method, kwargs, status):
    if kwargs["json"] == "tx":
        kwargs = {"json": tx_payload()}
    r = getattr(api, method)(path, **kwargs)
    assert r.status_code == status
    ErrorResponse.model_validate(r.json())


def test_auth_and_mode_errors_carry_detail(api, tx_payload, settings_override):
    r = api.post("/decide?mode=baseline", json=tx_payload())
    assert r.status_code == 403 and ErrorResponse.model_validate(r.json()).request_id
    settings_override(app_api_key="k")
    r = api.post("/decision", json=tx_payload())
    assert r.status_code == 401 and "detail" in r.json()


def test_openapi_documents_success_and_error_responses():
    from main import app
    op = app.openapi()["paths"]["/decision"]["post"]["responses"]
    assert {"200", "401", "422", "429", "503"} <= set(op)
    assert app.openapi()["components"]["schemas"]["DecisionResponse"]["properties"]["decision"]["description"]


def test_stored_examples_validate_against_the_contract():
    from config import settings
    files = sorted((settings.base_dir / "docs" / "examples").glob("*.json"))
    assert len(files) >= 4
    for f in files:
        pair = json.loads(f.read_text(encoding="utf8"))
        Transaction.model_validate(pair["request"])
        parsed = DecisionResponse.model_validate(pair["response"])
        assert parsed.decision.transaction_id == pair["request"]["transaction_id"]
