"""Version tag of the decision logic. Bump it whenever rules, thresholds, policies or prompts change, so every stored
evaluation result and every logged decision says WHICH version produced it (needed to answer "did the fix help?")."""
AGENT_VERSION = "v3"

CHANGELOG = {
    "v1": "Day 31-35: risk rules, eligibility, scoring, LLM review, fallback + uncertainty routes",
    "v2": "Day 38: card-testing rule, amount-anomaly rule, chargeback-history rule (fixes found by the Day 37 evaluation)",
    "v3": "Day 41: policy constraints (sanctions, limits, forbidden combinations) enforced before and after the decision",
}
