"""Business policy constraints - non-negotiable rules kept in a table (data/policies.json), not scattered through code.

A policy is NOT a risk opinion: it is something the business/regulator has said must always hold (no payments from sanctioned
countries, per-customer and per-method limits, forbidden combinations). They are enforced twice:
  1. policy_gate     - right after input, before any tool or LLM work: a violation ends the run with a safe, explained decision;
  2. constraint_guard - after the final decision: an independent re-check of the invariants that must hold on EVERY output
                        (defence in depth: it should never fire; if it does, something upstream is wrong and it is logged loudly).
Policies can only make an outcome stricter (manual_review or decline), never more permissive.
"""
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from config import settings
from errors import DataStoreError
from risk import amount_in_usd
from schemas import Action, Transaction

POLICIES_PATH = settings.data_dir / "policies.json"
STRICTNESS = {Action.MANUAL_REVIEW: 1, Action.DECLINE: 2}


class Policy(BaseModel):
    id: str = Field(pattern=r"^P\d+_[A-Z_]+$")
    kind: Literal["blocked_country", "max_amount_by_customer", "max_amount_by_method", "forbidden_combination"]
    action: Action
    description: str = Field(min_length=10)
    params: dict

    @model_validator(mode="after")
    def check(self) -> "Policy":
        if self.action is Action.ROUTE:
            raise ValueError("a policy can only require manual_review or decline")
        required = {"blocked_country": {"countries"}, "max_amount_by_customer": {"new", "returning", "vip"},
                    "max_amount_by_method": set(), "forbidden_combination": set()}[self.kind]
        if not required <= set(self.params):
            raise ValueError(f"{self.kind} needs params {sorted(required)}")
        if self.kind in ("max_amount_by_customer", "max_amount_by_method") and any(v <= 0 for v in self.params.values()):
            raise ValueError("limits must be positive")
        if self.kind == "forbidden_combination" and len(self.params) < 2:
            raise ValueError("a forbidden combination needs at least two fields")
        return self


@dataclass(frozen=True)
class Violation:
    policy_id: str
    action: Action
    message: str


@lru_cache(maxsize=1)
def load_policies() -> tuple[Policy, ...]:
    try:
        raw = json.loads(POLICIES_PATH.read_text(encoding="utf8"))
    except FileNotFoundError as exc:
        raise DataStoreError("policies.json not found") from exc
    except json.JSONDecodeError as exc:
        raise DataStoreError("policies.json is not valid JSON") from exc
    policies = tuple(Policy(**p) for p in raw)
    if len({p.id for p in policies}) != len(policies):
        raise DataStoreError("duplicate policy ids")
    return policies


def _violates(policy: Policy, tx: Transaction) -> bool:
    p = policy.params
    if policy.kind == "blocked_country":
        return tx.country in p["countries"]
    if policy.kind == "max_amount_by_customer":
        return amount_in_usd(tx) > p[tx.customer_type.value]
    if policy.kind == "max_amount_by_method":
        limit = p.get(tx.payment_method.value)
        return limit is not None and amount_in_usd(tx) > limit
    return all(getattr(tx, field).value == value for field, value in p.items())          # forbidden_combination


def check_policies(tx: Transaction, policies: tuple[Policy, ...] | None = None) -> list[Violation]:
    return [Violation(p.id, p.action, p.description) for p in (policies or load_policies()) if _violates(p, tx)]


def strictest(violations: list[Violation]) -> Action | None:
    return max((v.action for v in violations), key=lambda a: STRICTNESS[a], default=None)


def policy_summary() -> list[str]:
    """One line per policy - shown to the LLM so its explanation never contradicts a policy."""
    return [f"{p.id}: {p.description} ({p.action.value})" for p in load_policies()]
