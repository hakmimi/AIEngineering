import re
import unicodedata

from config import settings


def clean_text(text: str) -> str:
    """Normalise raw document text: unicode form, control chars, markup, whitespace."""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"<[^>]+>", " ", text)  # stray HTML tags
    text = "".join(ch for ch in text if ch.isprintable() or ch.isspace())
    text = re.sub(r"\s+", " ", text)  # collapse whitespace/newlines
    return text.strip()


def chunk_text(text: str, chunk_size: int = 30) -> list[str]:
    words = clean_text(text).split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        # Drop tiny tail chunks: they embed poorly and add noise to retrieval.
        if len(chunk) >= settings.min_chunk_words:
            chunks.append(" ".join(chunk))
    return chunks
