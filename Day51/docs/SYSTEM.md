# System overview (end of Week 3)

## Context

```mermaid
flowchart LR
    Client([Client / payment service]) -->|POST /decision, /decide, /jobs| API[FastAPI service]
    API --> Graph[[Decision graph]]
    Graph --> Rules[Rules + audited tools]
    Graph -->|explain / review| LLM[(OpenAI API)]
    Graph --> Audit[(SQLite audit table)]
    API --> Jobs[(SQLite job table)]
    Audit --> Metrics[metrics.py]
    Metrics --> Dash[Streamlit dashboard]
    Metrics --> Report[Markdown report + alerts]
    Cfg[/config.yaml + environment/] -.-> API
```

## One request, in time

```mermaid
sequenceDiagram
    participant C as Client
    participant A as API (auth, rate limit, validation)
    participant G as Graph
    participant L as LLM
    participant D as Audit DB
    C->>A: POST /decision {transaction}
    A->>G: run(transaction)
    G->>G: policy gate, input routing (no LLM)
    G->>G: risk tool, rules, provider + cost tools
    alt rules unambiguous (fast path)
        G->>G: template explanation
    else needs review
        G->>L: structured review request
        L-->>G: explanation, may escalate to review
        G->>G: numeric grounding check
    end
    G->>G: control rules, constraint guard
    G->>D: insert audit record (SHA-256)
    G-->>A: decision + trace + usage
    A-->>C: 200 {decision, decision_id, graph, usage}
```

## Where the LLM may and may not act

```mermaid
flowchart TD
    R[Rules decide action + provider] --> Q{LLM review}
    Q -->|agrees| K[keep rules decision]
    Q -->|escalate| E[route becomes manual_review]
    Q -->|fails / invalid / ungrounded| T[template explanation, rules decision]
    E --> G[constraint guard]
    K --> G
    T --> G
    G -->|policy violated| X[decline / review, logged at ERROR]
    G -->|ok| O[audit + respond]
```
The LLM has no path to `route` from `decline` or `manual_review`.

## Asynchronous work

```mermaid
flowchart LR
    S[POST /jobs] -->|202 + job id, idempotent by transaction id| Q[bounded asyncio queue]
    Q --> W1[worker 1..N]
    W1 --> G[async graph]
    G --> DB[(audit + job table)]
    Q -.->|full| B[429 backpressure]
    Poll[GET /status/id] --> DB
```

## Configuration and modes

| Layer | Source | Notes |
|---|---|---|
| 1 | code defaults | `config.py` |
| 2 | `config.yaml` | non-secret tunables, thresholds, model, temperature |
| 3 | environment | always wins; the only source of secrets |

`allowed_modes` (default `graph`) decides which of baseline / ai / graph `/decide` accepts; the other two lack the safety layers.

## Data model (audit table)

| Column group | Content |
|---|---|
| identity | decision_id, transaction_id, created_at, agent_version |
| outcome | action, provider, reason codes, risk score, explanation |
| process | route, graph trace, llm_status, fast_path, guard override |
| cost | tokens, estimated cost, latency |
| integrity | SHA-256 of the row |
