"""Application settings, layered:   code defaults  <  config.yaml  <  environment variables (and .env).

* `config.yaml` (committed) holds NON-secret tuning: model, temperature, thresholds, modes, file names. It documents every option.
* Environment variables override it (12-factor style, e.g. per-deployment or per-experiment): the variable is the field name in
  upper case (`LLM_MODEL`, `RISK_REVIEW`, ...). `FAST_PATH` is accepted as an alias of `fast_path_enabled`.
* Secrets (`OPENAI_API_KEY`, `APP_API_KEY`) come only from the environment / `.env`, never from the YAML file.
* `CONFIG_FILE` selects another YAML file (handy for experiments: same code, different config).

`Settings.snapshot()` is what gets logged per run and served by GET /config - it never contains secrets.
"""
try:  # use the OS certificate store (fixes SSL errors behind corporate proxies / antivirus on Windows)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
import logging
import os
from dataclasses import MISSING, dataclass, fields
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
logger = logging.getLogger("config")

SECRETS = ("openai_api_key", "app_api_key")
ALIASES = {"FAST_PATH": "fast_path_enabled"}                 # legacy environment variable names
MODES = ("baseline", "ai", "graph")


@dataclass(frozen=True)
class Settings:
    # --- where things are ------------------------------------------------------------------------------------------------------
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    providers_file: str = "providers.json"
    risk_tables_file: str = "risk_tables.json"
    transactions_file: str = "transactions.csv"
    policies_file: str = "policies.json"
    audit_db_path: Path | None = None                        # default: <data_dir>/audit.db
    jobs_db_path: Path | None = None                         # default: <data_dir>/jobs.db
    # --- secrets (environment only) -------------------------------------------------------------------------------------------
    openai_api_key: str | None = None
    app_api_key: str | None = None
    # --- which decision logic runs ----------------------------------------------------------------------------------------------
    decision_mode: str = "graph"                             # baseline | ai | graph (used by POST /decide when no ?mode= is given)
    allowed_modes: str = "graph"                             # comma-separated; experiments enable more, production keeps only "graph"
    # --- LLM -----------------------------------------------------------------------------------------------------------------
    llm_model: str = "gpt-4.1-mini"
    llm_temperature: float = 0.0
    llm_max_explanation_chars: int = 600
    openai_timeout_seconds: float = 20.0
    openai_max_retries: int = 0                               # the app-level retry is the only retry layer
    retry_attempts: int = 3
    retry_base_delay: float = 0.5
    # --- API -----------------------------------------------------------------------------------------------------------------
    rate_limit_per_minute: int = 600
    max_amount: float = 1_000_000.0
    # --- decision rules ------------------------------------------------------------------------------------------------------
    risk_decline: float = 0.70
    risk_review: float = 0.45
    new_customer_review_usd: float = 1000.0
    card_test_max_usd: float = 5.0
    amount_anomaly_multiple: float = 30.0
    chargeback_review_count: int = 3
    fast_path_enabled: bool = True
    fast_path_max_risk: float = 0.15
    fast_path_amount_multiple: float = 3.0
    # --- job queue -----------------------------------------------------------------------------------------------------------
    job_workers: int = 16
    job_queue_max: int = 100
    allow_simulated_delay: bool = False                       # demo/test only

    # -- derived paths ----------------------------------------------------------------------------------------------------------
    @property
    def providers_path(self) -> Path:
        return self.data_dir / self.providers_file

    @property
    def risk_tables_path(self) -> Path:
        return self.data_dir / self.risk_tables_file

    @property
    def transactions_path(self) -> Path:
        return self.data_dir / self.transactions_file

    @property
    def policies_path(self) -> Path:
        return self.data_dir / self.policies_file

    @property
    def enabled_modes(self) -> tuple[str, ...]:
        return tuple(m.strip() for m in self.allowed_modes.split(",") if m.strip())

    def snapshot(self) -> dict:
        """Every non-secret setting as plain JSON-able values (what is logged per run and returned by GET /config)."""
        out = {f.name: str(getattr(self, f.name)) if isinstance(getattr(self, f.name), Path) else getattr(self, f.name)
               for f in fields(self) if f.name not in SECRETS}
        out["openai_api_key_configured"] = bool(self.openai_api_key)
        out["app_api_key_configured"] = bool(self.app_api_key)
        return out


def _cast(value, default, name: str):
    """Convert a YAML value or an environment string to the type of the field's default."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        raise ValueError(f"{name}: '{value}' is not a boolean")
    if isinstance(default, Path) or default is None and name.endswith("_path"):
        return Path(str(value))
    if isinstance(default, int):
        return int(float(value)) if float(value).is_integer() else int(value)
    if isinstance(default, float):
        return float(value)
    return None if value is None else str(value)


def load_settings(env: dict | None = None, config_file: Path | str | None = None) -> Settings:
    """Build Settings from defaults < YAML < environment. `env` defaults to os.environ (tests pass their own dict)."""
    env = os.environ if env is None else env
    config_file = Path(config_file or env.get("CONFIG_FILE") or BASE_DIR / "config.yaml")
    defaults = {f.name: (f.default if f.default is not MISSING else None) for f in fields(Settings)}
    values: dict = {}

    if config_file.exists():
        loaded = yaml.safe_load(config_file.read_text(encoding="utf8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{config_file.name} must contain a mapping of setting names to values")
        for key, value in loaded.items():
            if key not in defaults:
                logger.warning("config_unknown_key file=%s key=%s (ignored)", config_file.name, key)
            elif key in SECRETS:
                logger.warning("config_secret_in_file key=%s (ignored: secrets come from the environment)", key)
            else:
                values[key] = _cast(value, defaults[key], key)

    for name in defaults:
        for var in (name.upper(), *[a for a, target in ALIASES.items() if target == name]):
            if var in env and env[var] != "":
                values[name] = _cast(env[var], defaults[name], name)
                break

    settings = Settings(**values)
    data_dir = Path(settings.data_dir)
    extra = {"data_dir": data_dir}
    for name, filename in (("audit_db_path", "audit.db"), ("jobs_db_path", "jobs.db")):
        extra[name] = getattr(settings, name) or data_dir / filename
    settings = Settings(**{**{f.name: getattr(settings, f.name) for f in fields(Settings)}, **extra})
    if settings.decision_mode not in MODES:
        raise ValueError(f"decision_mode must be one of {MODES}, got '{settings.decision_mode}'")
    unknown = [m for m in settings.enabled_modes if m not in MODES]
    if unknown or settings.decision_mode not in settings.enabled_modes:
        raise ValueError(f"allowed_modes {settings.enabled_modes} must be valid modes and include decision_mode '{settings.decision_mode}'")
    return settings


settings = load_settings()
