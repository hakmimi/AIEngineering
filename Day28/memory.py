"""Session memory, two kinds:

* short-term  - the last N turns of the conversation (bounded; used to resolve follow-ups)
* long-term   - a few durable facts about the user ("name", "interest") pulled out by simple rules

Stores share one interface (BaseMemory). Day 12's JSON-file store is kept; Day 19 adds SQLite, which is
safe for concurrent readers/writers, survives restarts, and is what the app uses by default.
We deliberately do NOT store retrieved chunks or timings (recomputable, would bloat prompts).
"""
import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import closing
from pathlib import Path

from config import settings
from errors import AppError

logger = logging.getLogger(__name__)

_SESSION_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_FACT_PATTERNS = [
    # (?i:...) makes only the trigger phrase case-insensitive, so a name must still start with a capital
    ("name", re.compile(r"\b(?i:my name is) ([A-Z][a-zA-Z'-]{1,30})")),
    ("name", re.compile(r"\b(?i:call me) ([A-Z][a-zA-Z'-]{1,30})")),
    ("interest", re.compile(r"\b(?i:i'm|i am) (?i:really |very )?(?i:interested in) ([A-Za-z][A-Za-z ,'-]{2,40}?)(?:[.!?]|$)")),
    ("interest", re.compile(r"\b(?i:i) (?i:love|like|enjoy) ([A-Za-z][A-Za-z ,'-]{2,40}?)(?:[.!?]|$)")),
]


class InvalidSessionError(AppError):
    def __init__(self):
        super().__init__("session_id must be 1-64 characters: letters, digits, '_' or '-'", status_code=422)


def validate_session_id(session_id: str) -> str:
    if not _SESSION_ID.match(session_id or ""):
        raise InvalidSessionError()
    return session_id


def extract_facts(text: str) -> dict[str, str]:
    """Pull durable user facts out of a message. Rules, not an LLM: free, predictable, easy to audit."""
    facts: dict[str, str] = {}
    for key, pattern in _FACT_PATTERNS:
        match = pattern.search(text or "")
        if match and key not in facts:
            facts[key] = match.group(1).strip()
    return facts


class BaseMemory:
    """Prompt formatting shared by every store. Subclasses implement get_history/add_turn/clear (+ facts)."""

    def get_history(self, session_id: str) -> list[dict]:
        raise NotImplementedError

    def get_facts(self, session_id: str) -> dict[str, str]:
        return {}

    def remember(self, session_id: str, key: str, value: str) -> None:
        return None

    def format_for_prompt(self, session_id: str, max_chars: int | None = None) -> str:
        """Most recent messages that fit max_chars, oldest first: 'User: ...\\nAssistant: ...'."""
        budget, lines = max_chars or settings.memory_prompt_chars, []
        for m in reversed(self.get_history(session_id)):
            line = f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            if len(line) > budget:
                break
            budget -= len(line) + 1
            lines.append(line)
        return "\n".join(reversed(lines))

    def format_facts(self, session_id: str) -> str:
        return "; ".join(f"{k}: {v}" for k, v in sorted(self.get_facts(session_id).items()))


# --- Day 12: JSON-file store (kept for comparison / simple deployments) ------------------------------
class MemoryStore(BaseMemory):
    def __init__(self, path: Path | None = None, max_turns: int | None = None, max_sessions: int | None = None):
        self.path = path
        self.max_turns = max_turns or settings.memory_max_turns
        self.max_sessions = max_sessions or settings.memory_max_sessions
        self._sessions: OrderedDict[str, list[dict]] = OrderedDict()  # LRU order: oldest first
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            self._sessions = OrderedDict(json.loads(self.path.read_text(encoding="utf8")))
        except (OSError, json.JSONDecodeError):
            logger.warning("memory_file_unreadable path=%s - starting empty", self.path)

    def _save(self) -> None:
        if not self.path:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._sessions, ensure_ascii=False), encoding="utf8")
        os.replace(tmp, self.path)

    def get_history(self, session_id: str) -> list[dict]:
        with self._lock:
            return list(self._sessions.get(session_id, []))

    def add_turn(self, session_id: str, question: str, answer: str) -> int:
        now = time.time()
        with self._lock:
            messages = self._sessions.pop(session_id, [])
            messages += [{"role": "user", "content": question, "ts": now},
                         {"role": "assistant", "content": answer, "ts": now}]
            self._sessions[session_id] = messages[-2 * self.max_turns:]
            while len(self._sessions) > self.max_sessions:
                evicted, _ = self._sessions.popitem(last=False)
                logger.info("memory_session_evicted session=%s", evicted)
            self._save()
            turns = len(self._sessions[session_id]) // 2
        logger.info("memory_write store=json session=%s turns=%s", session_id, turns)
        return turns

    def clear(self, session_id: str) -> bool:
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
            self._save()
        return existed


# --- Day 19: SQLite store (short-term history + long-term facts) --------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
    content TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS facts (
    session_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, ts REAL NOT NULL,
    PRIMARY KEY (session_id, key));
CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, last_seen REAL NOT NULL);
"""


class SqliteMemoryStore(BaseMemory):
    def __init__(self, path: Path, max_turns: int | None = None, max_sessions: int | None = None):
        self.path = Path(path)
        self.max_turns = max_turns or settings.memory_max_turns
        self.max_sessions = max_sessions or settings.memory_max_sessions
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)   # one short-lived connection per operation: thread-safe
        db.row_factory = sqlite3.Row
        return db

    def get_history(self, session_id: str) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT role, content, ts FROM messages WHERE session_id=? ORDER BY id", (session_id,))
            return [dict(r) for r in rows]

    def add_turn(self, session_id: str, question: str, answer: str) -> int:
        now = time.time()
        with closing(self._connect()) as db, db:      # `with db` = one transaction
            db.executemany("INSERT INTO messages(session_id, role, content, ts) VALUES (?,?,?,?)",
                           [(session_id, "user", question, now), (session_id, "assistant", answer, now)])
            db.execute("INSERT INTO sessions(session_id, last_seen) VALUES (?,?) "
                       "ON CONFLICT(session_id) DO UPDATE SET last_seen=excluded.last_seen", (session_id, now))
            db.execute("DELETE FROM messages WHERE session_id=? AND id NOT IN "
                       "(SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?)",
                       (session_id, session_id, 2 * self.max_turns))
            for (old,) in db.execute("SELECT session_id FROM sessions ORDER BY last_seen DESC LIMIT -1 OFFSET ?",
                                     (self.max_sessions,)).fetchall():
                for table in ("messages", "facts", "sessions"):
                    db.execute(f"DELETE FROM {table} WHERE session_id=?", (old,))
                logger.info("memory_session_evicted session=%s", old)
            turns = db.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)).fetchone()[0] // 2
        logger.info("memory_write store=sqlite session=%s turns=%s", session_id, turns)
        return turns

    def clear(self, session_id: str) -> bool:
        with closing(self._connect()) as db, db:
            existed = db.execute("SELECT 1 FROM sessions WHERE session_id=?", (session_id,)).fetchone() is not None
            for table in ("messages", "facts", "sessions"):
                db.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
        return existed

    def remember(self, session_id: str, key: str, value: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO facts(session_id, key, value, ts) VALUES (?,?,?,?) "
                       "ON CONFLICT(session_id, key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                       (session_id, key, value, time.time()))
            db.execute("INSERT INTO sessions(session_id, last_seen) VALUES (?,?) "
                       "ON CONFLICT(session_id) DO UPDATE SET last_seen=excluded.last_seen", (session_id, time.time()))
        logger.info("memory_fact_saved session=%s key=%s", session_id, key)

    def get_facts(self, session_id: str) -> dict[str, str]:
        with closing(self._connect()) as db:
            return {r["key"]: r["value"] for r in
                    db.execute("SELECT key, value FROM facts WHERE session_id=?", (session_id,))}


memory = SqliteMemoryStore(settings.memory_db_path)
