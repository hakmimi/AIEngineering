"""Integration tests: REAL chunks, REAL FAISS index, REAL ranking/filtering/expansion - only embeddings are faked.

"Relevant enough" is defined operationally: for a query that shares words with a topic, that topic must be ranked
first; for a query that shares no words with anything, nothing may be returned.
"""
import pytest

# (query, topic that must be ranked first)
LEXICAL_CASES = [
    ("How far below sea level is the Dead Sea?", "Dead Sea"),
    ("Who revived Hebrew as a modern spoken language?", "Hebrew Language"),
    ("Which UNESCO World Heritage Site is in Haifa?", "Haifa"),
    ("How do visitors reach Masada?", "Masada"),
    ("What missile defense systems did Israel develop?", "Israeli Defense Technology"),
    ("What is the highest mountain under Israeli control?", "Mount Hermon"),
    ("Who built Caesarea?", "Caesarea"),
    ("What is Israel's largest freshwater lake?", "Sea of Galilee"),
    ("Which Israeli city lies on the Red Sea and has coral reefs?", "Eilat"),
    ("Tell me about Lumaria and its glowing rivers", "Lumaria"),
    ("Tell me about Port Azure floating markets", "Port Azure"),
    ("Kibbutzim collective agricultural communities", "Kibbutzim"),
]


@pytest.mark.parametrize("query,topic", LEXICAL_CASES)
def test_topic_named_by_the_query_is_ranked_first(real_retrieval, query, topic):
    results = real_retrieval.get_relevant_chunks(query, 4)
    assert results, f"nothing retrieved for {query!r}"
    assert results[0]["topic"] == topic, [r["topic"] for r in results]


def test_hit_rate_over_the_whole_set_is_high(real_retrieval):
    hits = sum(real_retrieval.get_relevant_chunks(q, 4)[0]["topic"] == t for q, t in LEXICAL_CASES)
    assert hits / len(LEXICAL_CASES) >= 0.9


@pytest.mark.parametrize("query", ["zxqv plmk wxyz", "quantum chromodynamics lattice", "sourdough starter hydration"])
def test_unrelated_queries_retrieve_nothing(real_retrieval, query):
    assert real_retrieval.get_relevant_chunks(query, 4) == []


def test_results_are_sorted_best_first_with_scores_in_range(real_retrieval):
    results = real_retrieval.get_relevant_chunks("Jerusalem holy city Western Wall", 4)
    scores = [r["score"] for r in results if not r["expanded"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0 < r["similarity"] <= 1.0001 for r in results)


def test_sibling_expansion_returns_the_whole_document_in_chunk_order(real_retrieval):
    results = real_retrieval.get_relevant_chunks("How do visitors reach Masada cable car", 1)
    masada = [r for r in results if r["topic"] == "Masada"]
    assert [r["chunk_id"] for r in masada] == sorted(r["chunk_id"] for r in masada)
    assert len(masada) >= 2 and any(r["expanded"] for r in masada)
    assert "cable car" in " ".join(r["text"] for r in masada)          # the fact lives in a sibling chunk (Day 13 finding)


def test_metadata_filter_only_returns_that_category(real_retrieval):
    results = real_retrieval.get_relevant_chunks("technology startups innovation", 6, {"category": "technology"})
    assert results and {r["category"] for r in results} == {"technology"}
    assert real_retrieval.get_relevant_chunks("technology startups innovation", 6, {"category": "history"}) is not None


def test_topic_filter_is_exact(real_retrieval):
    results = real_retrieval.get_relevant_chunks("city on the coast", 6, {"topic": "Haifa"})
    assert results and {r["topic"] for r in results} == {"Haifa"}


def test_top_k_is_respected_before_expansion(real_retrieval):
    many = real_retrieval.get_relevant_chunks("Israel", 10)
    assert len({(r["doc_id"], r["chunk_id"]) for r in many}) == len(many)                # no duplicates
    assert len(many) <= real_retrieval.settings.max_context_chunks


def test_complex_queries_can_cover_two_topics(real_retrieval):
    results = real_retrieval.get_relevant_chunks("Compare Tel Aviv and Haifa", 6, None, wide=True)
    assert {"Tel Aviv", "Haifa"} <= {r["topic"] for r in results}


def test_the_index_matches_the_documents(fake_index):
    _, store = fake_index
    import json
    docs = json.load(open("data/docs.json", encoding="utf8"))
    assert {m["doc_id"] for m in store.metadata} == {d["id"] for d in docs}     # every document is searchable
    assert store.index.ntotal == len(store.metadata) > 50
