"""Day 47: layered configuration (default < YAML < environment) and the mode selector."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

import llm
import main
from config import MODES, Settings, load_settings
from modes import ModeNotAllowed, UnknownMode, decide_with_mode, resolve_mode
from schemas import Transaction

BASE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
        "prior_chargebacks": 0}


def yaml_file(tmp_path, text):
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf8")
    return path


# --- layering ----------------------------------------------------------------------------------------------------------------------
def test_shipped_yaml_equals_the_code_defaults():
    """config.yaml documents the defaults - it must never silently differ from them."""
    assert load_settings(env={}).snapshot() == Settings().snapshot() | {"audit_db_path": str(load_settings(env={}).audit_db_path),
                                                                          "jobs_db_path": str(load_settings(env={}).jobs_db_path)}


def test_yaml_overrides_defaults_and_environment_overrides_yaml(tmp_path):
    cfg = yaml_file(tmp_path, "llm_model: yaml-model\nllm_temperature: 0.3\nrisk_review: 0.5\n")
    s = load_settings(env={}, config_file=cfg)
    assert (s.llm_model, s.llm_temperature, s.risk_review) == ("yaml-model", 0.3, 0.5) and s.risk_decline == 0.70      # untouched = default
    s = load_settings(env={"LLM_MODEL": "env-model", "RISK_REVIEW": "0.55"}, config_file=cfg)
    assert (s.llm_model, s.llm_temperature, s.risk_review) == ("env-model", 0.3, 0.55)


@pytest.mark.parametrize("field,raw,expected", [
    ("risk_review", "0.6", 0.6), ("job_workers", "8", 8), ("fast_path_enabled", "false", False), ("fast_path_enabled", "1", True),
    ("allow_simulated_delay", "yes", True), ("llm_model", "m", "m"), ("max_amount", "500", 500.0),
])
def test_environment_strings_are_cast_to_the_field_type(field, raw, expected):
    value = getattr(load_settings(env={field.upper(): raw}, config_file="missing.yaml"), field)
    assert value == expected and type(value) is type(expected)


@pytest.mark.parametrize("field,raw", [("risk_review", "high"), ("job_workers", "many"), ("fast_path_enabled", "maybe")])
def test_bad_values_fail_loudly_at_start_up(field, raw):
    with pytest.raises(ValueError):
        load_settings(env={field.upper(): raw}, config_file="missing.yaml")


def test_legacy_alias_and_empty_variables(tmp_path):
    assert load_settings(env={"FAST_PATH": "0"}, config_file="missing.yaml").fast_path_enabled is False
    assert load_settings(env={"LLM_MODEL": ""}, config_file="missing.yaml").llm_model == "gpt-4.1-mini"      # empty = not set


def test_yaml_typos_and_secrets_are_ignored_with_a_warning(tmp_path, caplog):
    cfg = yaml_file(tmp_path, "llm_modle: typo\nopenai_api_key: sk-should-not-be-here\nllm_model: ok-model\n")
    with caplog.at_level(logging.WARNING, logger="config"):
        s = load_settings(env={}, config_file=cfg)
    assert s.llm_model == "ok-model" and s.openai_api_key is None
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "llm_modle" in text and "config_secret_in_file" in text and "sk-should" not in text


def test_secrets_come_from_the_environment_only():
    s = load_settings(env={"OPENAI_API_KEY": "sk-env", "APP_API_KEY": "k"}, config_file="missing.yaml")
    assert s.openai_api_key == "sk-env" and s.app_api_key == "k"


def test_invalid_yaml_structure_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="mapping"):
        load_settings(env={}, config_file=yaml_file(tmp_path, "- just\n- a list\n"))


def test_config_file_can_be_selected_by_environment(tmp_path):
    cfg = yaml_file(tmp_path, "llm_model: experiment-model\n")
    assert load_settings(env={"CONFIG_FILE": str(cfg)}).llm_model == "experiment-model"


# --- data paths --------------------------------------------------------------------------------------------------------------------------
def test_data_paths_follow_data_dir_and_file_names(tmp_path):
    s = load_settings(env={"DATA_DIR": str(tmp_path), "PROVIDERS_FILE": "p2.json"}, config_file="missing.yaml")
    assert s.providers_path == tmp_path / "p2.json" and s.risk_tables_path == tmp_path / "risk_tables.json"
    assert s.audit_db_path == tmp_path / "audit.db" and s.jobs_db_path == tmp_path / "jobs.db" and s.policies_path == tmp_path / "policies.json"


def test_explicit_db_paths_win_over_data_dir(tmp_path):
    s = load_settings(env={"DATA_DIR": str(tmp_path), "AUDIT_DB_PATH": str(tmp_path / "x" / "a.db")}, config_file="missing.yaml")
    assert s.audit_db_path == tmp_path / "x" / "a.db" and s.jobs_db_path == tmp_path / "jobs.db"


# --- snapshot ------------------------------------------------------------------------------------------------------------------------------
def test_snapshot_never_contains_secrets_but_says_whether_they_exist():
    s = load_settings(env={"OPENAI_API_KEY": "sk-secret-value", "APP_API_KEY": "another-secret"}, config_file="missing.yaml")
    snap = s.snapshot()
    assert "sk-secret-value" not in json.dumps(snap) and "another-secret" not in json.dumps(snap)
    assert snap["openai_api_key_configured"] is True and snap["app_api_key_configured"] is True and "openai_api_key" not in snap
    json.dumps(snap)                                            # fully JSON-serialisable


# --- mode validation -------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("env,message", [
    ({"DECISION_MODE": "turbo"}, "decision_mode"), ({"ALLOWED_MODES": "graph,warp"}, "allowed_modes"),
    ({"DECISION_MODE": "ai"}, "include decision_mode"),            # the default mode must be enabled
])
def test_invalid_mode_configuration_is_refused(env, message):
    with pytest.raises(ValueError, match=message):
        load_settings(env=env, config_file="missing.yaml")


def test_valid_mode_configuration():
    s = load_settings(env={"DECISION_MODE": "ai", "ALLOWED_MODES": "baseline, ai ,graph"}, config_file="missing.yaml")
    assert s.decision_mode == "ai" and s.enabled_modes == ("baseline", "ai", "graph")


# --- the selector ----------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def all_modes(settings_override):
    settings_override(allowed_modes="baseline,ai,graph", fast_path_enabled=False)


@pytest.fixture(autouse=True)
def fake_llm(stub_llm):
    return stub_llm.calls


def test_default_mode_is_graph_and_production_refuses_the_experimental_modes():
    assert resolve_mode(None) == "graph" and resolve_mode("graph") == "graph"
    with pytest.raises(ModeNotAllowed) as exc:
        resolve_mode("baseline")
    assert exc.value.status_code == 403 and "allowed: graph" in exc.value.message
    with pytest.raises(UnknownMode) as exc2:
        resolve_mode("turbo")
    assert exc2.value.status_code == 422


def test_each_mode_runs_its_own_machinery(all_modes, fake_llm):
    tx = Transaction(**BASE)
    baseline = decide_with_mode(tx, "baseline")
    assert baseline["mode"] == "baseline" and baseline["llm_status"] == "not_used" and fake_llm == [] and baseline["config"]["llm_model"] is None
    assert baseline["decision"]["explanation"].startswith("Routed to") and "audit" not in baseline["safety_layers"]
    ai = decide_with_mode(tx, "ai")
    assert ai["mode"] == "ai" and ai["llm_status"] == "ok" and fake_llm == ["decision_review"] and "tool_trace" in ai and "graph" not in ai
    graph = decide_with_mode(tx, "graph")
    assert graph["mode"] == "graph" and graph["decision_id"].startswith("dec_") and graph["graph"]["trace"][0] == "input" and "audit" in graph["safety_layers"]


def test_all_modes_agree_on_an_ordinary_payment(all_modes):
    tx = Transaction(**BASE)
    decisions = {m: decide_with_mode(tx, m)["decision"] for m in MODES}
    assert {d["action"] for d in decisions.values()} == {"route"} and {d["selected_provider"] for d in decisions.values()} == {"epsilon_local_il"}


def test_only_the_graph_mode_has_the_safety_layers(all_modes):
    sanctioned = Transaction(**{**BASE, "country": "KP"})
    assert decide_with_mode(sanctioned, "graph")["decision"]["action"] == "decline"
    # without the policy gate the rules alone do NOT decline a sanctioned country - exactly why production runs graph only
    assert decide_with_mode(sanctioned, "baseline")["decision"]["action"] != "decline"
    assert decide_with_mode(sanctioned, "ai")["decision"]["action"] != "decline"


def test_the_mode_falls_back_to_the_configured_default(settings_override):
    settings_override(allowed_modes="baseline,graph", decision_mode="baseline")
    assert decide_with_mode(Transaction(**BASE))["mode"] == "baseline"


def test_a_disabled_mode_is_refused_before_any_work_is_done(fake_llm):
    with pytest.raises(ModeNotAllowed):
        decide_with_mode(Transaction(**BASE), "ai")
    assert fake_llm == []


def test_active_config_is_logged_for_every_run(all_modes, caplog):
    with caplog.at_level(logging.INFO):
        decide_with_mode(Transaction(**BASE), "ai")
    line = next(r.getMessage() for r in caplog.records if "run_config" in r.getMessage())
    assert "mode=ai" in line and "agent_version=v3" in line and "llm_model=gpt-4.1-mini" in line and "llm_temperature=0.0" in line


def test_the_model_and_temperature_reach_the_llm_call(monkeypatch, settings_override):
    seen = {}

    class Responses:
        def create(self, **kw):
            seen.update(kw)
            return type("R", (), {"output_text": "{}", "usage": None})()

    monkeypatch.setattr(llm, "get_client", lambda: type("C", (), {"responses": Responses()})())
    settings_override(llm_model="other-model", llm_temperature=0.4)
    llm._call_once("p", {"type": "object"}, "x")
    assert seen["model"] == "other-model" and seen["temperature"] == 0.4


# --- API -------------------------------------------------------------------------------------------------------------------------------------
client = TestClient(main.app)


def test_decide_endpoint_defaults_to_graph_and_reports_mode_and_config():
    body = client.post("/decide", json=BASE).json()
    assert body["mode"] == "graph" and body["config"]["agent_version"] == "v3" and body["decision"]["action"] == "route"


def test_decide_endpoint_mode_gating_and_validation(settings_override):
    assert client.post("/decide?mode=baseline", json=BASE).status_code == 403
    assert client.post("/decide?mode=turbo", json=BASE).status_code == 422
    settings_override(allowed_modes="baseline,graph")
    r = client.post("/decide?mode=baseline", json=BASE)
    assert r.status_code == 200 and r.json()["mode"] == "baseline"
    assert client.post("/decide", json={**BASE, "amount": -1}).status_code == 422


def test_config_endpoint_is_safe_and_protected(settings_override):
    body = client.get("/config").json()
    assert body["enabled_modes"] == ["graph"] and body["settings"]["llm_model"] == "gpt-4.1-mini" and "openai_api_key" not in body["settings"]
    settings_override(app_api_key="s3cret", openai_api_key="sk-must-not-leak")
    assert client.get("/config").status_code == 401
    ok = client.get("/config", headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 200 and "sk-must-not-leak" not in ok.text and "s3cret" not in ok.text
