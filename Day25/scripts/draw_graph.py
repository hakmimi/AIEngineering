"""Generate docs/graph.md (Mermaid) straight from the compiled LangGraph, so the diagram cannot go stale."""
from graph import rag_graph
from config import settings

mermaid = rag_graph.get_graph().draw_mermaid()
out = settings.base_dir / "docs" / "graph.md"
out.write_text(
    "# Workflow graph (generated - do not edit; run `python -m scripts.draw_graph`)\n\n"
    "```mermaid\n" + mermaid + "\n```\n", encoding="utf8")
print(f"wrote {out} ({len(mermaid.splitlines())} lines)")
