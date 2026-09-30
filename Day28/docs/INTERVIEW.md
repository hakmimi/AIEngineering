# Interview notes - Israel Knowledge Assistant

## The 2-minute explanation (say this)

> "I built a production-minded RAG assistant, in about four weeks of daily increments, and I measured every step.
> Each request goes through a LangGraph workflow. First, cheap deterministic guardrails and a router decide the cheapest
> safe path: greetings and arithmetic never touch a model, prompt-injection attempts are blocked before anything expensive
> runs. Knowledge questions are embedded and searched in a persisted FAISS index, re-ranked with topic and keyword signals,
> and if the evidence is weak the system refuses *before* calling the LLM - that is what kept hallucination at zero on my
> unanswerable and trap questions. After generation an output guard checks the answer contract and rejects numbers that
> are not in the sources. Failures are contained per node - transient errors are retried once in a single visible layer,
> everything else goes to a fallback that answers honestly and still shows the best evidence. Per-session SQLite memory
> resolves follow-ups but is never treated as a source of facts. I track tokens and cost per request, log structured JSON
> with a request id, run 400 offline tests at 99 % coverage in CI, and evaluate with a judged 36-case set. The system
> is small and clean, so I treat the evaluation as regression safety rather than proof of scale."

## Questions I should be ready for

**Why a graph instead of functions?** The flow becomes inspectable data: per-node timing and tracing, uniform failure edges, branching that reads state, and later retries/persistence without rewriting steps. The LLM is one node, not the system.

**Why rules before the LLM?** Free, deterministic, explainable, testable. Measured: rule routing 100 % correct on the route decision; the LLM router fixed complexity (93 % → 100 %) but costs an extra call (~1 s). So rules by default, LLM as opt-in.

**How do you prevent hallucination?** Layers: (1) refuse when retrieval is weak, before the LLM; (2) grounded prompt with the refusal sentence; (3) output guard rejects numbers absent from the sources; (4) evaluation with trap questions ("exact height of Mount Hermon"). What I cannot claim: it works on messy real-world data.

**What was your biggest engineering surprise?** Live testing found problems unit tests missed: (a) stacked retries turned a 9 s failure into 25 s; (b) my own numeric guardrail blocked a correct answer because the model cited `[2:0,2:1; 5:0]`; (c) after changing embeddings, a fixed threshold started refusing valid questions. Lesson: measure guardrails for false positives on real model output; recalibrate thresholds when the embedding changes.

**How did you evaluate? What are the weaknesses of that?** Deterministic keyword eval (22 cases) + LLM judge (36 cases, three rubric scores with retrieved context shown) + guardrail/cost/routing evals. Weaknesses: small easy set, judge shares the model family, 100 % cannot discriminate between good systems (my two prompt versions tied).

**What would you do with real scale?** Bigger and adversarial eval set with a held-out split, human spot checks, hybrid retrieval (BM25 + vectors) and a reranker, an approximate index only beyond ~100k vectors, Redis/Postgres for memory and rate limits, a learned guardrail classifier next to the rules, prompt caching, real deployment with metrics/alerts.

**What does it cost?** ≈ $0.00012 per LLM request; free paths cost nothing; the biggest measured saving was removing a redundant schema from every prompt (-16 % cost) rather than trimming context.

## Five bullets for a CV / profile (all backed by measurements above)

- Built a LangGraph-based RAG assistant (FastAPI, FAISS, SQLite memory, tool use) with deterministic routing and guardrails; refused-before-LLM design kept hallucination at 0 % on 12 unanswerable/adversarial evaluation cases.
- Improved retrieval precision from 0.43 to 0.91 (topic-aware ranking, adaptive cutoff) and eval accuracy from 82 % to 100 % by diagnosing sibling-chunk misses from evaluation failures.
- Designed uniform failure handling (typed errors, single retry layer, fallback node with graceful degradation) validated with live failure drills; found and removed a retry-stacking latency amplification (25 s → ~9 s).
- Instrumented the service: JSON logs with request-ID tracing, per-node latency, token/cost tracking (-16 % cost at equal quality), and an LLM-judged evaluation runner.
- Shipped with 400 offline tests (99 % coverage), ruff, secret scanning, a coverage-gated GitHub Actions workflow and Docker packaging.
