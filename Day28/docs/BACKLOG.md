# Month 2 improvement backlog (from what Month 1 could not show)

## Turn the RAG lessons into a decision agent (plan: Days 29-56)

1. **New domain, same discipline** - payment/transaction decisioning: deterministic baseline first, LLM only to explain or challenge, controlled final decision, audit trail. Reuse: config/env pattern, request-id logging, guardrail-with-false-positive testing, retry/fallback graph, evaluation runner with versioned results.
2. **Evaluation first** - build the eval set *before* the agent so improvements are measured (Month 1 built it after and saturated at 100 %).

## Known gaps to close

| Gap (evidence) | Next step |
|---|---|
| Eval set is small/easy; 100 % cannot rank systems (prompt v1 = v2) | 100+ cases incl. adversarial, held-out split, different judge model, human spot checks |
| Guardrails miss paraphrase / obfuscation / Hebrew (4 of 27 attack cases) | learned classifier or LLM guard behind the rules; keep false-positive test set |
| Docker + CI validated only by simulation | build and run the image; push and watch the first green run |
| Memory, rate limits, SQLite are single-node | Redis/Postgres, shared rate limiter |
| Latency floor = two network calls (~1.3 s p50) | cache query embeddings, stream responses, async endpoints |
| Retrieval is lexical-boost + dense only | hybrid BM25 + dense, reranker, evaluation on paraphrase-heavy queries |
| Prices are estimates | pull prices from config/service, add budget alerts |
| No metrics endpoint / dashboards | Prometheus-style metrics from the existing structured events |
