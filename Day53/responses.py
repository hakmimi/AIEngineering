"""Response contracts (Day 52): what callers can rely on, documented in OpenAPI and enforced on every response.

`DecisionResponse` is what /decision and /decision/async return; `ModeDecisionResponse` is /decide (the same core plus the mode, the active
configuration and the safety layers that were in force). `ErrorResponse` is the one error shape of the whole API.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas import Decision

LLMStatus = Literal["ok", "skipped", "skipped_fast_path", "unavailable", "rejected_output", "not_used"]


class LLMReviewOut(BaseModel):
    explanation: str
    agrees_with_baseline: bool
    concerns: list[str] = []
    escalate_to_review: bool
    confidence: float = Field(ge=0, le=1)


class BlockedBy(BaseModel):
    model_config = ConfigDict(extra="allow")
    policy_id: str | None = None
    reason: str | None = None


class Usage(BaseModel):
    llm_calls: int = 0
    embedding_calls: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    embedding_tokens: int = 0
    estimated_cost_usd: float = 0.0


class GraphInfo(BaseModel):
    route: Literal["normal", "fallback", "uncertain", "policy", "tool_error"] | str = Field(description="which branch of the workflow handled the case")
    route_reason: str | None = None
    trace: list[str] = Field(description="nodes visited, in order")
    timings_ms: dict[str, float] = {}


class DecisionResponse(BaseModel):
    decision: Decision = Field(description="the final decision; the only field a caller must act on")
    baseline_decision: Decision = Field(description="what the rules alone decided (differs only when the LLM or a control rule made it safer)")
    decision_id: str | None = Field(default=None, description="key of the audit record: GET /decision/audit/{decision_id}")
    audit_recorded: bool | None = Field(default=None, description="false = the decision was made but its audit record could not be written")
    blocked_by: list[BlockedBy] = Field(default=[], description="policies that constrained the outcome")
    guard_override: str | None = Field(default=None, description="set when the final constraint guard changed the outcome")
    changed_by_ai: bool = Field(description="final action differs from the rules-only action")
    llm_status: LLMStatus
    fast_path: str | None = Field(default=None, description="why the LLM was skipped, when it was")
    llm: LLMReviewOut | None = None
    notes: list[str] = []
    usage: Usage = Usage()
    latency_ms: float
    tool_trace: list[dict] = []
    graph: GraphInfo | None = None

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "decision": {"transaction_id": "tx-1001", "action": "route", "selected_provider": "epsilon_local_il", "reason_codes": ["LOW_RISK"],
                     "risk_score": 0.08, "expected_cost": 3.61, "expected_approval_probability": 0.93,
                     "explanation": "Routed to epsilon_local_il: low risk, lowest expected cost among eligible providers."},
        "decision_id": "dec_0123456789abcdef", "audit_recorded": True, "blocked_by": [], "guard_override": None, "changed_by_ai": False,
        "llm_status": "ok", "fast_path": None, "latency_ms": 1650.2, "graph": {"route": "normal", "trace": ["input", "policy_gate", "rules"]}}]})


class ModeDecisionResponse(BaseModel):
    """/decide: the same core for every mode; the extra fields of a mode (e.g. `risk` and `candidates` in baseline) are passed through."""
    model_config = ConfigDict(extra="allow")

    mode: Literal["baseline", "ai", "graph"]
    config: dict = Field(description="the configuration that produced this decision (mode, agent version, model, temperature, thresholds)")
    safety_layers: list[str] = Field(description="which safety mechanisms were active in this mode")
    decision: Decision
    llm_status: LLMStatus | None = None
    decision_id: str | None = None


class ErrorResponse(BaseModel):
    detail: str | list = Field(description="what went wrong (a list of field errors for 422)")
    request_id: str | None = Field(default=None, description="also in the X-Request-ID header and in every log line of the request")


ERROR_RESPONSES = {
    401: {"model": ErrorResponse, "description": "missing or wrong X-API-Key"},
    422: {"model": ErrorResponse, "description": "the transaction failed validation, or an unknown mode was requested"},
    429: {"model": ErrorResponse, "description": "rate limit exceeded"},
    503: {"model": ErrorResponse, "description": "a dependency (the LLM provider) is unavailable and no safe fallback applies"},
}
