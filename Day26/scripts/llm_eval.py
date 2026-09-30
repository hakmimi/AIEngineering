"""LLM evaluation runner: run the graph on a labelled set, score every answer with an LLM judge
(relevance, accuracy, groundedness, 1-5) plus a deterministic keyword check, save a results table.

    python -m scripts.llm_eval run <label> [v1|v2]        run + judge + save data/eval/llm_<label>.json/.csv
    python -m scripts.llm_eval compare <labelA> <labelB>  per-criterion deltas and the cases that changed

The judge sees the retrieved context, so *groundedness* = "is every claim supported by what was retrieved",
which is separate from *accuracy* = "does it match the reference facts".
"""
import csv
import json
import logging
import statistics
import sys
import time

from config import settings
from graph import run_graph
from llm import get_structured
from prompts import set_prompt_version

EVAL_DIR = settings.base_dir / "data" / "eval"
PASS_THRESHOLD = 4   # a case passes when relevance, accuracy and groundedness are all >= 4
REFUSAL_MARKERS = ("can only help with questions about israel", "couldn't understand that message", "don't have enough information", "do not have enough information", "not enough information",
                   "does not provide", "doesn't provide", "not covered", "not available", "not specified")

HARD_REFUSALS = ("can only help with questions about israel", "couldn't understand that message",
                 "don't have enough information", "do not have enough information", "not enough information")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevance": {"type": "integer", "minimum": 1, "maximum": 5},
        "accuracy": {"type": "integer", "minimum": 1, "maximum": 5},
        "groundedness": {"type": "integer", "minimum": 1, "maximum": 5},
        "explanation": {"type": "string"},
    },
    "required": ["relevance", "accuracy", "groundedness", "explanation"],
    "additionalProperties": False,
}

JUDGE_PROMPT = """You are a strict evaluator of a question-answering assistant. Score the ANSWER from 1 (bad) to 5 (excellent).

Rubric
- relevance: does it address what the question asks (a correct refusal of an unanswerable question is relevant = 5)?
- accuracy: does it agree with the REFERENCE FACTS and EXPECTED BEHAVIOR? Wrong or invented facts = 1-2. A correct refusal
  when the expected behavior is to refuse = 5. Refusing when facts were available = 1-2. Missing part of a multi-part
  answer = 3.
- groundedness: is every claim in the answer supported by the RETRIEVED CONTEXT? Any unsupported claim or number = 1-2.
  A refusal makes no claims = 5.

Question: {question}
Expected behavior: {expected}
Reference facts: {facts}
Retrieved context:
{context}

ANSWER:
{answer}"""


def judge(case: dict, result: dict) -> dict:
    context = "\n".join(f"[{c['doc_id']}:{c['chunk_id']}] {c['text']}" for c in result.get("retrieved_chunks", [])) or "(none)"
    prompt = JUDGE_PROMPT.format(question=case["question"], expected=case["expected_behavior"],
                                 facts=", ".join(case["key_facts"]) or "(none - must refuse)", context=context,
                                 answer=result.get("answer"))
    return get_structured(prompt, JUDGE_SCHEMA, "judge")


def keyword_pass(case: dict, answer: str) -> bool:
    text = (answer or "").lower().replace("’", "'")
    if case["should_refuse"]:
        return any(m in text for m in REFUSAL_MARKERS)
    return all(any(k.lower() in text for k in group) for group in case["must_include"]) and not any(m in text for m in HARD_REFUSALS)


def run(label: str, version: str = "v1") -> dict:
    logging.disable(logging.CRITICAL)
    set_prompt_version(version)
    cases = json.loads((EVAL_DIR / "llm_eval_set.json").read_text(encoding="utf8"))
    rows = []
    for case in cases:
        started = time.perf_counter()
        result = run_graph(case["question"])
        latency = (time.perf_counter() - started) * 1000
        scores = judge(case, result)
        row = {"id": case["id"], "category": case["category"], "question": case["question"], "answer": result["answer"],
               "source": result["source"], "relevance": scores["relevance"], "accuracy": scores["accuracy"],
               "groundedness": scores["groundedness"], "keyword_pass": keyword_pass(case, result["answer"]),
               "latency_ms": round(latency, 1), "judge_note": scores["explanation"]}
        row["passed"] = min(row["relevance"], row["accuracy"], row["groundedness"]) >= PASS_THRESHOLD
        rows.append(row)
        print(f"{'PASS' if row['passed'] else 'FAIL'} {row['id']} R{row['relevance']} A{row['accuracy']} G{row['groundedness']} "
              f"kw={'Y' if row['keyword_pass'] else 'N'} [{row['category']}] {row['question'][:50]}")
    summary = summarize(rows, label, version)
    (EVAL_DIR / f"llm_{label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf8")
    with (EVAL_DIR / f"llm_{label}.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, indent=1))
    return summary


def summarize(rows: list[dict], label: str = "", version: str = "") -> dict:
    agree = sum(r["passed"] == r["keyword_pass"] for r in rows) / len(rows)
    by_cat: dict[str, list[bool]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["passed"])
    return {"label": label, "prompt_version": version, "cases": len(rows),
            "pass_rate": round(sum(r["passed"] for r in rows) / len(rows), 3),
            "relevance": round(statistics.mean(r["relevance"] for r in rows), 2),
            "accuracy": round(statistics.mean(r["accuracy"] for r in rows), 2),
            "groundedness": round(statistics.mean(r["groundedness"] for r in rows), 2),
            "keyword_pass_rate": round(sum(r["keyword_pass"] for r in rows) / len(rows), 3),
            "judge_keyword_agreement": round(agree, 3),
            "latency_p50_ms": round(statistics.median(r["latency_ms"] for r in rows), 1),
            "by_category": {c: round(sum(v) / len(v), 2) for c, v in by_cat.items()}}


def compare(a: str, b: str) -> None:
    ra, rb = (json.loads((EVAL_DIR / f"llm_{x}.json").read_text(encoding="utf8")) for x in (a, b))
    for key in ("pass_rate", "relevance", "accuracy", "groundedness", "keyword_pass_rate", "latency_p50_ms"):
        va, vb = ra["summary"][key], rb["summary"][key]
        print(f"{key:20} {a}={va:<8} {b}={vb:<8} delta={vb - va:+.3f}")
    print("\ncases whose verdict changed:")
    by_id = {r["id"]: r for r in ra["rows"]}
    for r in rb["rows"]:
        old = by_id[r["id"]]
        if old["passed"] != r["passed"]:
            print(f"  {r['id']} {old['passed']} -> {r['passed']}  {r['question'][:60]}\n     {b}: {str(r['answer'])[:140]}\n     judge: {r['judge_note'][:160]}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], *(sys.argv[3:4] or ["v1"]))
    elif sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
