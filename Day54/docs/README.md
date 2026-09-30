# Documentation index

| Read this | For |
|---|---|
| [SYSTEM.md](SYSTEM.md) | diagrams: context, request sequence, LLM boundaries, queue, configuration |
| [ARCHITECTURE.md](ARCHITECTURE.md) | layers, safety principles, decision log |
| [DESIGN.md](DESIGN.md) | data contracts and design choices |
| [INTERVIEW.md](INTERVIEW.md) | pitch, Q&A, numbers for interviews |
| [EVALUATION.md](EVALUATION.md) | how quality is measured and what the numbers mean |
| [FINAL_EVALUATION.md](FINAL_EVALUATION.md) | final results and their limits (generated from stored evidence) |
| [graph.md](graph.md) | the compiled workflow graph (generated) |
| [EXAMPLES.md](EXAMPLES.md) | real request/response pairs (generated with a live model) |
| [API.md](API.md) | endpoints and schemas (generated) |

Generated files are checked by a test, so they cannot silently go stale:
`python -m scripts.draw_graph` and `python -m scripts.make_api_docs`.
