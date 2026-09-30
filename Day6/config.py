try:  # use the OS certificate store (fixes SSL errors behind corporate proxies / antivirus)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

@dataclass(frozen=True)
class Settings:
    base_dir : Path = BASE_DIR
    docs_path : Path = BASE_DIR / "data" / "docs.json"
    embedded_chunks_path : Path = BASE_DIR / "data" / "embedded_chunks.json"
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    app_api_key: str | None = os.getenv("APP_API_KEY")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    max_query_length: int = int(os.getenv("MAX_QUERY_LENGTH", "1000"))
    max_top_k: int = int(os.getenv("MAX_TOP_K", "10"))
    retrieval_threshold: float = float(os.getenv("RETRIEVAL_THRESHOLD", "0.55"))
    max_context_chars: int = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))
    openai_timeout_seconds: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))
    openai_max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    # Day 5: reliability knobs
    min_chunk_words: int = int(os.getenv("MIN_CHUNK_WORDS", "5"))
    min_chunk_score: float = float(os.getenv("MIN_CHUNK_SCORE", "0.30"))
    keyword_boost: float = float(os.getenv("KEYWORD_BOOST", "0.10"))
    min_context_chunks: int = int(os.getenv("MIN_CONTEXT_CHUNKS", "1"))
    # Day 6: routing + latency
    min_query_words: int = int(os.getenv("MIN_QUERY_WORDS", "2"))
    complex_query_words: int = int(os.getenv("COMPLEX_QUERY_WORDS", "12"))
    slow_request_ms: float = float(os.getenv("SLOW_REQUEST_MS", "3000"))


settings = Settings()
