"""The agent's own risk estimate: transparent, table-based, reproducible (no ML model, no LLM).

    risk = 0.45*country + 0.35*category + customer adjustment + amount adjustment + chargeback adjustment   (clipped to 0..1)

It is deliberately simpler than the hidden simulation truth (no noise, coarser terms), like a real rules engine that
approximates a messier reality. scripts/compare_baseline.py measures how well the two agree.
"""
import math
from dataclasses import dataclass, field

from data_loader import load_risk_tables
from schemas import CustomerType, ReasonCode, Transaction

W_COUNTRY, W_CATEGORY = 0.45, 0.35
CUSTOMER_ADJUSTMENT = {CustomerType.NEW: 0.12, CustomerType.RETURNING: 0.0, CustomerType.VIP: -0.05}
CHARGEBACK_STEP, CHARGEBACK_CAP = 0.08, 0.30
AMOUNT_STEP, AMOUNT_CAP = 0.05, 0.15          # +0.05 per doubling above the category's typical amount, capped
UNKNOWN_RISK_SCORE = 0.5       # reported when a decision is made without a risk assessment: "medium", and a human decides
UNKNOWN_COUNTRY_RISK = 0.40                   # a country we have no table entry for is treated as risky, not as safe


@dataclass
class RiskAssessment:
    score: float
    components: dict[str, float]
    reason_codes: list[ReasonCode] = field(default_factory=list)


def amount_in_usd(tx: Transaction) -> float:
    return tx.amount / load_risk_tables()["currency_per_usd"][tx.currency.value]


def compute_risk(tx: Transaction) -> RiskAssessment:
    tables = load_risk_tables()
    country = tables["country_risk"].get(tx.country, UNKNOWN_COUNTRY_RISK)
    category = tables["category_risk"][tx.merchant_category.value]
    typical = tables["category_median_usd"][tx.merchant_category.value]
    doublings = max(math.log2(max(amount_in_usd(tx), 1e-6) / typical), 0.0)

    components = {
        "country": round(W_COUNTRY * country, 4),
        "category": round(W_CATEGORY * category, 4),
        "customer": CUSTOMER_ADJUSTMENT[tx.customer_type],
        "amount": round(min(AMOUNT_STEP * doublings, AMOUNT_CAP), 4),
        "chargebacks": round(min(CHARGEBACK_STEP * tx.prior_chargebacks, CHARGEBACK_CAP), 4),
    }
    score = round(min(max(sum(components.values()), 0.0), 1.0), 4)

    reasons = []
    if tx.prior_chargebacks >= 2:
        reasons.append(ReasonCode.PRIOR_CHARGEBACKS)
    return RiskAssessment(score, components, reasons)
