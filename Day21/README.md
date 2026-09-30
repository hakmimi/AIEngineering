# Day 21 – Week 3 Packaging

## Goal

Turn Week 3 (Days 15–20: LangGraph, routing, tools, failure handling, memory, evaluation) into **one clear, explainable milestone**: clean code, a diagram that cannot go stale, an architecture write-up with trade-offs, an interview-ready story, and a list of gaps for Week 4.

## What changed (vs Day 20)

| Area | Change |
|---|---|
| Code cleanup | `graph.py` header rewritten as the single description of the workflow (design rules, no per-day patch notes), imports sorted; `ruff --select F,E9,E7` is clean **in every day folder 8–21** (unused imports removed) |
| Bug found while cleaning | Days 18–20 had a **duplicate** `is_retryable()` and duplicated retry settings (a patch applied twice) – removed everywhere; all tests re-run green |
| Diagram | `scripts/draw_graph.py` generates `docs/graph.md` (Mermaid) from the compiled graph |
| Verification | `scripts/e2e_smoke.py`: 12 live scenarios through the real API (OpenAI + FAISS + temp SQLite): smalltalk, clarify, fact, comparison, refusal, both tools, 3-turn memory with follow-up and fact recall, input validation → **12/12 passed** |
| Docs | `docs/ARCHITECTURE.md`: flow, node table, trade-offs with evidence, data notes |
| Tests | unchanged 222 offline tests, all pass |

## "What I built" – 2-minute story

> I built a graph-based assistant over an Israel knowledge base. Every request goes through a router that decides the cheapest path: greetings and arithmetic never touch a model, knowledge questions go through FAISS retrieval, and if the retrieved evidence is weak the system refuses *before* calling the LLM – that is how hallucination stayed at zero on my unanswerable and trap questions. Tools (calculator, weighted score, topic listing) are validated on input and output. Every node that can fail is wrapped: transient errors are retried once in a single, visible layer, everything else lands in a fallback node that answers honestly and still shows the best evidence. Per-session SQLite memory resolves follow-ups ("How do visitors reach *it*?") and keeps durable facts, but is never treated as a source of facts. I evaluate with a 36-case set and an LLM judge (97 % pass), and I use it to *reject* changes too – a stricter prompt tied with the simple one, so I kept the simple one.

## Review notes (steps 4, 7)

- **Prompt + eval:** what improved quality was *retrieval*, not prompting: sibling-chunk expansion (Day 13, 82 → 100 %) and topic-aware ranking (Day 9, precision 0.43 → 0.91). Prompt v2 measured no better than v1.
- **Data:** topic-prefixed embeddings and metadata helped; memory adds context only when a follow-up needs it; the data set is tiny and clean, so it cannot show scaling problems.

## Gaps to work on in Week 4

1. Packaging: `requirements.txt` pinning, Docker (Day 22).
2. Observability: request IDs, structured logs, per-node timing in one place (Day 23).
3. Cost/tokens: not measured at all yet (Day 24).
4. Guardrails: prompt-extraction request got an indirect refusal from the judge (Day 25).
5. Tests: many mocks, few contract/integration tests; no coverage number (Day 26).
6. CI + `.env.example` + lint config (Day 27); note `.gitignore` currently ignores `.env.*`, which would also hide `.env.example`.
7. Multi-user hardening: in-process rate limiter and single-node SQLite.
8. Bigger, harder eval set and a held-out split.

## Run & test

```bash
cd Day21
python -m pytest tests -q                 # 222 offline tests
python -m scripts.e2e_smoke               # live, needs OPENAI_API_KEY
python -m scripts.draw_graph              # regenerate docs/graph.md
```
