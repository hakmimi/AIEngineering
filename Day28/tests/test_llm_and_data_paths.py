"""Error/edge paths of the provider wrappers, retrieval data loading, the FAISS files and the embedding pipeline."""
import json
import os
import time
from types import SimpleNamespace

import httpx
import openai
import pytest

import embedding_pipeline
import embeddings
import llm
import openai_client
import retrieval
import security
import similarity
from errors import ConfigurationError, DataStoreError, ExternalServiceError
from vector_store import VectorStore, load_or_build_store


# --- provider wrappers: error classification --------------------------------------------------------------------
def _request():
    return httpx.Request("POST", "https://api.openai.com/v1/x")


def _api_error(cls, status=None):
    if cls in (openai.APIConnectionError, openai.APITimeoutError):
        return cls(request=_request())
    response = httpx.Response(status, request=_request())
    return cls("boom", response=response, body=None)


@pytest.mark.parametrize("error,retryable", [
    (_api_error(openai.APIConnectionError), True),
    (_api_error(openai.APITimeoutError), True),
    (_api_error(openai.RateLimitError, 429), True),
    (_api_error(openai.InternalServerError, 500), True),
    (_api_error(openai.AuthenticationError, 401), False),
    (_api_error(openai.BadRequestError, 400), False),
])
def test_provider_errors_are_classified_for_retry(monkeypatch, error, retryable):
    def boom(**kw):
        raise error

    client = SimpleNamespace(responses=SimpleNamespace(create=boom), embeddings=SimpleNamespace(create=boom))
    monkeypatch.setattr(llm, "get_client", lambda: client)
    monkeypatch.setattr(embeddings, "get_client", lambda: client)
    with pytest.raises(ExternalServiceError) as llm_exc:
        llm.get_answer("p")
    with pytest.raises(ExternalServiceError) as emb_exc:
        embeddings.get_embedding("t")
    assert llm_exc.value.retryable is retryable and emb_exc.value.retryable is retryable
    assert openai_client.is_retryable(error) is retryable


def _client_returning(text):
    return SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: SimpleNamespace(output_text=text, usage=None)))


def test_structured_call_with_invalid_json_is_an_error(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda: _client_returning("not json"))
    with pytest.raises(ExternalServiceError) as exc:
        llm.get_structured("p", {"type": "object"}, "x")
    assert exc.value.retryable is True


def test_get_answer_tolerates_a_model_that_ignores_the_format(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda: _client_returning("plain text answer"))
    assert llm.get_answer("p") == {"answer": "plain text answer", "confidence": 0.5, "score": 0}


def test_get_answer_parses_json(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda: _client_returning('{"answer": "a", "confidence": 0.7, "score": null, "extra": 1}'))
    assert llm.get_answer("p") == {"answer": "a", "confidence": 0.7, "score": None}


def test_missing_api_key_is_a_configuration_error(settings_override, monkeypatch):
    monkeypatch.setattr(openai_client, "_client", None)
    settings_override(openai_api_key=None)
    with pytest.raises(ConfigurationError):
        openai_client.get_client()


def test_client_is_created_once(settings_override, monkeypatch):
    monkeypatch.setattr(openai_client, "_client", None)
    settings_override(openai_api_key="sk-test")
    assert openai_client.get_client() is openai_client.get_client()


# --- retrieval data loading ---------------------------------------------------------------------------------------
@pytest.fixture
def fresh_chunk_cache():
    retrieval.load_embedded_chunks.cache_clear()
    yield
    retrieval.load_embedded_chunks.cache_clear()


def test_load_embedded_chunks_happy_path(tmp_path, settings_override, fresh_chunk_cache):
    path = tmp_path / "c.json"
    path.write_text(json.dumps([{"doc_id": 1}]), encoding="utf8")
    settings_override(embedded_chunks_path=path)
    assert retrieval.load_embedded_chunks() == [{"doc_id": 1}]


@pytest.mark.parametrize("content,message", [(None, "not found"), ("{broken", "invalid JSON"), ('{"a": 1}', "must contain a list")])
def test_load_embedded_chunks_failures(tmp_path, settings_override, fresh_chunk_cache, content, message):
    path = tmp_path / "c.json"
    if content is not None:
        path.write_text(content, encoding="utf8")
    settings_override(embedded_chunks_path=path)
    with pytest.raises(DataStoreError, match=message):
        retrieval.load_embedded_chunks()


def test_legacy_search_matches_the_faiss_path_and_skips_bad_chunks(tmp_path, settings_override, fresh_chunk_cache):
    chunks = [
        {"doc_id": 1, "chunk_id": 0, "topic": "A", "text": "alpha city", "embedded_text": [1.0, 0.0]},
        {"doc_id": 2, "chunk_id": 0, "topic": "B", "text": "beta", "embedded_text": [0.0, 1.0]},
        {"doc_id": 3, "chunk_id": 0, "topic": "C", "text": "broken", "embedded_text": [1.0]},     # wrong dimension
        {"doc_id": 4, "chunk_id": 0, "topic": "D", "text": "missing vector"},                       # no vector at all
    ]
    path = tmp_path / "c.json"
    path.write_text(json.dumps(chunks), encoding="utf8")
    settings_override(embedded_chunks_path=path)
    result = retrieval.legacy_search([1.0, 0.1], "alpha city", 3)
    assert result[0]["doc_id"] == 1 and {r["doc_id"] for r in result} <= {1, 2}


# --- FAISS files ---------------------------------------------------------------------------------------------------
CHUNKS = [{"doc_id": 1, "chunk_id": 0, "topic": "A", "text": "a", "embedded_text": [1.0, 0.0]},
          {"doc_id": 2, "chunk_id": 0, "topic": "B", "text": "b", "embedded_text": [0.0, 1.0]}]


@pytest.fixture
def index_files(tmp_path, settings_override):
    settings_override(embedded_chunks_path=tmp_path / "chunks.json", faiss_index_path=tmp_path / "i.index",
                      faiss_meta_path=tmp_path / "m.json")
    return tmp_path


def test_missing_everything_raises_a_helpful_error(index_files):
    with pytest.raises(DataStoreError, match="embedding_pipeline"):
        load_or_build_store()


def test_index_is_built_then_loaded_then_rebuilt_when_stale(index_files):
    (index_files / "chunks.json").write_text(json.dumps(CHUNKS), encoding="utf8")
    first = load_or_build_store()                                   # built + persisted
    assert (index_files / "i.index").exists() and first.index.ntotal == 2
    mtime = (index_files / "i.index").stat().st_mtime
    assert load_or_build_store().search([1, 0], 1)[0]["doc_id"] == 1
    assert (index_files / "i.index").stat().st_mtime == mtime       # loaded, not rebuilt

    newer = CHUNKS + [{"doc_id": 3, "chunk_id": 0, "topic": "C", "text": "c", "embedded_text": [0.7, 0.7]}]
    (index_files / "chunks.json").write_text(json.dumps(newer), encoding="utf8")
    future = time.time() + 5
    os.utime(index_files / "chunks.json", (future, future))         # source newer than the index
    assert load_or_build_store().index.ntotal == 3


def test_index_alone_is_enough_when_the_source_is_gone(index_files):
    VectorStore.build(CHUNKS).save(index_files / "i.index", index_files / "m.json")
    assert load_or_build_store().index.ntotal == 2


# --- embedding pipeline ----------------------------------------------------------------------------------------------
def test_pipeline_builds_chunks_with_metadata_and_topic_prefixed_embeddings(tmp_path, settings_override, monkeypatch):
    docs = [{"id": 1, "topic": "Masada", "text": "Masada is an ancient fortress located on a plateau near the Dead Sea. <b>Visitors</b> arrive by cable car."},
            {"id": 2, "topic": "Copy", "text": "Masada is an ancient fortress located on a plateau near the Dead Sea. <b>Visitors</b> arrive by cable car."}]
    (tmp_path / "docs.json").write_text(json.dumps(docs), encoding="utf8")
    (tmp_path / "cats.json").write_text(json.dumps({"Masada": "history"}), encoding="utf8")
    settings_override(docs_path=tmp_path / "docs.json", categories_path=tmp_path / "cats.json")
    embedded_inputs = []
    monkeypatch.setattr(embedding_pipeline, "get_embedding", lambda text: embedded_inputs.append(text) or [0.1, 0.2])
    chunks = embedding_pipeline.build_embedded_chunks()
    assert len(chunks) == 1                                          # the second document is an exact duplicate -> skipped
    c = chunks[0]
    assert c["topic"] == "Masada" and c["category"] == "history" and c["embedded_text"] == [0.1, 0.2]
    assert "<b>" not in c["text"] and "Visitors arrive" in c["text"]  # cleaned
    assert embedded_inputs == [f"Masada: {c['text']}"]                # embedded with the topic prefix, stored without it


def test_pipeline_uses_other_category_for_unknown_topics(tmp_path, settings_override, monkeypatch):
    (tmp_path / "docs.json").write_text(json.dumps([{"id": 9, "topic": "Mystery", "text": "one two three four five six seven"}]), encoding="utf8")
    (tmp_path / "cats.json").write_text("{}", encoding="utf8")
    settings_override(docs_path=tmp_path / "docs.json", categories_path=tmp_path / "cats.json")
    monkeypatch.setattr(embedding_pipeline, "get_embedding", lambda text: [0.0])
    assert embedding_pipeline.build_embedded_chunks()[0]["category"] == "other"


# --- small utilities -----------------------------------------------------------------------------------------------------
def test_cosine_similarity_edge_cases():
    assert similarity.cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert similarity.cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        similarity.cosine_similarity([1, 0], [1])
    with pytest.raises(ValueError):
        similarity.cosine_similarity([0, 0], [1, 0])


def test_rate_limiter_state_is_per_client(settings_override):
    settings_override(rate_limit_per_minute=1)
    security._requests_by_client.clear()
    a, b = SimpleNamespace(client=SimpleNamespace(host="1.1.1.1")), SimpleNamespace(client=SimpleNamespace(host="2.2.2.2"))
    security.rate_limit(a)
    security.rate_limit(b)                                             # different client: allowed
    with pytest.raises(Exception) as exc:
        security.rate_limit(a)
    assert getattr(exc.value, "status_code", None) == 429
    security._requests_by_client.clear()
