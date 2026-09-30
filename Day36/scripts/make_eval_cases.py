"""Writes data/eval/decision_cases.json from the definitions below.

The expected outcomes come from BUSINESS reasoning ("a new customer paying 2,400 USD for electronics belongs with a human"),
written down *before* looking at what the agent does - otherwise the evaluation would just mirror the agent's own bugs.
Where several answers are commercially acceptable the case lists them (acceptable_actions / acceptable_providers).
"""
import json

from config import settings

BASE = {"timestamp": "2026-01-05T09:12:00Z", "prior_chargebacks": 0}
CASES = []


def case(cid, category, why, tx, actions, providers=None, route="normal", reasons=None, ):
    CASES.append({"id": cid, "category": category, "description": why,
                  "transaction": {**BASE, "transaction_id": cid, **tx},
                  "expected": {"acceptable_actions": actions, "acceptable_providers": providers, "route": route,
                               "must_include_reason_codes": reasons or []}})


T = lambda **kw: kw  # noqa: E731  (readability only)

# --- routine payments that must be processed -----------------------------------------------------------------------------------------
case("n01_il_grocery_card", "normal", "Local grocery card payment in Israel - the local provider is cheapest and most reliable",
     T(amount=216, currency="ILS", country="IL", merchant_category="groceries", customer_type="returning", payment_method="card", customer_age_days=400),
     ["route"], ["epsilon_local_il"])
case("n02_us_grocery_card", "normal", "Small US card payment by a known customer",
     T(amount=100, currency="USD", country="US", merchant_category="groceries", customer_type="returning", payment_method="card", customer_age_days=300),
     ["route"], ["alpha_pay", "gamma_wallet"])
case("n03_de_bank_transfer", "normal", "Utility bill by bank transfer in Germany - the bank-transfer specialist is the natural choice",
     T(amount=2000, currency="EUR", country="DE", merchant_category="utilities", customer_type="returning", payment_method="bank_transfer", customer_age_days=700),
     ["route"], ["beta_bank"])
case("n04_vip_travel_eur", "normal", "Large travel booking by a long-standing VIP - process, do not block a good customer",
     T(amount=5200, currency="EUR", country="DE", merchant_category="travel", customer_type="vip", payment_method="card", customer_age_days=900),
     ["route"], ["alpha_pay"])
case("n05_wallet_digital", "normal", "Small wallet purchase of digital goods by a returning customer",
     T(amount=30, currency="USD", country="US", merchant_category="digital_goods", customer_type="returning", payment_method="wallet", customer_age_days=250),
     ["route"], ["alpha_pay", "gamma_wallet"])
case("n06_il_bank_transfer", "normal", "Israeli bank transfer - either the bank-transfer specialist or the local provider is fine",
     T(amount=3000, currency="ILS", country="IL", merchant_category="utilities", customer_type="returning", payment_method="bank_transfer", customer_age_days=500),
     ["route"], ["beta_bank", "epsilon_local_il"])
case("n07_gb_electronics", "normal", "UK electronics purchase by a returning customer - moderate amount, low risk",
     T(amount=450, currency="GBP", country="GB", merchant_category="electronics", customer_type="returning", payment_method="card", customer_age_days=380),
     ["route"], ["alpha_pay", "gamma_wallet", "zeta_budget"])
case("n08_vip_luxury", "normal", "Big luxury purchase by a VIP with a long history - should still be processed",
     T(amount=8000, currency="USD", country="US", merchant_category="luxury", customer_type="vip", payment_method="card", customer_age_days=1200),
     ["route"], ["alpha_pay", "delta_global"])
case("n09_in_electronics", "normal", "Returning customer in a medium-risk country buying electronics - risk is manageable, process it",
     T(amount=300, currency="USD", country="IN", merchant_category="electronics", customer_type="returning", payment_method="card", customer_age_days=420),
     ["route"], ["alpha_pay", "gamma_wallet"])
case("n10_chargebacks_but_ok", "normal", "Returning customer with two old chargebacks on a tiny grocery order - process but keep the history visible",
     T(amount=200, currency="USD", country="US", merchant_category="groceries", customer_type="returning", payment_method="card", customer_age_days=600, prior_chargebacks=2),
     ["route"], None, reasons=["PRIOR_CHARGEBACKS"])
case("n11_only_option_bank_br", "normal", "Bank transfer from Brazil in GBP - only the expensive global provider can carry it; acceptable, not a reason to refuse",
     T(amount=640, currency="GBP", country="BR", merchant_category="luxury", customer_type="returning", payment_method="bank_transfer", customer_age_days=120),
     ["route"], ["delta_global"])

# --- risky payments that need a human or must be declined ---------------------------------------------------------------------------------
case("r01_new_big_electronics", "risky", "Brand-new customer, 2,400 USD of electronics - classic fraud pattern, needs a human",
     T(amount=2400, currency="USD", country="US", merchant_category="electronics", customer_type="new", payment_method="card", customer_age_days=3),
     ["manual_review"], reasons=["NEW_CUSTOMER_HIGH_AMOUNT"])
case("r02_new_big_travel", "risky", "New customer, 1,500 USD travel booking - large first purchase",
     T(amount=1500, currency="USD", country="GB", merchant_category="travel", customer_type="new", payment_method="card", customer_age_days=10),
     ["manual_review"], reasons=["NEW_CUSTOMER_HIGH_AMOUNT"])
case("r03_ng_electronics_new_cb", "risky", "New customer in a high-risk country with a chargeback, buying electronics",
     T(amount=700, currency="USD", country="NG", merchant_category="electronics", customer_type="new", payment_method="card", customer_age_days=5, prior_chargebacks=1),
     ["manual_review", "decline"])
case("r04_ng_digital_two_chargebacks", "risky", "Day-old account, two chargebacks, high-risk country, digital goods via wallet - decline",
     T(amount=1800, currency="USD", country="NG", merchant_category="digital_goods", customer_type="new", payment_method="wallet", customer_age_days=1, prior_chargebacks=2),
     ["decline"], reasons=["HIGH_RISK"])
case("r05_ng_gaming_three_chargebacks", "risky", "Three chargebacks on a two-day-old gaming account in a high-risk country - decline",
     T(amount=500, currency="USD", country="NG", merchant_category="gaming", customer_type="new", payment_method="card", customer_age_days=2, prior_chargebacks=3),
     ["decline"])
case("r06_tr_luxury_new_big", "risky", "New customer in a medium/high-risk country buying 4,000 USD of luxury goods - never auto-approve",
     T(amount=4000, currency="USD", country="TR", merchant_category="luxury", customer_type="new", payment_method="card", customer_age_days=4, prior_chargebacks=2),
     ["manual_review", "decline"])

# --- edge cases: the agent must not decide alone -------------------------------------------------------------------------------------------------
case("e01_unknown_country", "edge", "Country the risk tables do not cover - risk cannot be assessed",
     T(amount=100, currency="USD", country="ZZ", merchant_category="groceries", customer_type="returning", payment_method="card", customer_age_days=300),
     ["manual_review"], route="fallback", reasons=["UNKNOWN_COUNTRY"])
case("e02_extreme_amount", "edge", "75,000 USD - above any automatic limit, even for a VIP",
     T(amount=75000, currency="USD", country="US", merchant_category="electronics", customer_type="vip", payment_method="card", customer_age_days=800),
     ["manual_review"], route="fallback", reasons=["EXTREME_AMOUNT"])
case("e03_vip_with_new_account", "edge", "A 'vip' whose account is 20 days old - the profile data is inconsistent",
     T(amount=900, currency="EUR", country="DE", merchant_category="travel", customer_type="vip", payment_method="card", customer_age_days=20),
     ["manual_review"], route="fallback", reasons=["INCONSISTENT_PROFILE"])
case("e04_returning_two_day_account", "edge", "A 'returning' customer whose account is two days old - inconsistent",
     T(amount=50, currency="USD", country="US", merchant_category="groceries", customer_type="returning", payment_method="card", customer_age_days=2),
     ["manual_review"], route="fallback", reasons=["INCONSISTENT_PROFILE"])

# --- uncertain: a routed decision that deserves a second look ----------------------------------------------------------------------------------------
case("u01_borderline_new_br_gaming", "uncertain", "New customer, Brazil, gaming, risk just under the review line - safer with a human",
     T(amount=100, currency="USD", country="BR", merchant_category="gaming", customer_type="new", payment_method="card", customer_age_days=10),
     ["manual_review"], route="uncertain", reasons=["LOW_CONFIDENCE"])
case("u02_borderline_new_in_digital", "uncertain", "New customer, India, digital goods, risk just under the review line",
     T(amount=60, currency="USD", country="IN", merchant_category="digital_goods", customer_type="new", payment_method="card", customer_age_days=15),
     ["manual_review"], route="uncertain", reasons=["LOW_CONFIDENCE"])


def main() -> None:
    out = settings.data_dir / "eval" / "decision_cases.json"
    out.write_text(json.dumps(CASES, indent=1), encoding="utf8")
    print(f"wrote {len(CASES)} cases to {out}")
    by = {}
    for c in CASES:
        by[c["category"]] = by.get(c["category"], 0) + 1
    print(by)


if __name__ == "__main__":
    main()
