import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def bg_home(tmp_path, monkeypatch):
    """Every test gets its own empty state directory."""
    home = tmp_path / "bg-home"
    monkeypatch.setenv("BURNGUARD_HOME", str(home))
    monkeypatch.delenv("BURNGUARD_DISABLE", raising=False)
    return home


def assistant(msg_id: str, inp=0, out=0, cache_read=0, cache_write=0) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": msg_id,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
        },
    }


def write_lines(path: Path, records, mode="a") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
