try:  # use the OS certificate store (fixes SSL errors behind corporate proxies / antivirus on Windows)
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
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    app_api_key: str | None = os.getenv("APP_API_KEY")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    openai_timeout_seconds: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))
    openai_max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "0"))     # app-level retry is the only retry layer
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "3"))
    retry_base_delay: float = float(os.getenv("RETRY_BASE_DELAY", "0.5"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "600"))
    max_amount: float = float(os.getenv("MAX_AMOUNT", "1000000"))
    # Day 31: baseline decision thresholds (risk is 0-1)
    risk_decline: float = float(os.getenv("RISK_DECLINE", "0.70"))
    risk_review: float = float(os.getenv("RISK_REVIEW", "0.45"))
    llm_max_explanation_chars: int = int(os.getenv("LLM_MAX_EXPLANATION_CHARS", "600"))
    card_test_max_usd: float = float(os.getenv("CARD_TEST_MAX_USD", "5"))
    amount_anomaly_multiple: float = float(os.getenv("AMOUNT_ANOMALY_MULTIPLE", "30"))
    chargeback_review_count: int = int(os.getenv("CHARGEBACK_REVIEW_COUNT", "3"))
    fast_path_enabled: bool = os.getenv("FAST_PATH", "1") == "1"
    fast_path_max_risk: float = float(os.getenv("FAST_PATH_MAX_RISK", "0.15"))
    fast_path_amount_multiple: float = float(os.getenv("FAST_PATH_AMOUNT_MULTIPLE", "3"))
    audit_db_path: Path = BASE_DIR / "data" / "audit.db"
    new_customer_review_usd: float = float(os.getenv("NEW_CUSTOMER_REVIEW_USD", "1000"))


settings = Settings()
