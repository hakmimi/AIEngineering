"""Day 30: the synthetic data - reproducible, valid, realistic enough, and read through the loaders."""
import json

import pandas as pd
import pytest

import data_loader
from errors import DataStoreError
from schemas import Transaction
from simulation import COUNTRIES, PROVIDERS, can_carry, generate_transactions, risk_tables, summary_stats


@pytest.fixture(scope="module")
def df():
    return generate_transactions(1000, seed=42)


# --- generator ----------------------------------------------------------------------------------------------
def test_shape_and_columns(df):
    assert len(df) == 1000 and df["transaction_id"].is_unique
    assert not df.isna().any().any()
    assert {"simulated_risk_score", "is_fraud", "historical_provider", "approved_outcome"} <= set(df.columns)


def test_same_seed_same_data_different_seed_different_data():
    a, b, c = generate_transactions(200, 7), generate_transactions(200, 7), generate_transactions(200, 8)
    pd.testing.assert_frame_equal(a, b)
    assert not a["amount"].equals(c["amount"])


def test_every_row_is_a_valid_transaction(df):
    hidden = ["simulated_risk_score", "is_fraud", "historical_provider", "approved_outcome"]
    for record in df.drop(columns=hidden).to_dict(orient="records"):
        Transaction(**record)                                     # raises on any invalid row


def test_value_ranges(df):
    assert df["amount"].between(1, 60000).all() and df["customer_age_days"].between(0, 3000).all()
    assert df["simulated_risk_score"].between(0, 1).all() and df["prior_chargebacks"].between(0, 5).all()
    assert set(df["country"]) <= set(COUNTRIES) and set(df["currency"]) <= {"USD", "EUR", "GBP", "ILS"}


def test_customer_type_is_consistent_with_account_age(df):
    assert df.loc[df["customer_type"] == "new", "customer_age_days"].max() <= 60
    assert df.loc[df["customer_type"] == "vip", "customer_age_days"].min() >= 365


def test_dates_span_thirty_days_and_are_not_in_the_future(df):
    ts = pd.to_datetime(df["timestamp"], utc=True)
    assert (ts.max() - ts.min()).days >= 25 and ts.max() <= pd.Timestamp("2026-02-01", tz="UTC")


def test_realistic_rates(df):
    stats = summary_stats(df)
    assert 0.15 <= stats["share_new"] <= 0.35
    assert 0.002 <= stats["fraud_rate"] <= 0.05                   # rare, like real fraud
    assert 0.75 <= stats["approval_rate"] <= 0.95
    assert stats["amount_median"] < stats["amount_p99"] / 10      # heavy right tail


def test_risk_behaves_as_documented(df):
    by_country = df.groupby("country")["simulated_risk_score"].mean()
    assert by_country["NG"] > by_country["US"] * 2                # riskiest vs safest market
    assert df.groupby("customer_type")["simulated_risk_score"].mean()["new"] > df.groupby("customer_type")["simulated_risk_score"].mean()["vip"]
    assert df.groupby("prior_chargebacks")["simulated_risk_score"].mean().is_monotonic_increasing
    fraud_risk, ok_risk = df.loc[df["is_fraud"], "simulated_risk_score"].mean(), df.loc[~df["is_fraud"], "simulated_risk_score"].mean()
    assert fraud_risk > ok_risk                                    # fraud concentrates in high-risk transactions


def test_historical_provider_could_really_carry_the_payment(df):
    by_id = {p.provider_id: p for p in PROVIDERS}
    for row in df.itertuples():
        provider = by_id[row.historical_provider]
        # the generator falls back to delta_global only when nobody else can carry it
        assert can_carry(provider, row.country, row.currency, row.payment_method, row.amount) or provider.provider_id == "delta_global"


# --- provider table ---------------------------------------------------------------------------------------------
def test_provider_table_is_sane():
    assert len(PROVIDERS) == 6 and len({p.provider_id for p in PROVIDERS}) == 6
    for p in PROVIDERS:
        assert 0 < p.base_approval_rate <= 1 and 0 < p.uptime <= 1 and p.max_amount > 0 and p.supported_methods
    assert [p.provider_id for p in PROVIDERS if p.supported_countries is None] == ["alpha_pay", "delta_global"]


def test_providers_are_meaningfully_different():
    fees = [p.fee_percent for p in PROVIDERS]
    assert max(fees) / min(fees) > 3 and len({p.max_risk for p in PROVIDERS}) >= 4


@pytest.mark.parametrize("provider,country,currency,method,amount,expected", [
    ("beta_bank", "DE", "EUR", "bank_transfer", 500, True),
    ("beta_bank", "DE", "EUR", "card", 500, False),                 # method
    ("beta_bank", "BR", "EUR", "bank_transfer", 500, False),        # country
    ("zeta_budget", "US", "ILS", "card", 100, False),               # currency
    ("zeta_budget", "US", "USD", "card", 3001, False),              # amount limit
    ("alpha_pay", "NG", "USD", "card", 100, True),                  # worldwide
])
def test_can_carry(provider, country, currency, method, amount, expected):
    p = next(x for x in PROVIDERS if x.provider_id == provider)
    assert can_carry(p, country, currency, method, amount) is expected


# --- loaders ------------------------------------------------------------------------------------------------------
def test_loaders_read_the_committed_files():
    providers = data_loader.load_providers()
    assert [p.provider_id for p in providers] == [p.provider_id for p in PROVIDERS]
    assert data_loader.load_risk_tables() == json.loads(json.dumps(risk_tables()))
    assert len(data_loader.load_transactions()) == 1000
    assert data_loader.get_provider("zeta_budget").fee_percent == 1.6


def test_agent_view_hides_the_truth_columns():
    txs = list(data_loader.iter_transactions(limit=25))
    assert len(txs) == 25 and all(isinstance(t, Transaction) for t in txs)
    assert not hasattr(txs[0], "simulated_risk_score") and not hasattr(txs[0], "approved_outcome")


def test_unknown_provider_and_missing_files_raise_data_store_errors(tmp_path, settings_override_paths):
    with pytest.raises(DataStoreError, match="unknown provider"):
        data_loader.get_provider("nope")
    settings_override_paths(tmp_path)
    with pytest.raises(DataStoreError, match="generate_data"):
        data_loader.load_transactions()


@pytest.fixture
def settings_override_paths(monkeypatch):
    def apply(tmp):
        monkeypatch.setattr(data_loader, "TRANSACTIONS_PATH", tmp / "missing.csv")
    return apply


def test_corrupt_json_is_reported(tmp_path, monkeypatch):
    bad = tmp_path / "p.json"
    bad.write_text("{oops", encoding="utf8")
    with pytest.raises(DataStoreError, match="not valid JSON"):
        data_loader._read_json(bad)
