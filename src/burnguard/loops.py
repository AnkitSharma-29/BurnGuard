"""Loop detection.

An agent is considered stuck when it is about to make a call it has already
made ``max_repeats`` times within the last ``window`` calls, and every one of
those earlier attempts produced the *same result*. Re-running tests after an
edit is fine (the output changes); running the same failing command over and
over without changing anything is a loop.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import deque
from typing import Any

from burnguard import _store

# Keys that vary between otherwise identical tool calls.
_VOLATILE_KEYS = {"description"}
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")
# A reserved call that never reports back (denied by another hook, crashed)
# stops counting after this long.
_PENDING_TTL_S = 300.0


def _stable(value: Any) -> Any:
    """Drop volatile keys at any depth so cosmetic differences don't hide a loop."""
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


def fingerprint(value: Any) -> str:
    value = _stable(value)
    blob = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def repeats(history: list[tuple[str, str]], call: str) -> int:
    """How many times `call` already ran with one identical result (0 if results differ)."""
    results = {res for c, res in history if c == call}
    if len(results) != 1:
        return 0
    return sum(1 for c, _ in history if c == call)


class LoopDetector:
    """In-memory detector for your own agent loops.

    >>> d = LoopDetector(max_repeats=3)
    >>> d.is_loop("search", "nothing found")  # record and check
    """

    def __init__(self, max_repeats: int = 3, window: int = 20) -> None:
        self.max_repeats = max_repeats
        self._history: deque[tuple[str, str]] = deque(maxlen=window)

    def would_loop(self, call: Any) -> bool:
        return repeats(list(self._history), fingerprint(call)) >= self.max_repeats

    def record(self, call: Any, result: Any) -> None:
        self._history.append((fingerprint(call), fingerprint(result)))

    def is_loop(self, call: Any, result: Any) -> bool:
        """Record a finished call; True if the *next* identical call should be blocked."""
        self.record(call, result)
        return self.would_loop(call)

    def reset(self) -> None:
        self._history.clear()


class SessionLoops:
    """Persistent per-session history for Claude Code hooks (one process per call)."""

    def __init__(self, session_id: str, window: int = 20) -> None:
        self.window = window
        self.path = _store.home() / "sessions" / f"{_SAFE_ID.sub('_', session_id)}.json"

    @staticmethod
    def _default() -> dict[str, Any]:
        return {"history": [], "pending": {}, "blocks": 0, "updated": 0.0}

    def check(self, tool_name: str, tool_input: Any) -> int:
        """Times this exact call already returned an identical result."""
        state = _store.read_json(self.path, self._default())
        history = [tuple(h) for h in state.get("history", [])]
        return repeats(history, fingerprint([tool_name, tool_input]))

    def reserve(self, tool_name: str, tool_input: Any, tool_use_id: str | None, limit: int) -> int:
        """Count earlier identical calls, including ones still running, and reserve a slot.

        Claude Code can send several identical calls in one batch. Their
        PreToolUse hooks all run before any of them finishes, so counting only
        finished calls would let the whole batch through. Calls that passed
        PreToolUse but have not finished yet are therefore counted too. Check
        and reservation happen under one lock. Returns the count; a slot is
        reserved only when the count is below `limit`.
        """
        call = fingerprint([tool_name, tool_input])
        now = time.time()
        with _store.update_json(self.path, self._default()) as state:
            pending = {
                k: v
                for k, v in state.get("pending", {}).items()
                if now - float(v[1]) < _PENDING_TTL_S  # calls that never reported back
            }
            history = [tuple(h) for h in state["history"]]
            done = sum(1 for c, _ in history if c == call)
            running = sum(1 for c, _ in pending.values() if c == call)
            # Finished identical calls only count when they all returned the same result.
            n = (repeats(history, call) if done else 0) + running
            if n < limit and tool_use_id:
                pending[tool_use_id] = [call, now]
            state["pending"] = pending
            state["updated"] = now
            return n

    def record(
        self, tool_name: str, tool_input: Any, tool_response: Any, tool_use_id: str | None = None
    ) -> None:
        with _store.update_json(self.path, self._default()) as state:
            state.setdefault("pending", {}).pop(tool_use_id or "", None)
            state["history"].append([fingerprint([tool_name, tool_input]), fingerprint(tool_response)])
            state["history"] = state["history"][-self.window :]
            state["updated"] = time.time()

    def release(self, tool_use_id: str | None) -> None:
        """Forget a reservation without recording a result (e.g. the call was interrupted)."""
        if not tool_use_id:
            return
        with _store.update_json(self.path, self._default()) as state:
            state.setdefault("pending", {}).pop(tool_use_id, None)

    def add_block(self) -> int:
        with _store.update_json(self.path, self._default()) as state:
            state["blocks"] = int(state.get("blocks", 0)) + 1
            state["updated"] = time.time()
            return state["blocks"]

    def blocks(self) -> int:
        return int(_store.read_json(self.path, self._default()).get("blocks", 0))


def prune_sessions(max_age_s: float = 3 * 86400, now: float | None = None) -> int:
    """Delete session files older than max_age_s. Returns how many were removed."""
    now = time.time() if now is None else now
    removed = 0
    folder = _store.home() / "sessions"
    if not folder.is_dir():
        return 0
    for f in folder.glob("*.json"):
        try:
            if now - f.stat().st_mtime > max_age_s:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed
