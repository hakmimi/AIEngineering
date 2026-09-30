"""Synthetic world for the decision agent: reference tables (providers, country/category risk) and a seeded
generator of labelled transactions.

Everything is deterministic given a seed. Assumptions are documented in the README so the data can be criticised.
`simulated_risk_score` and the outcome labels are the *hidden truth* of the simulation - the agent never sees them;
they exist to evaluate how well the agent's own (table-based) risk estimate and routing perform.
"""
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from schemas import Currency, CustomerType, PaymentMethod


class Provider(BaseModel):
    provider_id: str
    name: str
    supported_countries: list[str] | None = Field(description="ISO codes; null = worldwide")
    supported_currencies: list[Currency]
    supported_methods: list[PaymentMethod]
    fee_percent: float = Field(ge=0, le=20, description="Percent of the amount")
    fee_fixed: float = Field(ge=0, description="Fixed fee per transaction (transaction currency units)")
    base_approval_rate: float = Field(ge=0, le=1)
    max_amount: float = Field(gt=0)
    uptime: float = Field(ge=0, le=1, description="Share of time the provider is available")
    max_risk: float = Field(ge=0, le=1, description="Highest risk score the provider accepts")
    avg_latency_ms: int = Field(gt=0)


EU = ["DE", "FR", "IT", "ES", "NL"]
PROVIDERS = [
    Provider(provider_id="alpha_pay", name="Alpha Pay", supported_countries=None,
             supported_currencies=[Currency.USD, Currency.EUR, Currency.GBP, Currency.ILS],
             supported_methods=[PaymentMethod.CARD, PaymentMethod.WALLET], fee_percent=2.9, fee_fixed=0.30,
             base_approval_rate=0.93, max_amount=20000, uptime=0.999, max_risk=0.55, avg_latency_ms=320),
    Provider(provider_id="beta_bank", name="Beta Bank Transfers", supported_countries=[*EU, "GB", "IL"],
             supported_currencies=[Currency.EUR, Currency.GBP, Currency.ILS, Currency.USD],
             supported_methods=[PaymentMethod.BANK_TRANSFER], fee_percent=0.8, fee_fixed=0.20,
             base_approval_rate=0.97, max_amount=100000, uptime=0.995, max_risk=0.45, avg_latency_ms=900),
    Provider(provider_id="gamma_wallet", name="Gamma Wallet", supported_countries=["US", "CA", "GB", "DE", "FR", "IL", "AE", "IN"],
             supported_currencies=[Currency.USD, Currency.EUR, Currency.GBP, Currency.ILS],
             supported_methods=[PaymentMethod.WALLET, PaymentMethod.CARD], fee_percent=2.4, fee_fixed=0.20,
             base_approval_rate=0.90, max_amount=5000, uptime=0.998, max_risk=0.50, avg_latency_ms=400),
    Provider(provider_id="delta_global", name="Delta Global (high-risk tolerant)", supported_countries=None,
             supported_currencies=[Currency.USD, Currency.EUR, Currency.GBP, Currency.ILS],
             supported_methods=[PaymentMethod.CARD, PaymentMethod.WALLET, PaymentMethod.BANK_TRANSFER], fee_percent=4.2,
             fee_fixed=0.50, base_approval_rate=0.84, max_amount=50000, uptime=0.990, max_risk=0.80, avg_latency_ms=550),
    Provider(provider_id="epsilon_local_il", name="Epsilon Local (Israel)", supported_countries=["IL"],
             supported_currencies=[Currency.ILS, Currency.USD],
             supported_methods=[PaymentMethod.CARD, PaymentMethod.WALLET, PaymentMethod.BANK_TRANSFER], fee_percent=1.9,
             fee_fixed=0.10, base_approval_rate=0.95, max_amount=15000, uptime=0.997, max_risk=0.50, avg_latency_ms=200),
    Provider(provider_id="zeta_budget", name="Zeta Budget", supported_countries=["US", "GB", *EU, "CA"],
             supported_currencies=[Currency.USD, Currency.EUR, Currency.GBP], supported_methods=[PaymentMethod.CARD],
             fee_percent=1.6, fee_fixed=0.15, base_approval_rate=0.86, max_amount=3000, uptime=0.960, max_risk=0.40,
             avg_latency_ms=700),
]

# Country weights (share of traffic) and risk (0-1). Assumption: fraud pressure is higher in emerging card-not-present markets.
COUNTRIES = {  # code: (traffic weight, country risk)
    "IL": (0.18, 0.10), "US": (0.20, 0.08), "GB": (0.10, 0.08), "DE": (0.08, 0.07), "FR": (0.06, 0.08),
    "IT": (0.04, 0.10), "ES": (0.04, 0.10), "NL": (0.04, 0.07), "CA": (0.05, 0.08), "BR": (0.05, 0.30),
    "IN": (0.05, 0.28), "NG": (0.03, 0.55), "TR": (0.04, 0.35), "MX": (0.02, 0.30), "AE": (0.02, 0.18),
}
CATEGORY_RISK = {"groceries": 0.05, "utilities": 0.05, "travel": 0.25, "electronics": 0.30, "digital_goods": 0.35,
                 "gaming": 0.35, "luxury": 0.30}
CATEGORY_MEDIAN_USD = {"groceries": 60, "utilities": 120, "travel": 700, "electronics": 500, "digital_goods": 25,
                       "gaming": 40, "luxury": 1500}
CURRENCY_SCALE = {"USD": 1.0, "EUR": 0.92, "GBP": 0.80, "ILS": 3.6}
HOME_CURRENCY = {"IL": "ILS", "US": "USD", "GB": "GBP", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "NL": "EUR",
                 "CA": "USD", "AE": "USD", "IN": "USD", "BR": "USD", "NG": "USD", "TR": "USD", "MX": "USD"}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def generate_transactions(n: int = 1000, seed: int = 42, end: datetime | None = None) -> pd.DataFrame:
    """n synthetic transactions over the 30 days before `end`, with hidden truth columns (see module docstring)."""
    rng = np.random.default_rng(seed)
    end = end or datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc)
    codes = list(COUNTRIES)
    weights = np.array([COUNTRIES[c][0] for c in codes])
    country = rng.choice(codes, size=n, p=weights / weights.sum())
    category = rng.choice(list(CATEGORY_RISK), size=n, p=[0.28, 0.12, 0.10, 0.14, 0.14, 0.12, 0.10])
    customer = rng.choice([c.value for c in CustomerType], size=n, p=[0.25, 0.65, 0.10])
    method = rng.choice([m.value for m in PaymentMethod], size=n, p=[0.70, 0.20, 0.10])

    age = np.where(customer == "new", rng.integers(0, 61, n),
                   np.where(customer == "returning", rng.integers(60, 1500, n), rng.integers(365, 3000, n)))
    country_risk = np.array([COUNTRIES[c][1] for c in country])
    cat_risk = np.array([CATEGORY_RISK[c] for c in category])
    chargeback_rate = np.where(customer == "new", 0.05, np.where(customer == "returning", 0.10, 0.02)) * (1 + 3 * country_risk)
    chargebacks = np.minimum(rng.poisson(chargeback_rate), 5)

    # Home currency most of the time, otherwise a random one (cross-currency payments happen).
    home = np.array([HOME_CURRENCY[c] for c in country])
    currency = np.where(rng.random(n) < 0.8, home, rng.choice(list(CURRENCY_SCALE), size=n))
    median = np.array([CATEGORY_MEDIAN_USD[c] for c in category]) * np.array([CURRENCY_SCALE[c] for c in currency])
    amount = np.round(np.clip(median * rng.lognormal(0.0, 0.9, n), 1.0, 60000.0), 2)

    ts = [end - timedelta(seconds=int(s)) for s in rng.integers(0, 30 * 24 * 3600, n)]

    # Hidden truth: latent risk grows with country/category risk, new customers, unusually large amounts, chargebacks.
    amount_ratio = np.log(np.maximum(amount / median, 1e-3))
    logit = (-3.0 + 3.2 * country_risk + 2.4 * cat_risk + 0.9 * (customer == "new") - 0.6 * (customer == "vip")
             + 0.35 * np.maximum(amount_ratio, 0) + 0.7 * chargebacks + rng.normal(0, 0.35, n))
    true_risk = np.round(_sigmoid(logit), 4)
    fraud = rng.random(n) < 0.35 * true_risk**2                                      # riskier => far more actual fraud (~1-3% overall)

    df = pd.DataFrame({
        "transaction_id": [f"txn-{seed}-{i:05d}" for i in range(n)],
        "timestamp": [t.isoformat().replace("+00:00", "Z") for t in ts],
        "amount": amount, "currency": currency, "country": country, "merchant_category": category,
        "customer_type": customer, "payment_method": method, "customer_age_days": age.astype(int),
        "prior_chargebacks": chargebacks.astype(int),
        "simulated_risk_score": true_risk, "is_fraud": fraud,
    })
    # Outcome at a historical provider chosen at random among those that could carry the payment.
    historical, approved = [], []
    for row, r in zip(df.itertuples(index=False), true_risk, strict=True):
        candidates = [p for p in PROVIDERS if can_carry(p, row.country, row.currency, row.payment_method, row.amount)] or [PROVIDERS[3]]
        provider = candidates[int(rng.integers(0, len(candidates)))]
        p_ok = provider.base_approval_rate * (1 - 0.40 * r)
        historical.append(provider.provider_id)
        approved.append(bool(rng.random() < p_ok and not row.is_fraud))
    df["historical_provider"], df["approved_outcome"] = historical, approved
    return df.sort_values("timestamp").reset_index(drop=True)


def can_carry(provider: Provider, country: str, currency: str, method: str, amount: float) -> bool:
    """Hard capability constraints (no risk here): country, currency, method, amount limit."""
    return ((provider.supported_countries is None or country in provider.supported_countries)
            and currency in [c.value for c in provider.supported_currencies]
            and method in [m.value for m in provider.supported_methods]
            and amount <= provider.max_amount)


def risk_tables() -> dict:
    return {"country_risk": {c: v[1] for c, v in COUNTRIES.items()}, "category_risk": CATEGORY_RISK}


def summary_stats(df: pd.DataFrame) -> dict:
    return {
        "rows": len(df),
        "amount_median": float(df["amount"].median()), "amount_p99": float(df["amount"].quantile(0.99)),
        "share_new": float((df["customer_type"] == "new").mean()),
        "fraud_rate": float(df["is_fraud"].mean()), "approval_rate": float(df["approved_outcome"].mean()),
        "mean_simulated_risk": float(df["simulated_risk_score"].mean()),
        "risk_by_country": {k: round(v, 3) for k, v in df.groupby("country")["simulated_risk_score"].mean().sort_values().items()},
        "math_check": math.isfinite(float(df["amount"].sum())),
    }
