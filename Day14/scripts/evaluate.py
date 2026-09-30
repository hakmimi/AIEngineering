"""Evaluation harness: run the system on a labelled question set and score it.

    python -m scripts.evaluate run <label> [rag|multistep|assistant]     run + save data/eval/results_<label>.json/.csv
    python -m scripts.evaluate stability <a> <b>                identical-answer rate between two runs
    python -m scripts.evaluate compare <labelA> <labelB>       metric deltas between two saved runs

Scoring (all deterministic, no LLM judge - that comes on Day 20):
  retrieval_hit  expected topic(s) appear in the retrieved chunks ("any" or "all")
  keyword_score  share of required keyword groups present in the answer (each group = any-of)
  refused        the answer is a refusal ("not enough information")
  passed         answerable: not refused AND keyword_score == 1 ; should_refuse: refused
"""
import csv
import json
import logging
import statistics
import sys
import time
from collections import defaultdict

from config import settings

EVAL_DIR = settings.base_dir / "data" / "eval"
REFUSAL_MARKERS = ("don't have enough information", "do not have enough information", "not enough information",
                   "does not provide", "doesn't provide", "cannot answer", "can't answer")


def is_refusal(answer: str | None) -> bool:
    text = (answer or "").lower().replace("’", "'")
    return any(marker in text for marker in REFUSAL_MARKERS)


def keyword_score(answer: str | None, groups: list[list[str]]) -> float:
    if not groups:
        return 1.0
    text = (answer or "").lower()
    return sum(any(k.lower() in text for k in group) for group in groups) / len(groups)


def retrieval_hit(topics: list[str], expected: list[str], mode: str) -> bool | None:
    if not expected:
        return None  # nothing to retrieve (out of domain)
    found = [t in topics for t in expected]
    return all(found) if mode == "all" else any(found)


def score_case(case: dict, result: dict, latency_ms: float) -> dict:
    topics = [c.get("topic") for c in result.get("retrieved_chunks", [])]
    refused = is_refusal(result.get("answer"))
    kw = keyword_score(result.get("answer"), case["must_include"])
    passed = refused if case["should_refuse"] else (not refused and kw == 1.0)
    return {"id": case["id"], "type": case["type"], "question": case["question"], "answer": result.get("answer"),
            "source": result.get("source"), "should_refuse": case["should_refuse"], "refused": refused,
            "retrieval_hit": retrieval_hit(topics, case["expected_topics"], case["topic_match"]),
            "keyword_score": round(kw, 2), "passed": passed, "latency_ms": round(latency_ms, 1),
            "retrieved_topics": topics}


def summarize(rows: list[dict]) -> dict:
    answerable = [r for r in rows if not r["should_refuse"]]
    unanswerable = [r for r in rows if r["should_refuse"]]
    hits = [r["retrieval_hit"] for r in rows if r["retrieval_hit"] is not None]
    lat = sorted(r["latency_ms"] for r in rows)
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r["passed"])
    return {
        "cases": len(rows),
        "accuracy": round(sum(r["passed"] for r in rows) / len(rows), 3),
        "answerable_pass_rate": round(sum(r["passed"] for r in answerable) / max(len(answerable), 1), 3),
        "refusal_pass_rate": round(sum(r["passed"] for r in unanswerable) / max(len(unanswerable), 1), 3),
        "hallucination_rate": round(sum(not r["refused"] for r in unanswerable) / max(len(unanswerable), 1), 3),
        "false_refusal_rate": round(sum(r["refused"] for r in answerable) / max(len(answerable), 1), 3),
        "retrieval_hit_rate": round(sum(hits) / max(len(hits), 1), 3),
        "avg_keyword_score": round(statistics.mean(r["keyword_score"] for r in answerable), 3),
        "latency_p50_ms": round(statistics.median(lat), 1),
        "latency_p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1),
        "by_type": {t: round(sum(v) / len(v), 2) for t, v in by_type.items()},
    }


def get_system(name: str):
    if name == "multistep":
        from pipeline import run_pipeline
        return lambda q: run_pipeline(q, 4)
    if name == "assistant":  # the complete system, each question in a throwaway session
        import uuid

        from assistant import ask
        return lambda q: ask(f"eval-{uuid.uuid4().hex[:8]}", q, 4)
    from rag import get_rag_answer
    return lambda q: get_rag_answer(q, 4)


def run(label: str, system_name: str = "rag") -> dict:
    logging.disable(logging.CRITICAL)
    cases = json.loads((EVAL_DIR / "eval_set.json").read_text(encoding="utf8"))
    system, rows = get_system(system_name), []
    for case in cases:
        started = time.perf_counter()
        result = system(case["question"])
        rows.append(score_case(case, result, (time.perf_counter() - started) * 1000))
        print(f"{'PASS' if rows[-1]['passed'] else 'FAIL'} {case['id']} [{case['type']}] {case['question'][:55]}")
    summary = {"label": label, "system": system_name, **summarize(rows)}
    (EVAL_DIR / f"results_{label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf8")
    with (EVAL_DIR / f"results_{label}.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[k for k in rows[0] if k != "retrieved_topics"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, indent=1))
    for r in rows:
        if not r["passed"]:
            print(f"\n--- FAIL {r['id']} ({r['type']}): {r['question']}\n    refused={r['refused']} kw={r['keyword_score']} topics={r['retrieved_topics']}\n    answer: {str(r['answer'])[:220]}")
    return summary


def compare(a: str, b: str) -> None:
    sa, sb = (json.loads((EVAL_DIR / f"results_{x}.json").read_text(encoding="utf8"))["summary"] for x in (a, b))
    for key in sa:
        if isinstance(sa[key], (int, float)) and key != "cases":
            print(f"{key:24} {a}={sa[key]:<8} {b}={sb[key]:<8} delta={sb[key] - sa[key]:+.3f}")


def stability(a: str, b: str) -> None:
    """Same questions, two runs: how many answers are word-for-word identical? (temperature is 0)"""
    ra, rb = (json.loads((EVAL_DIR / f"results_{x}.json").read_text(encoding="utf8"))["rows"] for x in (a, b))
    same = sum(x["answer"] == y["answer"] for x, y in zip(ra, rb))
    verdict = sum(x["passed"] == y["passed"] for x, y in zip(ra, rb))
    print(f"identical answers: {same}/{len(ra)}   same pass/fail verdict: {verdict}/{len(ra)}")


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "run":
        run(sys.argv[2], *(sys.argv[3:4] or ["rag"]))
    elif command == "stability":
        stability(sys.argv[2], sys.argv[3])
    elif command == "compare":
        compare(sys.argv[2], sys.argv[3])
