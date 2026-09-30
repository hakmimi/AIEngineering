# Day 41 – Policy Guardrails for Decision Safety

## Goal

Add **non-negotiable business constraints** that the agent can never violate – regardless of what the rules or the LLM think – with a safe, explained blocked-decision format, logging, and regression tests. Principle: policies can only make an outcome *stricter*.

```text
Transaction → Policy Gate ─ violation → Blocked Decision (decline / manual review) ─┐
                         └ ok → route → tools → rules → LLM review → Finalize → Constraint Guard → Decision → Audit
```

## What changed (vs Day 40)

| File | Change |
|---|---|
| `data/policies.json` (new) | the **constraint table**: 4 policies as data, not code |
| `policy.py` (new) | validated `Policy` model (4 kinds), `load_policies`, `check_policies(tx)` → `Violation`s, `strictest()`, `policy_summary()` for the LLM prompt |
| `decision_graph.py` | new nodes `policy_gate` (right after `input`, before any tool/LLM work), `policy_block` (blocked-decision format) and `constraint_guard` (independent re-check after `finalize`); response carries `blocked_by` and `guard_override` |
| `prompts.py` | the review prompt lists the policies in force and forbids suggestions that conflict with them or claims that a policy was waived |
| `ai_decision.py` | an explanation already written by the graph (the blocking policy) is no longer overwritten by the template |
| `version.py` | `AGENT_VERSION = "v3"` |
| `data/eval/decision_cases.json` | +6 **policy** cases (45 total), including two *guards* that must not be over-blocked |
| `tests/test_policy.py` (new), other tests updated for the new nodes | 39 new tests → 331 in total |

## The constraint table

| Id | Rule | Action |
|---|---|---|
| `P1_SANCTIONED_COUNTRY` | customer country in KP, IR, SY, CU | **decline** |
| `P2_AMOUNT_LIMIT_BY_CUSTOMER` | single payment above new 5,000 / returning 25,000 / vip 75,000 USD | manual review |
| `P3_WALLET_LIMIT` | wallet payment above 3,000 USD | manual review |
| `P4_NO_GAMING_BY_BANK_TRANSFER` | payment method `bank_transfer` with merchant category `gaming` | **decline** |

A policy is validated when loaded: unique id, allowed kind, required parameters, positive limits, and it may only require `manual_review` or `decline` – a policy that *permits* something is rejected.

## How it was implemented (steps 1–10)

1. **Hard constraints** – sanctions, per-customer and per-method limits, a forbidden combination (chosen as typical of payment-compliance rules).
2. **Constraint table/config** – `data/policies.json`, so compliance can change limits without touching code.
3. **Validation function** – `check_policies(tx)`; amounts compared in USD (a 100,000 ILS payment is ≈ 27.8k USD and violates the returning-customer limit).
4. **Guardrail node in the graph** – *two* places, on purpose: `policy_gate` first (a violation needs no tools or LLM and ends the run with a safe explained decision) and `constraint_guard` last (an independent second check of invariants that must hold on every output: no policy violation, and a routed provider must really be eligible).
5. **Blocked-decision format** – a normal HTTP 200 business decision: `action` decline/manual_review, `reason_codes: ["POLICY_BLOCK"]`, `explanation` naming the policy, `blocked_by: [{policy_id, action, message}]`, `llm_status: "skipped"`. Blocking is a decision, not an error.
6. **Prompt respects constraints** – policies are listed in the LLM prompt; the LLM still cannot make anything less strict (Day 32 control rules).
7. **Logging** – `guardrail_decision stage=policy_gate policy_ids=[…] action=…`; a guard correction logs `guardrail_override` at **ERROR** (it means an upstream bug); the audit record notes `policy block: …`.
8. **Blocked cases tested** and 9. **normal cases regression-tested** – see below. 10. **Documented** – this file.

Two design details worth noting:
- **Policy beats fallback.** Country `KP` is not in the risk tables, so the Day 35 fallback would have sent it to manual review. The gate runs first, so it is *declined* – which is what a sanction requires.
- **No duplicate rules.** The VIP limit is 75,000 (not 50,000) so it does not shadow the agent's own `EXTREME_AMOUNT` competence limit (50,000 → human): between 50k and 75k a VIP still takes the fallback route, above 75k the policy applies.

## Results

| Check | Result |
|---|---|
| Policy cases in the evaluation (4 blocked + 2 must-not-block) | AI agent **6/6**; rules-only baseline 2/6 (it *routes* sanctioned and forbidden payments – 4 more unsafe errors) |
| Whole 45-case set | AI **100 %**, 0 unsafe errors; baseline 75.6 % with 10 unsafe errors |
| Regression on the 39 earlier cases | AI 100 % → 100 %, no case regressed |
| Guard proven to work | tests inject an upstream bug (gate misses a sanctioned payment; a routed provider that cannot carry the amount) and assert the guard corrects it, clears the provider and logs at ERROR |
| Property | for every policy, the final action is at least as strict as the policy requires (tested for each kind and boundary: exactly at a limit passes, one cent over blocks) |

## Caveats

The policy table is illustrative (real sanctions lists change and are maintained by compliance); amounts use the fixed currency table; policies only look at the transaction (no velocity or cumulative-limit rules yet).

## Run & test

```bash
cd Day41
python -m pytest                                # 331 offline tests (~23 s)
python -m scripts.eval_full v4                  # live: both agents, 45 cases
python -m scripts.eval_compare v2 v3
# POST /decision with country "KP" -> decline, POLICY_BLOCK, blocked_by [...]
```
