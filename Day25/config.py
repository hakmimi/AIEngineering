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
    retrieval_threshold: float = float(os.getenv("RETRIEVAL_THRESHOLD", "0.40"))
    max_context_chars: int = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))
    openai_timeout_seconds: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))
    openai_max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "0"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    # Day 5: reliability knobs
    min_chunk_words: int = int(os.getenv("MIN_CHUNK_WORDS", "5"))
    min_chunk_score: float = float(os.getenv("MIN_CHUNK_SCORE", "0.30"))
    keyword_boost: float = float(os.getenv("KEYWORD_BOOST", "0.10"))
    min_context_chunks: int = int(os.getenv("MIN_CONTEXT_CHUNKS", "1"))
    # Day 6: routing + latency
    min_query_words: int = int(os.getenv("MIN_QUERY_WORDS", "2"))
    complex_query_words: int = int(os.getenv("COMPLEX_QUERY_WORDS", "12"))
    faiss_index_path: Path = BASE_DIR / "data" / "faiss.index"
    faiss_meta_path: Path = BASE_DIR / "data" / "faiss_meta.json"
    faiss_candidate_multiplier: int = int(os.getenv("FAISS_CANDIDATE_MULTIPLIER", "3"))
    # Day 9: retrieval quality
    categories_path: Path = BASE_DIR / "data" / "categories.json"
    topic_boost: float = float(os.getenv("TOPIC_BOOST", "0.15"))
    relative_score_margin: float = float(os.getenv("RELATIVE_SCORE_MARGIN", "0.12"))
    # Day 12: memory
    sessions_path: Path = BASE_DIR / "data" / "sessions.json"      # Day 12 JSON store (legacy)
    memory_db_path: Path = BASE_DIR / "data" / "memory.db"          # Day 19 SQLite store
    memory_max_turns: int = int(os.getenv("MEMORY_MAX_TURNS", "6"))
    memory_max_sessions: int = int(os.getenv("MEMORY_MAX_SESSIONS", "500"))
    memory_prompt_chars: int = int(os.getenv("MEMORY_PROMPT_CHARS", "1200"))
    # Day 13: fixes found by evaluation
    expand_siblings: bool = os.getenv("EXPAND_SIBLINGS", "1") == "1"
    max_context_chunks: int = int(os.getenv("MAX_CONTEXT_CHUNKS", "8"))
    complex_margin: float = float(os.getenv("COMPLEX_SCORE_MARGIN", "0.30"))
    # Day 16: routing
    llm_routing: bool = os.getenv("LLM_ROUTING", "0") == "1"   # off = rules only (free, deterministic)
    # Day 18: retries
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "3"))          # total tries, incl. the first
    retry_base_delay: float = float(os.getenv("RETRY_BASE_DELAY", "0.5"))  # seconds; doubles each retry
    # Day 24: cost control. Context is capped in TOKENS (estimated) rather than characters (0 = no cap; 400 = default guardrail).
    max_context_tokens: int = int(os.getenv("MAX_CONTEXT_TOKENS", "400"))
    # The strict JSON schema is already enforced by the API; repeating it in the prompt only costs input tokens.
    json_schema_in_prompt: bool = os.getenv("JSON_SCHEMA_IN_PROMPT", "0") == "1"
    slow_request_ms: float = float(os.getenv("SLOW_REQUEST_MS", "3000"))


settings = Settings()
