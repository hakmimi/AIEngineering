"""Docs that are generated from code must match the code; hand-written docs must not link to files that do not exist."""
import re

from config import settings
from decision_graph import decision_graph
from scripts.make_api_docs import render

DOCS = settings.base_dir / "docs"


def test_api_reference_is_current():
    assert (DOCS / "API.md").read_text(encoding="utf8") == render(), "run: python -m scripts.make_api_docs"


def test_graph_diagram_is_current():
    assert decision_graph.get_graph().draw_mermaid() in (DOCS / "graph.md").read_text(encoding="utf8"), "run: python -m scripts.draw_graph"


def test_every_endpoint_is_documented():
    from main import app
    text = (DOCS / "API.md").read_text(encoding="utf8")
    assert all(f"`{path}`" in text for path in app.openapi()["paths"])


def test_relative_links_in_docs_resolve():
    for md in DOCS.glob("*.md"):
        for target in re.findall(r"\]\(([^)#]+\.md)\)", md.read_text(encoding="utf8")):
            assert (DOCS / target).exists(), f"{md.name} links to missing {target}"


def test_mermaid_blocks_are_closed():
    for md in DOCS.glob("*.md"):
        text = md.read_text(encoding="utf8")
        assert text.count("```mermaid") <= text.count("```") // 2 and text.count("```") % 2 == 0, md.name
