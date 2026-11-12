"""Local state: one directory, JSON files, cross-process locking, atomic writes.

Claude Code runs matching hooks in parallel, so two BurnGuard processes can
touch the same file at once. Every read-modify-write goes through `locked()`.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_LOCK_TIMEOUT_S = 5.0
_STALE_LOCK_S = 30.0


def home() -> Path:
    """State directory. Override with BURNGUARD_HOME (used by tests)."""
    override = os.environ.get("BURNGUARD_HOME")
    path = Path(override) if override else Path.home() / ".burnguard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_text(path: Path) -> str:
    # On Windows a file is briefly unopenable while os.replace swaps it in.
    for attempt in range(50):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.01)
    raise AssertionError("unreachable")


def read_json(path: Path, default: Any) -> Any:
    try:
        data = json.loads(_read_text(path))
        if isinstance(default, dict) and not isinstance(data, dict):
            return copy.deepcopy(default)
        return data
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # A corrupt state file must never take the agent down; start fresh.
        return copy.deepcopy(default)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        # os.replace is atomic, but on Windows it fails while another process
        # has the target open for reading. Retry briefly.
        for attempt in range(50):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.01)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Exclusive lock around `path` using an O_EXCL lock file (portable)."""
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except (FileExistsError, PermissionError):
            # Windows raises PermissionError while the lock file is being deleted.
            try:
                if time.time() - lock.stat().st_mtime > _STALE_LOCK_S:
                    os.remove(lock)  # holder crashed
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"could not lock {path}") from None
            time.sleep(0.005)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(lock)


@contextlib.contextmanager
def update_json(path: Path, default: Any) -> Iterator[Any]:
    """Lock, load, let the caller mutate, then save atomically."""
    with locked(path):
        data = read_json(path, default)
        yield data
        write_json(path, data)
