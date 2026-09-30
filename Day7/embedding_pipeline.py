import json
import logging

from chunk import chunk_text
from config import settings
from embeddings import get_embedding

logger = logging.getLogger(__name__)


def build_embedded_chunks() -> list[dict]:
    with settings.docs_path.open("r", encoding="utf8") as f:
        docs = json.load(f)

    embedded = []
    seen = set()
    for doc in docs:
        for chunk_id, text in enumerate(chunk_text(doc.get("text", ""))):
            if text in seen:  # exact duplicates only add noise
                continue
            seen.add(text)
            embedded.append({
                "doc_id": doc.get("id"),
                "chunk_id": chunk_id,
                "text": text,
                "embedded_text": get_embedding(text),
            })
    return embedded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    chunks = build_embedded_chunks()
    with settings.embedded_chunks_path.open("w", encoding="utf8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    logger.info("Wrote %s chunks to %s", len(chunks), settings.embedded_chunks_path)
