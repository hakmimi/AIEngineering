import json
from similarity import cosine_similarity
from embeddings import get_embedding
import time
import logging
from functools import lru_cache

from config import settings
from errors import DataStoreError

logging.basicConfig(level=logging.INFO,
                       format= "%(asctime)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_embedded_chunks() -> list[dict]:
    try:
        # Original code opened data/embedded_chunks.json on every request using a relative path.
        with settings.embedded_chunks_path.open('r', encoding='utf-8') as f:
            chunks = json.load(f)
    except FileNotFoundError as exc:
        raise DataStoreError("Embedded chunks file was not found") from exc
    except json.JSONDecodeError as exc:
        raise DataStoreError("Embedded chunks file contains invalid JSON") from exc

    if not isinstance(chunks, list):
        raise DataStoreError("Embedded chunks file must contain a list")

    return chunks


def get_relevant_chunks(query: str,top_k: int=4):
    started_at = time.time()
    top_k = max(1, min(top_k, settings.max_top_k))
    query_embedding = get_embedding(query)
    chunks = load_embedded_chunks()
    results = []

    for chunk in chunks:
        try:
            score = cosine_similarity(query_embedding,chunk['embedded_text'])
            results.append({'doc_id':chunk['doc_id'],
                            'chunk_id':chunk['chunk_id'],
                            'text' : chunk['text'],
                            'score': score
            })
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping invalid embedded chunk: %s", exc)
        
    results = sorted(results,key = lambda x: x['score'] , reverse=True)
    logging.info(f"Request took {time.time() - started_at:.2f} seconds")
    return(results[:top_k])
    
        

# retrieval / llm call

