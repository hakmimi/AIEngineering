"""How the agent (and the tests) read reference data and transactions.

The orchestration layer never opens files itself: it calls these loaders, so the storage format can change
(CSV/JSON today, a database later) without touching the agent. Loaders validate what they read.
"""
import json
from collections.abc import Iterator
from functools import lru_cache

import pandas as pd

from config import settings
from errors import DataStoreError
from schemas import Transaction
from simulation import Provider

PROVIDERS_PATH = settings.data_dir / "providers.json"
RISK_TABLES_PATH = settings.data_dir / "risk_tables.json"
TRANSACTIONS_PATH = settings.data_dir / "transactions.csv"
HIDDEN_COLUMNS = ["simulated_risk_score", "is_fraud", "historical_provider", "approved_outcome"]


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except FileNotFoundError as exc:
        raise DataStoreError(f"{path.name} not found - run `python -m scripts.generate_data`") from exc
    except json.JSONDecodeError as exc:
        raise DataStoreError(f"{path.name} is not valid JSON") from exc


@lru_cache(maxsize=1)
def load_providers() -> tuple[Provider, ...]:
    return tuple(Provider(**p) for p in _read_json(PROVIDERS_PATH))


@lru_cache(maxsize=1)
def load_risk_tables() -> dict:
    return _read_json(RISK_TABLES_PATH)


def load_transactions() -> pd.DataFrame:
    """The full labelled dataset (includes the hidden truth columns - for evaluation/analysis only)."""
    try:
        return pd.read_csv(TRANSACTIONS_PATH)
    except FileNotFoundError as exc:
        raise DataStoreError("transactions.csv not found - run `python -m scripts.generate_data`") from exc


def iter_transactions(limit: int | None = None) -> Iterator[Transaction]:
    """Validated Transaction objects WITHOUT the hidden columns - exactly what the agent is allowed to see."""
    df = load_transactions()
    for row in df.head(limit).drop(columns=HIDDEN_COLUMNS).to_dict(orient="records"):
        yield Transaction(**row)


def get_provider(provider_id: str) -> Provider:
    for provider in load_providers():
        if provider.provider_id == provider_id:
            return provider
    raise DataStoreError(f"unknown provider '{provider_id}'")
