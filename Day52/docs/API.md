# API reference (generated - run `python -m scripts.make_api_docs`)

Protected endpoints need the `X-API-Key` header when `APP_API_KEY` is set. Errors share one JSON shape: `{"error": {...}}`.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/config` | API key | The effective, non-secret configuration of this process (defaults < config.yaml < environment). |
| POST | `/decide` | API key | One entry point for every mode. `?mode=baseline|ai|graph` (default from config; other modes must be enabled in allowed_modes). |
| POST | `/decision` | API key | The LangGraph workflow: tools -> rules -> LLM explanation -> controlled final decision (response includes the node trace). |
| POST | `/decision/ai` | API key | Baseline decision + LLM explanation/second opinion. The LLM can only make the outcome safer (route -> manual_review). |
| POST | `/decision/async` | API key | Same decision as POST /decision, but the LLM calls are awaited (AsyncOpenAI + graph.ainvoke): one worker serves many |
| POST | `/decision/async-naive` | API key | ANTI-PATTERN kept for the benchmark only: `async def` that calls the blocking graph directly. It blocks the event loop, |
| GET | `/decision/audit` | API key | All decision ids recorded for a transaction id. |
| GET | `/decision/audit/{decision_id}` | API key | The full audit record of one decision (404 if unknown) plus a tamper check. |
| POST | `/decision/baseline` | API key | Deterministic decision (no LLM): risk rules -> eligibility -> scoring -> action with reason codes. |
| POST | `/decision/tools` | API key | Rules over audited tool calls (no LLM). Same decision as /decision/baseline, plus the trace of every lookup. |
| POST | `/events/validate` | - | Accept a transaction and echo it back normalised - proves the input contract before any decision logic exists. |
| GET | `/health` | - | Health |
| POST | `/jobs` | API key | Queue a transaction for background decisioning and return immediately (202). The same transaction id is idempotent. |
| GET | `/jobs` | API key | Queue Stats |
| GET | `/status/{job_id}` | API key | Job Status |

## Schemas

### BlockedBy

| Field | Type | Required |
|---|---|---|
| `policy_id` | string/null |  |
| `reason` | string/null |  |

### Decision

| Field | Type | Required |
|---|---|---|
| `transaction_id` | string | yes |
| `action` | ref | yes |
| `selected_provider` | string/null |  |
| `reason_codes` | array | yes |
| `risk_score` | number | yes |
| `expected_cost` | number/null |  |
| `expected_approval_probability` | number/null |  |
| `explanation` | string/null |  |

### DecisionResponse

| Field | Type | Required |
|---|---|---|
| `decision` | ref | yes |
| `baseline_decision` | ref | yes |
| `decision_id` | string/null |  |
| `audit_recorded` | boolean/null |  |
| `blocked_by` | array |  |
| `guard_override` | string/null |  |
| `changed_by_ai` | boolean | yes |
| `llm_status` | string | yes |
| `fast_path` | string/null |  |
| `llm` | ref/null |  |
| `notes` | array |  |
| `usage` | ref |  |
| `latency_ms` | number | yes |
| `tool_trace` | array |  |
| `graph` | ref/null |  |

### ErrorResponse

| Field | Type | Required |
|---|---|---|
| `detail` | string/array | yes |
| `request_id` | string/null |  |

### GraphInfo

| Field | Type | Required |
|---|---|---|
| `route` | string/string | yes |
| `route_reason` | string/null |  |
| `trace` | array | yes |
| `timings_ms` | object |  |

### JobRequest

| Field | Type | Required |
|---|---|---|
| `transaction` | ref | yes |
| `simulate_delay_s` | number |  |

### LLMReviewOut

| Field | Type | Required |
|---|---|---|
| `explanation` | string | yes |
| `agrees_with_baseline` | boolean | yes |
| `concerns` | array |  |
| `escalate_to_review` | boolean | yes |
| `confidence` | number | yes |

### ModeDecisionResponse

| Field | Type | Required |
|---|---|---|
| `mode` | string | yes |
| `config` | object | yes |
| `safety_layers` | array | yes |
| `decision` | ref | yes |
| `llm_status` | string/null |  |
| `decision_id` | string/null |  |

### Transaction

| Field | Type | Required |
|---|---|---|
| `transaction_id` | string | yes |
| `timestamp` | string | yes |
| `amount` | number | yes |
| `currency` | ref | yes |
| `country` | string | yes |
| `merchant_category` | ref | yes |
| `customer_type` | ref | yes |
| `payment_method` | ref | yes |
| `customer_age_days` | integer | yes |
| `prior_chargebacks` | integer |  |

### Usage

| Field | Type | Required |
|---|---|---|
| `llm_calls` | integer |  |
| `embedding_calls` | integer |  |
| `llm_input_tokens` | integer |  |
| `llm_output_tokens` | integer |  |
| `embedding_tokens` | integer |  |
| `estimated_cost_usd` | number |  |

