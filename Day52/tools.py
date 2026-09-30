"""Tool layer for the decision agent: risk_lookup, provider_lookup, cost_estimate.

Why tools instead of "just pass data in the prompt"?
* they compute exact things (fees, eligibility, risk) outside the LLM;
* each call has a validated input model and a validated output, and leaves a trace (name, arguments, result, ms);
* the trace is shown to the LLM and returned to the API caller, so an explanation can be checked against what the agent
  actually looked up.
"""
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from data_loader import get_provider, load_providers, load_risk_tables
from errors import DataStoreError
from observability import log_event, summarize
from risk import compute_risk
from schemas import Currency, CustomerType, MerchantCategory, PaymentMethod, Transaction

logger = logging.getLogger("tools")


# --- inputs ---------------------------------------------------------------------------------------------------------
class RiskLookupInput(BaseModel):
    """The transaction fields that determine risk (a Transaction dict is accepted as-is)."""
    country: str = Field(min_length=2, max_length=2)
    merchant_category: MerchantCategory
    customer_type: CustomerType
    amount: float = Field(gt=0)
    currency: Currency
    prior_chargebacks: int = Field(default=0, ge=0)


class ProviderLookupInput(BaseModel):
    country: str = Field(min_length=2, max_length=2)
    currency: Currency
    payment_method: PaymentMethod
    amount: float = Field(gt=0)
    risk: float = Field(ge=0, le=1)


class CostEstimateInput(BaseModel):
    provider_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    risk: float = Field(ge=0, le=1)


# --- implementations ----------------------------------------------------------------------------------------------------
def _risk_lookup(args: RiskLookupInput) -> dict:
    tx = Transaction(transaction_id="tool-call", timestamp="2026-01-01T00:00:00Z", amount=args.amount, currency=args.currency,
                     country=args.country, merchant_category=args.merchant_category, customer_type=args.customer_type,
                     payment_method=PaymentMethod.CARD, customer_age_days=0 if args.customer_type is CustomerType.NEW else 400,
                     prior_chargebacks=args.prior_chargebacks)
    assessment = compute_risk(tx)
    tables = load_risk_tables()
    return {"risk_score": assessment.score, "components": assessment.components,
            "country_known": args.country in tables["country_risk"], "reason_codes": [r.value for r in assessment.reason_codes]}


def _provider_lookup(args: ProviderLookupInput) -> dict:
    from decision_engine import ineligible_reason  # local import: decision_engine depends on this module's gatherer
    tx = Transaction(transaction_id="tool-call", timestamp="2026-01-01T00:00:00Z", amount=args.amount, currency=args.currency,
                     country=args.country, merchant_category=MerchantCategory.GROCERIES, customer_type=CustomerType.RETURNING,
                     payment_method=args.payment_method, customer_age_days=400)
    eligible, rejected = [], {}
    for provider in load_providers():
        cause = ineligible_reason(provider, tx, args.risk)
        if cause:
            rejected[provider.provider_id] = cause
        else:
            eligible.append(provider.provider_id)
    return {"eligible": eligible, "rejected": rejected}


def _cost_estimate(args: CostEstimateInput) -> dict:
    from decision_engine import score_provider
    provider = get_provider(args.provider_id)
    tx = Transaction(transaction_id="tool-call", timestamp="2026-01-01T00:00:00Z", amount=args.amount, currency=Currency.USD,
                     country="US", merchant_category=MerchantCategory.GROCERIES, customer_type=CustomerType.RETURNING,
                     payment_method=PaymentMethod.CARD, customer_age_days=400)
    candidate = score_provider(provider, tx, args.risk)
    return {"provider_id": provider.provider_id, "expected_cost": candidate.expected_cost,
            "expected_approval_probability": candidate.expected_approval_probability, "score": candidate.score,
            "latency_ms": candidate.latency_ms}


# --- output contracts (a tool result is checked before anything uses it) --------------------------------------------------------
def _check_risk(out: dict) -> None:
    if not (isinstance(out["risk_score"], float) and 0 <= out["risk_score"] <= 1 and math.isfinite(out["risk_score"])):
        raise ValueError("risk_score out of range")


def _check_providers(out: dict) -> None:
    known = {p.provider_id for p in load_providers()}
    if not set(out["eligible"]) <= known or set(out["eligible"]) & set(out["rejected"]):
        raise ValueError("inconsistent provider lists")


def _check_cost(out: dict) -> None:
    if out["expected_cost"] < 0 or not (0 <= out["expected_approval_probability"] <= 1):
        raise ValueError("cost/approval out of range")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    fn: Callable[[BaseModel], dict]
    check_output: Callable[[dict], None]


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("risk_lookup", "Risk score and components for a customer/transaction profile", RiskLookupInput, _risk_lookup, _check_risk),
    Tool("provider_lookup", "Providers that can carry a payment, and why the others cannot", ProviderLookupInput, _provider_lookup, _check_providers),
    Tool("cost_estimate", "Fee, approval probability and score for one provider", CostEstimateInput, _cost_estimate, _check_cost),
)}


@dataclass
class ToolResult:
    ok: bool
    output: dict | None = None
    error: str | None = None


@dataclass
class ToolTrace:
    """Ordered record of every tool call made for one decision."""
    calls: list[dict] = field(default_factory=list)

    def add(self, name: str, args: dict, result: ToolResult, ms: float) -> None:
        self.calls.append({"tool": name, "arguments": args, "ok": result.ok, "output": result.output, "error": result.error,
                           "ms": round(ms, 2)})

    def for_prompt(self) -> list[dict]:
        return [{"tool": c["tool"], "arguments": c["arguments"], "result": c["output"] if c["ok"] else {"error": c["error"]}}
                for c in self.calls]


def execute_tool(name: str, arguments: dict, trace: ToolTrace | None = None) -> ToolResult:
    """Validate the arguments, run the tool, validate the output, log and trace the call. Never raises."""
    started = time.perf_counter()
    tool = TOOLS.get(name)
    try:
        if tool is None:
            raise KeyError(f"unknown tool '{name}'")
        output = tool.fn(tool.input_model(**arguments))
        tool.check_output(output)
        result = ToolResult(True, output)
    except ValidationError as exc:
        result = ToolResult(False, error=f"invalid arguments: {exc.errors()[0]['loc'][0]}: {exc.errors()[0]['msg']}")
    except (KeyError, ValueError, DataStoreError) as exc:
        result = ToolResult(False, error=str(exc.args[0]) if isinstance(exc, KeyError) else str(exc))
    ms = (time.perf_counter() - started) * 1000
    log_event(logger, "tool_call", tool=name, args=arguments, ok=result.ok, error=result.error,
              output=summarize(result.output, 100) if result.ok else None, ms=round(ms, 2))
    if trace is not None:
        trace.add(name, arguments, result, ms)
    return result
