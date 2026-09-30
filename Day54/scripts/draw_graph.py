"""Generate docs/graph.md (Mermaid) from the compiled decision graph, so the diagram cannot go stale."""
from config import settings
from decision_graph import decision_graph

mermaid = decision_graph.get_graph().draw_mermaid()
out = settings.base_dir / "docs" / "graph.md"
out.write_text("# Decision workflow (generated - run `python -m scripts.draw_graph`)\n\n```mermaid\n" + mermaid + "\n```\n", encoding="utf8")
print(f"wrote {out}")
