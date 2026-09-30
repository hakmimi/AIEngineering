"""Day 29: the input contract, the decision contract and the API skeleton."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import app
from schemas import Action, Decision, ReasonCode, Transaction

ROOT = Path(__file__).resolve().parent.parent
VALID = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 85.5, "currency": "ILS", "country": "IL",
         "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card",
         "customer_age_days": 400, "prior_chargebacks": 0}
client = TestClient(app)


def tx(**changes):
    return Transaction(**{**VALID, **changes})


# --- transaction contract ------------------------------------------------------------------------------------
def test_valid_transaction_parses_and_normalises():
    t = tx(amount=10.456, transaction_id="  abc-1  ")
    assert t.amount == 10.46 and t.transaction_id == "abc-1" and t.timestamp.tzinfo is not None


def test_defaults():
    data = {k: v for k, v in VALID.items() if k != "prior_chargebacks"}
    assert Transaction(**data).prior_chargebacks == 0


@pytest.mark.parametrize("field,value", [
    ("amount", 0), ("amount", -5), ("amount", 1_000_001), ("amount", "lots"),
    ("currency", "JPY"), ("country", "israel"), ("country", "il"), ("country", "I"), ("country", "1L"),
    ("merchant_category", "weapons"), ("customer_type", "guest"), ("payment_method", "crypto"),
    ("customer_age_days", -1), ("prior_chargebacks", -1), ("prior_chargebacks", 101),
    ("transaction_id", ""), ("transaction_id", "has space"), ("transaction_id", "x" * 65), ("transaction_id", "a/b"),
    ("timestamp", "2026-01-05T09:12:00"),                                        # no timezone
    ("timestamp", "not a date"),
])
def test_invalid_fields_are_rejected(field, value):
    with pytest.raises(ValidationError):
        tx(**{field: value})


def test_future_timestamp_is_rejected_but_small_clock_skew_is_tolerated():
    with pytest.raises(ValidationError):
        tx(timestamp=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    tx(timestamp=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())


def test_new_customer_cannot_have_an_old_account():
    with pytest.raises(ValidationError, match="new"):
        tx(customer_type="new", customer_age_days=200)
    tx(customer_type="new", customer_age_days=90)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        Transaction(**VALID, is_admin=True)


def test_missing_required_fields_are_rejected():
    for field in VALID:
        if field == "prior_chargebacks":
            continue
        with pytest.raises(ValidationError):
            Transaction(**{k: v for k, v in VALID.items() if k != field})


# --- decision contract --------------------------------------------------------------------------------------------
def test_route_requires_a_provider_and_others_forbid_one():
    Decision(transaction_id="t", action=Action.ROUTE, selected_provider="p1", reason_codes=[ReasonCode.LOW_RISK], risk_score=0.1)
    with pytest.raises(ValidationError):
        Decision(transaction_id="t", action=Action.ROUTE, reason_codes=[ReasonCode.LOW_RISK], risk_score=0.1)
    with pytest.raises(ValidationError):
        Decision(transaction_id="t", action=Action.DECLINE, selected_provider="p1", reason_codes=[ReasonCode.HIGH_RISK], risk_score=0.9)


def test_reason_codes_are_mandatory_and_from_the_closed_set():
    with pytest.raises(ValidationError):
        Decision(transaction_id="t", action=Action.DECLINE, reason_codes=[], risk_score=0.9)
    with pytest.raises(ValidationError):
        Decision(transaction_id="t", action=Action.DECLINE, reason_codes=["SOMETHING_ELSE"], risk_score=0.9)


@pytest.mark.parametrize("risk", [-0.1, 1.1])
def test_risk_score_is_bounded(risk):
    with pytest.raises(ValidationError):
        Decision(transaction_id="t", action=Action.DECLINE, reason_codes=[ReasonCode.HIGH_RISK], risk_score=risk)


# --- sample events ---------------------------------------------------------------------------------------------------
def test_all_five_sample_events_are_valid_and_diverse():
    events = json.loads((ROOT / "data" / "sample_events.json").read_text(encoding="utf8"))
    parsed = [Transaction(**e) for e in events]
    assert len(parsed) == 5 and len({t.transaction_id for t in parsed}) == 5
    assert len({t.customer_type for t in parsed}) == 3 and len({t.currency for t in parsed}) >= 3


# --- API skeleton ------------------------------------------------------------------------------------------------------
def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_validate_endpoint_accepts_and_echoes_normalised_event():
    r = client.post("/events/validate", json={**VALID, "amount": 10.456})
    assert r.status_code == 200 and r.json()["valid"] and r.json()["transaction"]["amount"] == 10.46
    assert r.headers["X-Request-ID"]


def test_validate_endpoint_rejects_bad_events_with_422():
    assert client.post("/events/validate", json={**VALID, "amount": -1}).status_code == 422
    assert client.post("/events/validate", json={}).status_code == 422
    assert client.post("/events/validate", json={**VALID, "extra": 1}).status_code == 422
