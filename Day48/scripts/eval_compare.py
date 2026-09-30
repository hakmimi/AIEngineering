"""Compare two stored evaluation runs (before/after a fix).

    python -m scripts.eval_compare v1 v2
"""
import json
import sys

from config import settings

EVAL_DIR = settings.data_dir / "eval"
METRICS = ["pass_rate", "action_accuracy", "route_accuracy", "provider_accuracy", "explanation_avg_score", "latency_p50_ms", "total_cost_usd"]


def load(label: str) -> dict:
    return json.loads((EVAL_DIR / f"full_{label}.json").read_text(encoding="utf8"))


def compare(a: str, b: str) -> dict:
    ra, rb = load(a), load(b)
    out = {"from": a, "to": b, "versions": [ra["summary"].get("agent_version", "v1 (untagged)"), rb["summary"].get("agent_version", "v1 (untagged)")], "metrics": {}}
    for mode in ("baseline", "ai"):
        for key in METRICS:
            old, new = ra["summary"][mode][key], rb["summary"][mode][key]
            out["metrics"][f"{mode}.{key}"] = {"before": old, "after": new, "delta": round(new - old, 4)}
        out["metrics"][f"{mode}.unsafe_errors"] = {"before": ra["summary"][mode]["errors"].get("unsafe_error", 0),
                                                   "after": rb["summary"][mode]["errors"].get("unsafe_error", 0)}
    old_rows = {r["case_id"]: r for r in ra["rows"]}
    common = [r for r in rb["rows"] if r["case_id"] in old_rows]                 # only cases both runs saw are comparable
    out["new_cases_only_in_second_run"] = [r["case_id"] for r in rb["rows"] if r["case_id"] not in old_rows]
    for mode in ("baseline", "ai"):
        out[f"{mode}_common_pass_rate"] = {"before": round(sum(r[f"{mode}_pass"] for r in old_rows.values()) / len(old_rows), 3),
                                           "after": round(sum(r[f"{mode}_pass"] for r in common) / len(common), 3), "cases": len(common)}
        out[f"{mode}_fixed"] = [r["case_id"] for r in common if r[f"{mode}_pass"] and not old_rows[r["case_id"]][f"{mode}_pass"]]
        out[f"{mode}_regressed"] = [r["case_id"] for r in common if not r[f"{mode}_pass"] and old_rows[r["case_id"]][f"{mode}_pass"]]
        out[f"{mode}_still_failing"] = [r["case_id"] for r in common if not r[f"{mode}_pass"] and not old_rows[r["case_id"]][f"{mode}_pass"]]
        new = [r for r in rb["rows"] if r["case_id"] not in old_rows]
        out[f"{mode}_new_cases_pass_rate"] = round(sum(r[f"{mode}_pass"] for r in new) / len(new), 3) if new else None
    return out


def main(a: str, b: str) -> None:
    result = compare(a, b)
    print(f"{a} (agent {result['versions'][0]}) -> {b} (agent {result['versions'][1]})")
    for name, m in result["metrics"].items():
        delta = f"  delta {m['delta']:+}" if "delta" in m else ""
        print(f"  {name:30} {m['before']} -> {m['after']}{delta}")
    print(f"cases only in the second run (hold-out): {result['new_cases_only_in_second_run']}")
    for mode in ("baseline", "ai"):
        print(f"{mode}: common-case pass rate {result[f'{mode}_common_pass_rate']}  new-case pass rate {result[f'{mode}_new_cases_pass_rate']}")
        print(f"{mode}: fixed={result[f'{mode}_fixed']} regressed={result[f'{mode}_regressed']} still_failing={result[f'{mode}_still_failing']}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
