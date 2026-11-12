"""Daily token budget.

Usage is counted in *weighted tokens*:

    input + cache_creation + output + cache_read * cache_read_weight

For Claude Code, usage is read straight from the session transcript
(``transcript_path`` in the hook payload): every assistant message carries the
API ``usage`` block. A message can appear several times in the transcript (one
line per content block) with identical usage, so each message id is counted
once. Subagent transcripts live in ``<session>/subagents/*.jsonl`` and are
counted too.

The transcript format is not a documented Claude Code API. It was verified
against Claude Code 2.1.x; if it changes, BurnGuard counts nothing rather than
crashing (fail-open), and ``burnguard status`` will show zero usage.

For your own code, call ``Budget().record(...)`` after each LLM call.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from burnguard import _store
from burnguard.config import Config

_MAX_IDS_PER_FILE = 2000  # dedupe memory per transcript file


class BudgetExceeded(RuntimeError):
    """Raised by Budget.check() when today's cap is used up."""


@dataclass
class BudgetStatus:
    day: str
    used: int
    limit: int | None

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used)

    @property
    def exceeded(self) -> bool:
        return self.limit is not None and self.used >= self.limit


def weighted_tokens(usage: dict[str, Any], cache_read_weight: float) -> int:
    def n(key: str) -> int:
        value = usage.get(key) or 0
        return int(value) if isinstance(value, (int, float)) else 0

    return round(
        n("input_tokens")
        + n("cache_creation_input_tokens")
        + n("output_tokens")
        + n("cache_read_input_tokens") * cache_read_weight
    )


def _today() -> str:
    return date.today().isoformat()


def _fresh_state() -> dict[str, Any]:
    return {"day": _today(), "used": 0, "files": {}}


class Budget:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.load()
        self.path = _store.home() / "budget.json"

    # -- public API ---------------------------------------------------------

    def status(self) -> BudgetStatus:
        state = _store.read_json(self.path, _fresh_state())
        used = state.get("used", 0) if state.get("day") == _today() else 0
        return BudgetStatus(_today(), int(used), self.config.daily_token_limit)

    def record(self, tokens: int) -> BudgetStatus:
        """Add tokens spent outside Claude Code (SDK usage)."""
        with _store.update_json(self.path, _fresh_state()) as state:
            self._roll_day(state)
            state["used"] += max(0, int(tokens))
        return self.status()

    def record_usage(self, usage: dict[str, Any]) -> BudgetStatus:
        """Add an Anthropic-style ``usage`` dict (input/output/cache fields)."""
        return self.record(weighted_tokens(usage, self.config.cache_read_weight))

    def check(self) -> None:
        """Raise BudgetExceeded if today's cap is used up."""
        st = self.status()
        if st.exceeded:
            raise BudgetExceeded(f"Daily token budget used up: {st.used:,} / {st.limit:,}")

    def reset_today(self) -> None:
        with _store.update_json(self.path, _fresh_state()) as state:
            self._roll_day(state)
            state["used"] = 0

    def sync_transcript(self, transcript_path: str) -> BudgetStatus:
        """Count new usage from a Claude Code transcript and its subagents."""
        files = [Path(transcript_path)]
        sub_dir = Path(transcript_path).with_suffix("") / "subagents"
        if sub_dir.is_dir():
            files.extend(sorted(sub_dir.glob("*.jsonl")))
        with _store.update_json(self.path, _fresh_state()) as state:
            self._roll_day(state)
            for f in files:
                state["used"] += self._consume(state, f)
        return self.status()

    # -- internals -----------------------------------------------------------

    def _roll_day(self, state: dict[str, Any]) -> None:
        if state.get("day") != _today():
            # Keep file offsets so yesterday's lines are never re-counted.
            state["day"] = _today()
            state["used"] = 0
            # Forget transcripts nobody has touched for a week.
            cutoff = date.fromordinal(date.today().toordinal() - 7).isoformat()
            state["files"] = {k: v for k, v in state.get("files", {}).items() if v.get("seen", "") >= cutoff}
        state.setdefault("used", 0)
        state.setdefault("files", {})

    def _consume(self, state: dict[str, Any], path: Path) -> int:
        key = os.path.normcase(str(path.resolve()))
        entry = state["files"].setdefault(key, {"offset": 0, "ids": []})
        entry["seen"] = _today()
        try:
            size = path.stat().st_size
        except OSError:
            return 0
        if size < entry["offset"]:  # file was truncated/replaced
            entry["offset"], entry["ids"] = 0, []
        with open(path, "rb") as f:
            f.seek(entry["offset"])
            chunk = f.read()
        # Claude Code writes the transcript asynchronously: only consume
        # complete lines so a half-written record is read next time.
        end = chunk.rfind(b"\n")
        if end == -1:
            return 0
        entry["offset"] += end + 1
        seen = set(entry["ids"])
        added = 0
        for raw in chunk[: end + 1].splitlines():
            try:
                rec = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            if rec.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            usage, msg_id = msg.get("usage"), msg.get("id")
            if not isinstance(usage, dict) or not msg_id or msg_id in seen:
                continue
            seen.add(msg_id)
            entry["ids"].append(msg_id)
            added += weighted_tokens(usage, self.config.cache_read_weight)
        entry["ids"] = entry["ids"][-_MAX_IDS_PER_FILE:]
        return added
