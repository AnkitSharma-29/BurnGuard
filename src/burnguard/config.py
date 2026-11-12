"""User configuration stored in ~/.burnguard/config.json."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from burnguard import _store


@dataclass
class Config:
    # Daily budget in weighted tokens (see budget.py). None = no cap.
    daily_token_limit: int | None = None
    # Cache reads cost ~10% of normal input on Anthropic pricing, and a long
    # session re-reads its whole context every turn. Counting them at full
    # weight would exhaust any sane budget in minutes.
    cache_read_weight: float = 0.1
    # Block a tool call once the same call has already produced the same
    # result this many times in a row-window.
    loop_max_repeats: int = 3
    # How many recent tool calls per session are remembered.
    loop_window: int = 20
    # After this many loop blocks in one session, stop the agent entirely.
    loop_hard_stop_after: int = 3
    # "block" | "warn" | "off": secrets in prompts you send.
    secrets_in_prompt: str = "block"
    # Redact secrets in Bash output before the model sees it.
    redact_tool_output: bool = True
    # Refuse Read on files that usually hold secrets (.env, *.pem, ...).
    block_secret_files: bool = True
    # Warn the model when fetched/read content contains injection-like text.
    flag_injection: bool = True

    @classmethod
    def load(cls) -> Config:
        raw = _store.read_json(_store.home() / "config.json", {})
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        _store.write_json(_store.home() / "config.json", asdict(self))

    @classmethod
    def set(cls, key: str, value: Any) -> Config:
        cfg = cls.load()
        if key not in {f.name for f in fields(cls)}:
            raise KeyError(key)
        setattr(cfg, key, value)
        cfg.save()
        return cfg
