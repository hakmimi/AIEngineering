# Day 50 - Documentation and diagrams

## Goal
Someone new should understand the system in ten minutes: what it is, how a request flows, where the LLM may act, how to call it -
and the documentation must not rot.

## What changed
| File | Change |
|---|---|
| `docs/SYSTEM.md` (new) | Mermaid diagrams: system context, request sequence, LLM boundary, async queue; configuration layers; audit data model. |
| `docs/README.md` (new) | Index of all docs. |
| `docs/API.md` (new, generated) | Endpoint table and schemas from the FastAPI OpenAPI spec (`scripts/make_api_docs.py`). |
| `docs/graph.md` (regenerated) | Was out of date relative to the 16-node graph; now generated. The stale `docs_graph.mmd` (9 nodes) was deleted. |
| `docs/ARCHITECTURE.md` | Updated to end of Week 3 (operations layer, links). |
| `tests/test_docs.py` (new, 5 tests) | Generated docs equal the code, every endpoint is documented, relative links resolve, code fences are balanced. |

## How implemented
Anything derivable from code is generated (graph from the compiled LangGraph, API from OpenAPI); anything that explains
*why* is hand-written. A test fails when a generated file is stale - changing an endpoint without regenerating the docs breaks the build.

## Caveats
- Mermaid renders on GitHub and in most editors, but was not rendered in a browser here; the test only checks syntax basics (balanced fences), not diagram validity.
- API.md summaries are the first docstring line of each endpoint; two endpoints (`/health`, `/jobs`) have generic summaries because they lack docstrings.
