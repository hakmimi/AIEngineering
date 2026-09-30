"""Session memory: short-term conversation history per session_id, persisted to a JSON file.

What we store: role + text + timestamp for the last N turns only (bounded, so prompts stay small and
memory can't grow forever). We do NOT store retrieved chunks or timings - they can be recomputed.
"""
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

from config import settings
from errors import AppError

logger = logging.getLogger(__name__)

_SESSION_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class InvalidSessionError(AppError):
    def __init__(self):
        super().__init__("session_id must be 1-64 characters: letters, digits, '_' or '-'", status_code=422)


def validate_session_id(session_id: str) -> str:
    if not _SESSION_ID.match(session_id or ""):
        raise InvalidSessionError()
    return session_id


class MemoryStore:
    def __init__(self, path: Path | None = None, max_turns: int | None = None, max_sessions: int | None = None):
        self.path = path
        self.max_turns = max_turns or settings.memory_max_turns
        self.max_sessions = max_sessions or settings.memory_max_sessions
        self._sessions: OrderedDict[str, list[dict]] = OrderedDict()  # LRU order: oldest first
        self._lock = threading.Lock()
        self._load()

    # -- persistence ---------------------------------------------------------------------
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
        os.replace(tmp, self.path)  # atomic: a crash can't leave a half-written file

    # -- API -------------------------------------------------------------------------------
    def get_history(self, session_id: str) -> list[dict]:
        """Last max_turns *turns* (a turn = user + assistant message) as [{role, content, ts}]."""
        with self._lock:
            return list(self._sessions.get(session_id, []))

    def add_turn(self, session_id: str, question: str, answer: str) -> int:
        now = time.time()
        with self._lock:
            messages = self._sessions.pop(session_id, [])          # pop + reinsert = mark as most recent
            messages += [{"role": "user", "content": question, "ts": now},
                         {"role": "assistant", "content": answer, "ts": now}]
            self._sessions[session_id] = messages[-2 * self.max_turns:]
            while len(self._sessions) > self.max_sessions:
                evicted, _ = self._sessions.popitem(last=False)
                logger.info("memory_session_evicted session=%s", evicted)
            self._save()
            turns = len(self._sessions[session_id]) // 2
        logger.info("memory_write session=%s turns=%s", session_id, turns)
        return turns

    def clear(self, session_id: str) -> bool:
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
            self._save()
        return existed

    def format_for_prompt(self, session_id: str, max_chars: int | None = None) -> str:
        """Most recent messages that fit in max_chars, oldest first: 'User: ...\\nAssistant: ...'."""
        budget, lines = max_chars or settings.memory_prompt_chars, []
        for m in reversed(self.get_history(session_id)):
            line = f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            if len(line) > budget:
                break
            budget -= len(line) + 1
            lines.append(line)
        return "\n".join(reversed(lines))


memory = MemoryStore(settings.sessions_path)
