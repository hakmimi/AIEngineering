"""Measure retrieval quality on labelled queries (hit@1, hit@3, MRR) and save a labelled run.

Usage: python retrieval_quality.py <label>      e.g. `baseline` (before) or `improved` (after)
Compare runs with: python retrieval_quality.py compare baseline improved
"""
import json
import sys

from config import settings
from retrieval import get_relevant_chunks

# (query, acceptable topics, optional metadata filters)
CASES = [
    ("Why is Jerusalem holy to three religions?", {"Jerusalem"}, None),
    ("Where can I float effortlessly in very salty water?", {"Dead Sea"}, None),
    ("Which city is known for startups and nightlife?", {"Tel Aviv", "Startup Nation"}, None),
    ("Ancient fortress on a plateau where rebels made a last stand", {"Masada"}, None),
    ("Huge erosion crater in the southern desert", {"Ramon Crater", "Negev Desert"}, None),
    ("How does Israel desalinate and recycle water?", {"Water Technology"}, None),
    ("Which country cyber defense companies are based there?", {"Israeli Cybersecurity"}, None),
    ("Tell me about the Roman port city with an amphitheatre", {"Caesarea"}, None),
    ("Communal agricultural settlements", {"Kibbutzim"}, None),
    ("What is the Israeli space agency doing?", {"Israeli Space Program"}, None),
    ("Wine regions and wineries", {"Israeli Wine Industry"}, None),
    ("Tell me about Lumaria", {"Lumaria"}, None),
    ("Port Azure harbour", {"Port Azure"}, None),
    ("Nerion Desert", {"Nerion Desert"}, None),
    ("Markets with spices and street food in the capital", {"Jerusalem Markets", "Carmel Market", "Israeli Food Markets"}, None),
    ("Where can I go skiing?", {"Mount Hermon"}, None),
    ("Lowest point on earth and a mineral lake", {"Dead Sea"}, None),
    ("Ancient Mediterranean harbour city with crusader tunnels", {"Akko", "Caesarea", "Jaffa"}, None),
    ("Mountain with skiing", {"Mount Hermon"}, {"category": "nature"}),
    ("Something about technology in the south", {"Beersheba", "Israeli Cybersecurity"}, {"category": "city"}),
]


def doc_topics() -> dict[int, str]:
    docs = json.loads(settings.docs_path.read_text(encoding="utf8"))
    return {d["id"]: d["topic"] for d in docs}


def run(label: str) -> dict:
    topics = doc_topics()
    rows, hit1, hit3, rr, prec, returned = [], 0, 0, 0.0, 0.0, 0
    for query, expected, filters in CASES:
        kwargs = {"filters": filters} if filters else {}
        results = get_relevant_chunks(query, 4, **kwargs)
        got = [topics[c["doc_id"]] for c in results]
        rank = next((i + 1 for i, t in enumerate(got) if t in expected), None)
        hit1 += rank == 1
        hit3 += bool(rank and rank <= 3)
        rr += 1 / rank if rank else 0
        prec += sum(t in expected for t in got) / len(got) if got else 0
        returned += len(got)
        rows.append({"query": query, "expected": sorted(expected), "got": got, "rank": rank})
    n = len(CASES)
    summary = {"label": label, "cases": n, "hit@1": round(hit1 / n, 3), "hit@3": round(hit3 / n, 3), "mrr": round(rr / n, 3),
               "precision": round(prec / n, 3), "avg_chunks": round(returned / n, 2)}
    (settings.base_dir / "data" / f"quality_{label}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf8")
    for r in rows:
        print(f"rank={r['rank']} | {r['query'][:60]:60} | {r['got'][:3]}")
    print(summary)
    return summary


def compare(a: str, b: str) -> None:
    sa, sb = (json.loads((settings.base_dir / "data" / f"quality_{x}.json").read_text(encoding="utf8"))["summary"] for x in (a, b))
    for metric in ("hit@1", "hit@3", "mrr", "precision", "avg_chunks"):
        print(f"{metric:6} {a}={sa[metric]:.3f} {b}={sb[metric]:.3f} delta={sb[metric] - sa[metric]:+.3f}")


if __name__ == "__main__":
    if sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
    else:
        run(sys.argv[1])
