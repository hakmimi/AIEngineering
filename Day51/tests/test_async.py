"""Day 44: the async decision path - same decisions as the sync path, non-blocking behaviour, retries, warm-up."""
import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

import ai_decision
import decision_graph
import llm
import main
import resilience
from data_loader import iter_transactions
from decision_graph import arun_decision_graph, run_decision_graph
from errors import ConfigurationError, ExternalServiceError
from schemas import Action, Transaction

BASE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
        "prior_chargebacks": 0}
REVIEW = {"explanation": "Explained.", "agrees_with_baseline": True, "concerns": [], "escalate_to_review": False, "confidence": 0.9}


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    """Sync and async fakes return the same payloads and record which flavour was used."""
    calls = {"sync": 0, "async": 0}

    def payload(name):
        return REVIEW if name == "decision_review" else {"explanation": "Check the account history."}

    def sync(prompt, schema, name):
        calls["sync"] += 1
        return payload(name)

    async def asyn(prompt, schema, name):
        calls["async"] += 1
        await asyncio.sleep(0)
        return payload(name)

    monkeypatch.setattr(decision_graph, "get_structured", sync)
    monkeypatch.setattr(decision_graph, "aget_structured", asyn)
    monkeypatch.setattr(ai_decision, "get_structured", sync)
    return calls


def run(coro):
    return asyncio.run(coro)


# --- equivalence -----------------------------------------------------------------------------------------------------------------
def test_async_decisions_equal_sync_decisions_on_many_transactions():
    async def go():
        for tx in iter_transactions(limit=150):
            a = await arun_decision_graph(tx)
            s = run_decision_graph(tx)
            assert (a.decision.action, a.decision.selected_provider, a.decision.reason_codes) == \
                   (s.decision.action, s.decision.selected_provider, s.decision.reason_codes), tx.transaction_id
            assert a.graph_trace == s.graph_trace and a.graph_route == s.graph_route and a.llm_status == s.llm_status
    run(go())


def test_async_path_uses_only_the_async_llm(fake_llm, settings_override):
    settings_override(fast_path_enabled=False)
    result = run(arun_decision_graph(Transaction(**BASE)))
    assert result.llm_status == "ok" and fake_llm == {"sync": 0, "async": 1}
    run_decision_graph(Transaction(**BASE))
    assert fake_llm == {"sync": 1, "async": 1}


def test_uncertainty_node_is_async_too(fake_llm, monkeypatch, settings_override):
    settings_override(fast_path_enabled=False)
    disagree = {**REVIEW, "agrees_with_baseline": False}

    async def adisagree(prompt, schema, name):
        fake_llm["async"] += 1
        return disagree if name == "decision_review" else {"explanation": "Check the account history."}

    monkeypatch.setattr(decision_graph, "aget_structured", adisagree)
    r = run(arun_decision_graph(Transaction(**BASE)))
    assert r.graph_route == "uncertain" and r.decision.action is Action.MANUAL_REVIEW and fake_llm["async"] == 2
    assert r.decision.explanation == "Check the account history."


def test_llm_failure_in_the_async_path_degrades_like_the_sync_path(monkeypatch, settings_override):
    settings_override(fast_path_enabled=False)

    async def boom(prompt, schema, name):
        raise ExternalServiceError()

    monkeypatch.setattr(decision_graph, "aget_structured", boom)
    r = run(arun_decision_graph(Transaction(**BASE)))
    assert r.llm_status == "unavailable" and r.decision.action is Action.ROUTE and r.decision.explanation.startswith("Routed to")


def test_usage_decision_id_and_audit_survive_the_async_path(isolated_audit, settings_override):
    settings_override(fast_path_enabled=False)
    r = run(arun_decision_graph(Transaction(**BASE)))
    assert r.decision_id.startswith("dec_") and r.audit_recorded and isolated_audit.get(r.decision_id).final_action == "route"
    from observability import decision_id_var
    assert decision_id_var.get() == "-"                                              # context is clean afterwards


def test_concurrent_async_decisions_do_not_mix_up_ids_or_usage(isolated_audit):
    async def go():
        txs = [Transaction(**{**BASE, "transaction_id": f"c-{i}", "amount": 100 + i}) for i in range(20)]
        return await asyncio.gather(*(arun_decision_graph(t) for t in txs))
    results = run(go())
    assert len({r.decision_id for r in results}) == 20
    for r in results:
        assert isolated_audit.get(r.decision_id).transaction_id == r.decision.transaction_id


# --- async node plumbing -----------------------------------------------------------------------------------------------------------
def test_timed_keeps_coroutine_functions_awaitable_and_sync_functions_sync():
    import inspect
    assert inspect.iscoroutinefunction(decision_graph.allm_node) and not inspect.iscoroutinefunction(decision_graph.llm_node)
    assert inspect.iscoroutinefunction(decision_graph.auncertainty_node)


def test_sync_and_async_graphs_have_the_same_shape():
    a = decision_graph.async_decision_graph.get_graph()
    s = decision_graph.decision_graph.get_graph()
    assert set(a.nodes) == set(s.nodes) and {(e.source, e.target) for e in a.edges} == {(e.source, e.target) for e in s.edges}


# --- async LLM call and async retry ---------------------------------------------------------------------------------------------------
def _usage():
    return SimpleNamespace(input_tokens=10, output_tokens=2)


def test_aget_structured_returns_json_and_records_usage(monkeypatch):
    async def create(**kw):
        return SimpleNamespace(output_text='{"a": 1}', usage=_usage())

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(llm, "get_async_client", lambda: client)
    from usage import start_tracking, stop_tracking
    tracker, token = start_tracking()
    assert run(llm.aget_structured("p", {"type": "object"}, "x")) == {"a": 1}
    stop_tracking(token)
    assert tracker.summary()["llm_input_tokens"] == 10


@pytest.mark.parametrize("output", ["not json", ""])
def test_aget_structured_rejects_invalid_json_after_retries(monkeypatch, output):
    calls = {"n": 0}

    async def create(**kw):
        calls["n"] += 1
        return SimpleNamespace(output_text=output, usage=None)

    monkeypatch.setattr(llm, "get_async_client", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    with pytest.raises(ExternalServiceError):
        run(llm.aget_structured("p", {}, "x"))
    assert calls["n"] == 3                                                            # retryable: RETRY_ATTEMPTS tries


def test_async_retry_recovers_and_stops_on_non_retryable_errors():
    state = {"n": 0}

    async def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise ExternalServiceError()
        return "ok"

    assert run(resilience.aretry_call(flaky, label="t", base_delay=0)) == "ok" and state["n"] == 3

    async def fatal():
        state["n"] += 1
        raise ExternalServiceError(retryable=False)

    state["n"] = 0
    with pytest.raises(ExternalServiceError):
        run(resilience.aretry_call(fatal, label="t", base_delay=0))
    assert state["n"] == 1


def test_async_client_needs_a_key(settings_override, monkeypatch):
    import openai_client
    monkeypatch.setattr(openai_client, "_async_client", None)
    settings_override(openai_api_key=None)
    with pytest.raises(ConfigurationError):
        openai_client.get_async_client()
    settings_override(openai_api_key="sk-test")
    assert openai_client.get_async_client() is openai_client.get_async_client()


# --- the event loop: proper async vs the anti-pattern -----------------------------------------------------------------------------------
def test_naive_async_endpoint_serialises_requests_while_the_proper_one_overlaps(monkeypatch):
    """Deterministic proof without any LLM: a 0.2 s 'model call' - blocking (time.sleep) vs awaited (asyncio.sleep)."""
    def fake_result():
        return SimpleNamespace(to_dict=lambda: {"ok": True})

    def blocking(tx):
        time.sleep(0.2)
        return fake_result()

    async def awaiting(tx):
        await asyncio.sleep(0.2)
        return fake_result()

    monkeypatch.setattr(main, "run_decision_graph", blocking)
    monkeypatch.setattr(main, "arun_decision_graph", awaiting)

    async def burst(path):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = time.perf_counter()
            responses = await asyncio.gather(*(client.post(path, json=BASE) for _ in range(5)))
            return time.perf_counter() - started, [r.status_code for r in responses]

    naive_s, codes = run(burst("/decision/async-naive"))
    proper_s, codes2 = run(burst("/decision/async"))
    assert codes == codes2 == [200] * 5
    assert naive_s >= 0.95 and proper_s < 0.6                # 5 x 0.2 s serialised vs ~0.2 s overlapped


def test_event_loop_stays_responsive_during_awaited_work_but_not_during_blocking_work(monkeypatch):
    """A ticker task measures the longest gap between loop iterations while a slow request is in flight (this is what /health feels)."""
    async def awaiting(tx):
        await asyncio.sleep(0.5)
        return SimpleNamespace(to_dict=lambda: {})

    def blocking(tx):
        time.sleep(0.5)
        return SimpleNamespace(to_dict=lambda: {})

    monkeypatch.setattr(main, "arun_decision_graph", awaiting)
    monkeypatch.setattr(main, "run_decision_graph", blocking)

    async def longest_stall(path):
        gaps, stop = [], asyncio.Event()

        async def ticker():
            last = time.perf_counter()
            while not stop.is_set():
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tick = asyncio.create_task(ticker())
            await client.post(path, json=BASE)
            stop.set()
            await tick
        return max(gaps)

    assert run(longest_stall("/decision/async")) < 0.15 and run(longest_stall("/decision/async-naive")) >= 0.45


# --- endpoints and start-up ----------------------------------------------------------------------------------------------------------------
def test_async_endpoint_returns_the_same_payload_shape_as_the_sync_one(settings_override):
    settings_override(fast_path_enabled=False)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            return (await client.post("/decision", json=BASE)).json(), (await client.post("/decision/async", json=BASE)).json()

    sync_body, async_body = run(go())
    assert set(sync_body) == set(async_body)
    assert async_body["decision"]["action"] == sync_body["decision"]["action"] and async_body["graph"]["trace"] == sync_body["graph"]["trace"]


def test_async_endpoints_validate_and_authenticate(settings_override):
    async def go(headers=None, body=BASE):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            return (await client.post("/decision/async", json=body, headers=headers or {})).status_code

    assert run(go(body={**BASE, "amount": -1})) == 422
    settings_override(app_api_key="s3cret")
    assert run(go()) == 401 and run(go({"X-API-Key": "s3cret"})) == 200


def test_lifespan_warms_the_clients_and_tolerates_a_missing_key(monkeypatch):
    warmed = []
    monkeypatch.setattr(main, "get_client", lambda: warmed.append("sync"))
    monkeypatch.setattr(main, "get_async_client", lambda: warmed.append("async"))

    async def enter():
        async with main.lifespan(main.app):
            pass

    run(enter())
    assert warmed == ["sync", "async"]

    def no_key():
        raise ConfigurationError("no key")

    monkeypatch.setattr(main, "get_client", no_key)
    run(enter())                                                                          # must not raise


def test_json_round_trip_of_an_async_result():
    r = run(arun_decision_graph(Transaction(**BASE)))
    assert json.loads(json.dumps(r.to_dict()))["decision"]["action"] == "route"
