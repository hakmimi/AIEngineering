"""Synthetic traffic for the simulator: a labelled mix of realistic and adversarial events.

    build_events(n, seed) -> [{"scenario": "...", "event": {...Transaction fields...}}, ...]

The `scenario` label stays on the client side and is never sent to the API; it lets the analysis check, per scenario, whether the
agent behaved as it should (e.g. every injected sanctions case must be declined).
"""
import random
from datetime import datetime, timedelta, timezone

from simulation import generate_transactions

# share of the traffic per scenario (routine traffic dominates, like in production)
DEFAULT_MIX = {"routine": 0.84, "card_testing": 0.04, "anomalous_amount": 0.03, "policy_violation": 0.05, "edge_case": 0.04}
HIDDEN = ["simulated_risk_score", "is_fraud", "historical_provider", "approved_outcome"]


def _base(i: int, rng: random.Random, when: datetime) -> dict:
    return {"transaction_id": f"sim-{i:04d}", "timestamp": when.isoformat().replace("+00:00", "Z"), "amount": 100.0, "currency": "USD",
            "country": "US", "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card",
            "customer_age_days": rng.randint(200, 1200), "prior_chargebacks": 0}


def _special(scenario: str, i: int, rng: random.Random, when: datetime) -> dict:
    e = _base(i, rng, when)
    if scenario == "card_testing":
        e.update(amount=round(rng.uniform(0.5, 5), 2), merchant_category=rng.choice(["digital_goods", "gaming"]), customer_type="new",
                 customer_age_days=rng.randint(0, 3))
    elif scenario == "anomalous_amount":
        e.update(amount=round(rng.uniform(4000, 9000), 2), merchant_category="groceries")             # 65-150x a grocery basket
    elif scenario == "policy_violation":
        kind = rng.choice(["sanctioned", "wallet_limit", "gaming_bank"])
        if kind == "sanctioned":
            e.update(country=rng.choice(["KP", "IR", "SY", "CU"]))
        elif kind == "wallet_limit":
            e.update(payment_method="wallet", amount=round(rng.uniform(3200, 4500), 2), merchant_category="electronics")
        else:
            e.update(payment_method="bank_transfer", merchant_category="gaming", country="DE", currency="EUR", amount=round(rng.uniform(40, 300), 2))
    elif scenario == "edge_case":
        kind = rng.choice(["unknown_country", "vip_new_account", "returning_new_account"])
        if kind == "unknown_country":
            e.update(country=rng.choice(["ZZ", "XX", "QQ"]))
        elif kind == "vip_new_account":
            e.update(customer_type="vip", customer_age_days=rng.randint(5, 100))
        else:
            e.update(customer_type="returning", customer_age_days=rng.randint(0, 5))
    return e


def build_events(n: int = 100, seed: int = 7, mix: dict[str, float] | None = None) -> list[dict]:
    if n < 1:
        raise ValueError("n must be at least 1")
    mix = mix or DEFAULT_MIX
    rng = random.Random(seed)
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    routine = generate_transactions(n, seed=seed, end=now).drop(columns=HIDDEN).to_dict(orient="records")
    scenarios = rng.choices(list(mix), weights=list(mix.values()), k=n)
    events = []
    for i, scenario in enumerate(scenarios):
        if scenario == "routine":
            event = {**routine[i], "transaction_id": f"sim-{i:04d}"}
        else:
            event = _special(scenario, i, rng, now - timedelta(minutes=i))
        events.append({"scenario": scenario, "event": event})
    return events
