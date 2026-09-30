"""Decision modes - one entry point, three levels of machinery, chosen by configuration.

    baseline  rules only (Day 31): risk rules, eligibility, scoring, template explanation. No LLM, no policies, no fallback routes.
    ai        rules + audited tools + LLM review (Day 32/33). No policy gate, fallback route or audit trail.
    graph     the full workflow (Day 34-45): policies, fallback + uncertainty routes, pattern rules, fast path, guard, audit.

`baseline` and `ai` exist for experiments and evaluation (same code, different config); they LACK the safety layers, so production keeps
`allowed_modes: graph` (the default) and a request for another mode is refused with 403. Every run logs the active configuration, so a
result can always be tied to the mode, model, temperature and agent version that produced it.
"""
import logging

from ai_decision import decide_ai
from config import MODES, settings
from decision_engine import decide_baseline
from decision_graph import run_decision_graph
from errors import AppError
from explanations import template_explanation
from observability import log_event
from schemas import Transaction
from version import AGENT_VERSION

logger = logging.getLogger("modes")

SAFETY_LAYERS = {
    "baseline": ["rules"],
    "ai": ["rules", "tools", "llm_control_rules"],
    "graph": ["policy_gate", "input_routing", "rules", "pattern_rules", "tools", "llm_control_rules", "uncertainty_route", "constraint_guard",
              "audit"],
}


class ModeNotAllowed(AppError):
    def __init__(self, mode: str, allowed: tuple[str, ...]):
        super().__init__(f"mode '{mode}' is not enabled (allowed: {', '.join(allowed)})", status_code=403)


class UnknownMode(AppError):
    def __init__(self, mode: str):
        super().__init__(f"unknown mode '{mode}' (choose from {', '.join(MODES)})", status_code=422)


def resolve_mode(requested: str | None) -> str:
    mode = requested or settings.decision_mode
    if mode not in MODES:
        raise UnknownMode(mode)
    if mode not in settings.enabled_modes:
        raise ModeNotAllowed(mode, settings.enabled_modes)
    return mode


def active_config(mode: str) -> dict:
    """The parts of the configuration that determine a decision's behaviour (logged per run and returned with every response)."""
    return {"mode": mode, "agent_version": AGENT_VERSION, "llm_model": settings.llm_model if mode != "baseline" else None,
            "llm_temperature": settings.llm_temperature if mode != "baseline" else None,
            "fast_path_enabled": settings.fast_path_enabled if mode == "graph" else None,
            "risk_decline": settings.risk_decline, "risk_review": settings.risk_review}


def decide_with_mode(tx: Transaction, mode: str | None = None) -> dict:
    mode = resolve_mode(mode)
    config = active_config(mode)
    log_event(logger, "run_config", transaction_id=tx.transaction_id, **config)
    if mode == "baseline":
        result = decide_baseline(tx)
        result.decision.explanation = template_explanation(result.decision)
        payload = {**result.to_dict(), "llm_status": "not_used"}
    elif mode == "ai":
        payload = decide_ai(tx).to_dict()
    else:
        payload = run_decision_graph(tx).to_dict()
    return {"mode": mode, "config": config, "safety_layers": SAFETY_LAYERS[mode], **payload}
