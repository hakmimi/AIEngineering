"""Rule-based vs LLM-based routing on labelled queries.  Run: python -m scripts.routing_eval

Labelling policy: the router decides HOW to process a message, not whether the topic is covered
(that is retrieval's job) - so "capital of France" is expected to route to rag/simple.
"""
import json
import logging

from config import settings
from intent import llm_classify, rule_classify

# (message, expected route, expected query_type)
CASES = [
    ("hello", "direct", "simple"), ("thanks a lot", "direct", "simple"), ("good morning", "direct", "simple"),
    ("bye", "direct", "simple"),
    ("ok", "fallback", "simple"), ("Jerusalem", "fallback", "simple"), ("asdfgh", "fallback", "simple"),
    ("it", "fallback", "simple"),
    ("Where is Masada?", "rag", "simple"), ("Tell me about Eilat", "rag", "simple"),
    ("What is the Dead Sea?", "rag", "simple"), ("How high is Mount Hermon?", "rag", "simple"),
    ("Who built Caesarea?", "rag", "simple"), ("What is the capital of France?", "rag", "simple"),
    ("How do visitors reach Masada?", "rag", "simple"), ("Why is the Dead Sea so salty?", "rag", "simple"),
    ("Compare Tel Aviv and Haifa", "rag", "complex"),
    ("Why is Jerusalem holy to three religions?", "rag", "complex"),
    ("What is the relationship between Israeli universities and startups?", "rag", "complex"),
    ("Explain how Israel handles water scarcity and agriculture", "rag", "complex"),
    ("What is the difference between Carmel Market and Mahane Yehuda?", "rag", "complex"),
    ("Tell me about Galilee, the Golan Heights and the Sea of Galilee", "rag", "complex"),
]


def evaluate(classifier) -> dict:
    rows = []
    for message, route, qtype in CASES:
        d = classifier(message)
        rows.append({"message": message, "expected": [route, qtype], "got": [d.route, d.query_type],
                     "route_ok": d.route == route, "type_ok": d.query_type == qtype or route != "rag"})
    n = len(rows)
    return {"route_accuracy": round(sum(r["route_ok"] for r in rows) / n, 3),
            "type_accuracy_on_rag": round(sum(r["type_ok"] for r in rows if r["expected"][0] == "rag") /
                                          sum(r["expected"][0] == "rag" for r in rows), 3),
            "wrong": [r for r in rows if not (r["route_ok"] and r["type_ok"])]}


def main() -> None:
    logging.disable(logging.CRITICAL)
    results = {"rules": evaluate(rule_classify), "llm": evaluate(llm_classify)}
    for name, res in results.items():
        print(f"\n{name}: route_accuracy={res['route_accuracy']} type_accuracy_on_rag={res['type_accuracy_on_rag']}")
        for w in res["wrong"]:
            print(f"   wrong: {w['message']!r} expected={w['expected']} got={w['got']}")
    (settings.base_dir / "data" / "routing_eval.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf8")


if __name__ == "__main__":
    main()
