import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    docs_path: Path = BASE_DIR / "data" / "docs.json"
    embedded_chunks_path: Path = BASE_DIR / "data" / "embedded_chunks.json"
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


settings = Settings()
