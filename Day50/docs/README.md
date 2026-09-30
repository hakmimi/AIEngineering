# Documentation index

| Read this | For |
|---|---|
| [SYSTEM.md](SYSTEM.md) | diagrams: context, request sequence, LLM boundaries, queue, configuration |
| [ARCHITECTURE.md](ARCHITECTURE.md) | layers, safety principles, decision log |
| [DESIGN.md](DESIGN.md) | data contracts and design choices |
| [EVALUATION.md](EVALUATION.md) | how quality is measured and what the numbers mean |
| [graph.md](graph.md) | the compiled workflow graph (generated) |
| [API.md](API.md) | endpoints and schemas (generated) |

Generated files are checked by a test, so they cannot silently go stale:
`python -m scripts.draw_graph` and `python -m scripts.make_api_docs`.
