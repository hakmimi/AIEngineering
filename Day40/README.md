# Day 40 – Audit Trail and Explainability

## Goal

Make every decision reviewable later – by a support agent, an auditor or a regulator – with a **durable, structured, tamper-evident record per decision**, retrievable by id, and clearly separated from the technical runtime logs.

```text
Decision Request → Decision Response (+ decision_id) → Audit Record → GET /decision/audit/{id}
```

## What changed (vs Day 39)

| File | Change |
|---|---|
| `audit.py` (new) | `AuditRecord` (Pydantic), insert-only SQLite `AuditStore` (`save`, `get`, `for_transaction`, `verify`, `count`) with a SHA-256 per row, `build_record`, `record_decision` |
| `decision_graph.py` | `run_decision_graph` creates a `decision_id`, exposes it to logs (context variable), and writes the audit record after the decision is complete |
| `observability.py` | `decision_id` appears on every log line produced while a decision is being made |
| `ai_decision.py` | results carry `decision_id`, `audit_recorded`, `risk_components` |
| `main.py` | `GET /decision/audit/{decision_id}` (record + integrity check, 404 if unknown), `GET /decision/audit?transaction_id=…`; **all decision endpoints now require the API key when `APP_API_KEY` is set, and are rate-limited** |
| `config.py` | `audit_db_path` (`data/audit.db`) |
| `tests/test_audit.py` (new), `tests/conftest.py` | 21 tests; every test gets its own audit store (in-memory by default, real SQLite in `test_audit.py`) |

## What an audit record contains

| Question an auditor asks | Field(s) |
|---|---|
| Which decision / request / code version? | `decision_id`, `request_id`, `agent_version`, `created_at` |
| What came in? | `input_summary` (business fields; no free text exists in this domain) |
| Which path did the agent take? | `route`, `route_reason`, `graph_trace`, `fast_path` |
| Which tools did it consult? | `tools_used`: tool, ok, ms, compact arguments (one entry per call) |
| What did the rules say? | `risk_score`, `risk_components`, `baseline_action`, `baseline_provider` |
| What did the LLM say? | `llm`: status, agrees, escalate, confidence, concerns |
| What was decided and why? | `final_action`, `final_provider`, `reason_codes`, `changed_by_ai` |
| What can I read to a customer? | `business_explanation` |
| What went wrong technically? | `technical_notes` (kept apart from the business text) |
| What did it cost? | `usage`, `latency_ms` |

## How it was implemented (steps 1–10)

1. **Schema** – `AuditRecord`; a record is created for *every* graph decision, on every path (normal, fallback, uncertain, fast path, tool failure).
2. **decision_id** – `dec_` + 16 hex chars; returned in the response, stored in the record and stamped on all runtime log lines of that decision, so logs and audit join on one key.
3–6. **Input summary / route and tools / reason codes / LLM summary** – see the table.
7. **Retrieval endpoint** – by decision id (with an integrity check) and by transaction id (a transaction can be decided more than once).
8. **Tests** – content, every path, immutability, tamper detection, reopen, failure behaviour, auth.
9. **Audit log vs runtime logs**

| | Runtime log (Day 23) | Audit record (Day 40) |
|---|---|---|
| Purpose | operate and debug the service | justify one decision |
| Audience | engineers | support, compliance, regulators |
| Shape | many events per request, free-form fields | one structured record per decision |
| Lifetime | rotated / discarded | retained, insert-only |
| Integrity | none | SHA-256 per record (`integrity_ok`) |
| Lookup | grep by request/decision id | `GET /decision/audit/{id}` |

10. **Design documentation** – below.

## Design decisions and honest limits

- **Immutability:** there is no update or delete API and ids are primary keys (a second write raises). The hash detects an edited row (tested by tampering with SQL) but is *not* protection against someone who can rewrite both record and hash – a hash chain or an external write-once store would be the next step.
- **If the audit write fails** the decision is still returned with `audit_recorded=false` and an ERROR log (availability over completeness). A regulated deployment may prefer to withhold the decision; the switch is one line in `record_decision`.
- **WAL mode + `synchronous=NORMAL`:** readers never block the writer and the record survives an application crash; only a power loss could lose the very last commit.
- **Personal data:** the summary holds business attributes only. If the input ever contained names or card numbers they would have to be excluded or encrypted here.
- **Scope:** only `POST /decision` (the production graph endpoint) is audited; the earlier experiment endpoints (`/decision/baseline|ai|tools`) are not.
- **A test-suite lesson:** the suite suddenly took 82 s instead of 16 s. Cause: one test re-configured logging while pytest was capturing stdout, leaving the app's log handler bound to a stream that was closed after that test – every later log line raised a swallowed "Logging error" (slow). Fix: the test restores the handler to its *original* stream. After the fix: 292 tests in 27 s.

## Run & test

```bash
cd Day40
python -m pytest                                   # 292 offline tests
# POST /decision {...}  ->  {"decision_id": "dec_…", "audit_recorded": true, ...}
# GET  /decision/audit/dec_…   ->  {"record": {...}, "integrity_ok": true}
# GET  /decision/audit?transaction_id=evt-001
```
