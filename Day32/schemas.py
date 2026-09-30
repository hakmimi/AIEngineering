"""Domain model for the payment-routing decision agent.

A *transaction* arrives, the agent picks an action (route to a provider / send to manual review / decline) and
explains why with machine-readable reason codes. These Pydantic models are the contract for the whole project:
the API, the data generator, the tools, the graph state and the audit log all use them.
"""
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config import settings


class Currency(StrEnum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    ILS = "ILS"


class PaymentMethod(StrEnum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    WALLET = "wallet"


class MerchantCategory(StrEnum):
    GROCERIES = "groceries"
    ELECTRONICS = "electronics"
    TRAVEL = "travel"
    DIGITAL_GOODS = "digital_goods"
    GAMING = "gaming"
    LUXURY = "luxury"
    UTILITIES = "utilities"


class CustomerType(StrEnum):
    NEW = "new"
    RETURNING = "returning"
    VIP = "vip"


class Action(StrEnum):
    """What the agent may do. Anything else is a bug, so this is a closed set."""
    ROUTE = "route"                    # approve and send to the selected provider
    MANUAL_REVIEW = "manual_review"    # a human decides
    DECLINE = "decline"


class ReasonCode(StrEnum):
    """Stable, machine-readable explanations (the LLM writes prose *around* these, never instead of them)."""
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"
    NEW_CUSTOMER_HIGH_AMOUNT = "NEW_CUSTOMER_HIGH_AMOUNT"
    PRIOR_CHARGEBACKS = "PRIOR_CHARGEBACKS"
    NO_ELIGIBLE_PROVIDER = "NO_ELIGIBLE_PROVIDER"
    CHEAPEST_ELIGIBLE = "CHEAPEST_ELIGIBLE"
    HIGHEST_APPROVAL_RATE = "HIGHEST_APPROVAL_RATE"
    BEST_OVERALL_SCORE = "BEST_OVERALL_SCORE"
    ONLY_ELIGIBLE_PROVIDER = "ONLY_ELIGIBLE_PROVIDER"
    POLICY_BLOCK = "POLICY_BLOCK"
    AI_ESCALATION = "AI_ESCALATION"
    INVALID_INPUT = "INVALID_INPUT"


class Transaction(BaseModel):
    """A business event the agent must decide on."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transaction_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    timestamp: datetime
    amount: float = Field(..., gt=0, description="In `currency`, major units")
    currency: Currency
    country: str = Field(..., min_length=2, max_length=2, description="ISO 3166-1 alpha-2 of the customer, upper case")
    merchant_category: MerchantCategory
    customer_type: CustomerType
    payment_method: PaymentMethod
    customer_age_days: int = Field(..., ge=0, le=36500, description="Days since the customer account was created")
    prior_chargebacks: int = Field(default=0, ge=0, le=100)

    @field_validator("country")
    @classmethod
    def country_is_upper_alpha(cls, value: str) -> str:
        if not (value.isalpha() and value.isupper()):
            raise ValueError("country must be two upper-case letters, e.g. 'IL'")
        return value

    @field_validator("amount")
    @classmethod
    def amount_within_limit(cls, value: float) -> float:
        if value > settings.max_amount:
            raise ValueError(f"amount exceeds the maximum of {settings.max_amount:,.0f}")
        return round(value, 2)

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_aware_and_not_future(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone (e.g. 2026-01-05T10:30:00Z)")
        if value > datetime.now(timezone.utc) + timedelta(minutes=5):      # 5 min of clock skew is tolerated
            raise ValueError("timestamp is in the future")
        return value

    @model_validator(mode="after")
    def new_customers_cannot_be_old(self) -> "Transaction":
        if self.customer_type is CustomerType.NEW and self.customer_age_days > 90:
            raise ValueError("a 'new' customer cannot have an account older than 90 days")
        return self


class Decision(BaseModel):
    """The agent's answer. `reason_codes` are the audit-grade explanation; `explanation` is optional prose."""
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    action: Action
    selected_provider: str | None = None
    reason_codes: list[ReasonCode] = Field(min_length=1)
    risk_score: float = Field(ge=0, le=1)
    expected_cost: float | None = Field(default=None, ge=0, description="Fee in the transaction currency")
    expected_approval_probability: float | None = Field(default=None, ge=0, le=1)
    explanation: str | None = None

    @model_validator(mode="after")
    def provider_matches_action(self) -> "Decision":
        if self.action is Action.ROUTE and not self.selected_provider:
            raise ValueError("action 'route' requires selected_provider")
        if self.action is not Action.ROUTE and self.selected_provider:
            raise ValueError("only action 'route' may carry a selected_provider")
        return self
