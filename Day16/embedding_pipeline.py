import json
import logging

from chunk import chunk_text
from config import settings
from embeddings import get_embedding

logger = logging.getLogger(__name__)


def build_embedded_chunks() -> list[dict]:
    with settings.docs_path.open("r", encoding="utf8") as f:
        docs = json.load(f)
    categories = json.loads(settings.categories_path.read_text(encoding="utf8"))

    embedded = []
    seen = set()
    for doc in docs:
        for chunk_id, text in enumerate(chunk_text(doc.get("text", ""))):
            if text in seen:  # exact duplicates only add noise
                continue
            seen.add(text)
            topic = doc.get("topic")
            embedded.append({
                "doc_id": doc.get("id"),
                "chunk_id": chunk_id,
                "topic": topic,                              # metadata used for filtering + ranking
                "category": categories.get(topic, "other"),
                "text": text,
                # contextual embedding: a bare chunk ("It is located...") loses its subject, so prefix the topic
                "embedded_text": get_embedding(f"{topic}: {text}"),
            })
    return embedded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    chunks = build_embedded_chunks()
    with settings.embedded_chunks_path.open("w", encoding="utf8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    logger.info("Wrote %s chunks to %s", len(chunks), settings.embedded_chunks_path)
