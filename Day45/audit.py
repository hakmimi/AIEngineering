"""Audit trail: one durable, structured, tamper-evident record per decision.

Runtime logs answer "what is the system doing right now?" (verbose, technical, rotated away).
The audit record answers "why was THIS payment routed/reviewed/declined?" months later, for a support agent or a regulator:
what came in, which path the agent took, which tools it consulted, what the rules and the LLM said, and what was finally decided.

Design choices
* Insert-only SQLite table keyed by decision_id (there is no update or delete API).
* Each row stores a SHA-256 of its JSON, so an edited row is detectable (`verify()`).
* Inputs are summarised (business fields only - no free text from users exists in this domain).
* If writing the audit record fails the decision is still returned, flagged `audit_recorded=false`, and an ERROR is logged -
  availability over completeness. A regulated deployment might choose the opposite (withhold the decision); it is one line to flip.
"""
import hashlib
import json
import logging
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from config import settings
from errors import AppError
from observability import log_event, request_id_var

logger = logging.getLogger("audit")


class AuditNotFound(AppError):
    def __init__(self, decision_id: str):
        super().__init__(f"no audit record for decision '{decision_id}'", status_code=404)


class AuditRecord(BaseModel):
    decision_id: str
    created_at: str
    request_id: str
    agent_version: str
    transaction_id: str
    input_summary: dict
    route: str
    route_reason: str | None = None
    graph_trace: list[str]
    tools_used: list[dict] = Field(description="tool name, ok, ms and a compact argument summary - one entry per call")
    risk_score: float
    risk_components: dict
    baseline_action: str
    baseline_provider: str | None
    final_action: str
    final_provider: str | None
    reason_codes: list[str]
    changed_by_ai: bool
    fast_path: str | None
    llm: dict = Field(description="status, agrees, escalate, confidence, concerns - or status only when the LLM was not used")
    business_explanation: str | None = Field(description="the sentence(s) a business user / auditor reads")
    technical_notes: list[str]
    usage: dict
    latency_ms: float


def new_decision_id() -> str:
    return "dec_" + uuid.uuid4().hex[:16]


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf8")).hexdigest()


class AuditStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS audit (decision_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, created_at TEXT NOT NULL,"
                       " record TEXT NOT NULL, sha256 TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_audit_tx ON audit(transaction_id, created_at)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")        # readers never block the writer; one fsync per checkpoint, not per commit
        db.execute("PRAGMA synchronous=NORMAL")      # durable across application crashes (only a power loss can lose the last commit)
        return db

    def save(self, record: AuditRecord) -> None:
        payload = record.model_dump_json()
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO audit(decision_id, transaction_id, created_at, record, sha256) VALUES (?,?,?,?,?)",
                       (record.decision_id, record.transaction_id, record.created_at, payload, _digest(payload)))

    def get(self, decision_id: str) -> AuditRecord:
        with closing(self._connect()) as db:
            row = db.execute("SELECT record FROM audit WHERE decision_id=?", (decision_id,)).fetchone()
        if row is None:
            raise AuditNotFound(decision_id)
        return AuditRecord.model_validate_json(row["record"])

    def for_transaction(self, transaction_id: str) -> list[str]:
        """Decision ids for one transaction, oldest first (a transaction may be decided more than once)."""
        with closing(self._connect()) as db:
            return [r["decision_id"] for r in db.execute(
                "SELECT decision_id FROM audit WHERE transaction_id=? ORDER BY created_at, rowid", (transaction_id,))]

    def verify(self, decision_id: str) -> bool:
        """True if the stored row still matches the hash taken when it was written."""
        with closing(self._connect()) as db:
            row = db.execute("SELECT record, sha256 FROM audit WHERE decision_id=?", (decision_id,)).fetchone()
        if row is None:
            raise AuditNotFound(decision_id)
        return _digest(row["record"]) == row["sha256"]

    def count(self) -> int:
        with closing(self._connect()) as db:
            return db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]


audit_store = AuditStore(settings.audit_db_path)


def _tool_summary(call: dict) -> dict:
    args = json.dumps(call["arguments"], default=str)
    return {"tool": call["tool"], "ok": call["ok"], "ms": call["ms"], "arguments": args if len(args) <= 160 else args[:160] + "..."}


def build_record(decision_id: str, result, tx, agent_version: str) -> AuditRecord:
    """Assemble the record from an AIResult (decision_graph.run_decision_graph)."""
    d, b = result.decision, result.baseline
    review = result.review
    llm = {"status": result.llm_status}
    if review is not None:
        llm |= {"agrees_with_baseline": review.agrees_with_baseline, "escalate_to_review": review.escalate_to_review,
                "confidence": review.confidence, "concerns": review.concerns}
    return AuditRecord(
        decision_id=decision_id, created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"), request_id=request_id_var.get(),
        agent_version=agent_version, transaction_id=tx.transaction_id,
        input_summary=tx.model_dump(mode="json", exclude={"transaction_id", "timestamp"}) | {"transaction_time": tx.timestamp.isoformat()},
        route=result.graph_route, route_reason=result.graph_route_reason, graph_trace=result.graph_trace,
        tools_used=[_tool_summary(c) for c in result.tool_trace], risk_score=d.risk_score, risk_components=result.risk_components,
        baseline_action=b.action.value, baseline_provider=b.selected_provider, final_action=d.action.value, final_provider=d.selected_provider,
        reason_codes=[r.value for r in d.reason_codes], changed_by_ai=d.action != b.action, fast_path=result.fast_path, llm=llm,
        business_explanation=d.explanation, technical_notes=result.notes, usage=result.usage, latency_ms=round(result.latency_ms, 1))


def record_decision(decision_id: str, result, tx, agent_version: str, store: AuditStore | None = None) -> bool:
    """Write the audit record. Returns False (and logs an ERROR) instead of raising - see the module docstring."""
    try:
        record = build_record(decision_id, result, tx, agent_version)
        (store or audit_store).save(record)
        log_event(logger, "audit_recorded", decision_id=decision_id, transaction_id=tx.transaction_id, action=record.final_action)
        return True
    except Exception as exc:  # noqa: BLE001
        log_event(logger, "audit_failed", level=logging.ERROR, decision_id=decision_id, transaction_id=tx.transaction_id,
                  error=type(exc).__name__, message=str(exc))
        return False
