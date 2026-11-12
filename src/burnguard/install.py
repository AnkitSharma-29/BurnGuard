"""Add/remove BurnGuard hooks in a Claude Code settings.json."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse")
MARKER = "-m burnguard hook"


def hook_command() -> str:
    # Absolute interpreter path: works no matter what is on the hook's PATH.
    # Forward slashes and quotes keep it valid in bash, sh and cmd on Windows.
    return f'"{Path(sys.executable).as_posix()}" {MARKER}'


def settings_path(scope: str, project_dir: Path | None = None) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    base = project_dir or Path.cwd()
    name = "settings.local.json" if scope == "local" else "settings.json"
    return base / ".claude" / name


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)  # invalid JSON: refuse to touch it
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _is_ours(handler: Any) -> bool:
    return isinstance(handler, dict) and MARKER in str(handler.get("command", ""))


def _strip(settings: dict[str, Any]) -> int:
    """Remove BurnGuard handlers. Returns how many were removed."""
    removed = 0
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    for event in list(hooks):
        groups = hooks[event] if isinstance(hooks[event], list) else []
        new_groups = []
        for group in groups:
            handlers = group.get("hooks", []) if isinstance(group, dict) else []
            keep = [h for h in handlers if not _is_ours(h)]
            removed += len(handlers) - len(keep)
            if keep:
                new_groups.append({**group, "hooks": keep})
            elif not handlers:
                new_groups.append(group)
        if new_groups:
            hooks[event] = new_groups
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return removed


def _write(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".burnguard.bak"))
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def install(path: Path) -> None:
    settings = _load(path)
    _strip(settings)  # idempotent: replace any older BurnGuard entries
    hooks = settings.setdefault("hooks", {})
    handler = {"type": "command", "command": hook_command(), "timeout": 15}
    for event in EVENTS:
        group: dict[str, Any] = {"hooks": [handler]}
        if event != "UserPromptSubmit":  # this event has no matcher
            group = {"matcher": "*", **group}
        hooks.setdefault(event, []).append(group)
    _write(path, settings)


def uninstall(path: Path) -> int:
    if not path.exists():
        return 0
    settings = _load(path)
    removed = _strip(settings)
    if removed:
        _write(path, settings)
    return removed


def installed(path: Path) -> bool:
    try:
        settings = _load(path)
    except (ValueError, json.JSONDecodeError):
        return False
    return any(
        _is_ours(h)
        for groups in (settings.get("hooks") or {}).values()
        if isinstance(groups, list)
        for g in groups
        if isinstance(g, dict)
        for h in g.get("hooks", [])
    )
