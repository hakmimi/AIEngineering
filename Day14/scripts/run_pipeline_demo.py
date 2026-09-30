"""Run the multi-step pipeline (and the single-step RAG) on several query types; save intermediate outputs."""
import json
import logging
import sys

from config import settings
from pipeline import run_pipeline
from rag import get_rag_answer

QUERIES = [
    "Where is Masada?",
    "Compare Tel Aviv and Haifa",
    "Why is Jerusalem so important?",
    "Which markets have spices and street food?",
    "What is the capital of France?",
    "How does Israel deal with water scarcity?",
    "hello",
]


def main(out_name: str = "pipeline_runs.json") -> None:
    logging.disable(logging.CRITICAL)
    rows = []
    for q in QUERIES:
        multi, single = run_pipeline(q), get_rag_answer(q)
        rows.append({"query": q,
                     "multistep": {k: multi[k] for k in ("answer", "source", "route", "timings", "pipeline") if k in multi},
                     "single": {k: single[k] for k in ("answer", "source", "timings")}})
        pl = multi.get("pipeline", {})
        print(f"\nQ: {q}\n  analyze : {pl.get('search_query')} [{pl.get('intent')}]\n  facts   : {len(pl.get('facts', []))}"
              f"\n  multi   : ({multi['source']}, {multi['timings']['total_ms']:.0f}ms) {str(multi['answer'])[:170]}"
              f"\n  single  : ({single['source']}, {single['timings']['total_ms']:.0f}ms) {str(single['answer'])[:170]}")
    (settings.base_dir / "data" / out_name).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf8")


if __name__ == "__main__":
    main(*sys.argv[1:])
