import json

import pytest

from burnguard import install
from burnguard.cli import main
from burnguard.config import Config


def test_install_is_idempotent_and_preserves_other_hooks(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir()
    other = {"type": "command", "command": "echo mine"}
    path.write_text(
        json.dumps({"model": "opus", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [other]}]}})
    )
    install.install(path)
    install.install(path)
    data = json.loads(path.read_text())
    assert data["model"] == "opus"
    pre = data["hooks"]["PreToolUse"]
    assert pre[0] == {"matcher": "Bash", "hooks": [other]}
    ours = [h for g in pre for h in g["hooks"] if install.MARKER in h["command"]]
    assert len(ours) == 1
    assert "matcher" not in data["hooks"]["UserPromptSubmit"][0]
    assert install.installed(path)
    assert (path.parent / "settings.json.burnguard.bak").exists()


def test_uninstall_leaves_other_hooks(tmp_path):
    path = tmp_path / "settings.json"
    other = {"type": "command", "command": "echo mine"}
    path.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [other]}]}}))
    install.install(path)
    assert install.uninstall(path) == 3
    assert json.loads(path.read_text()) == {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [other]}]}}
    assert not install.installed(path)


def test_uninstall_removes_empty_hooks_key(tmp_path):
    path = tmp_path / "settings.json"
    install.install(path)
    install.uninstall(path)
    assert json.loads(path.read_text()) == {}


def test_install_refuses_invalid_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ oops")
    with pytest.raises(json.JSONDecodeError):
        install.install(path)
    assert path.read_text() == "{ oops"


def test_hook_command_uses_absolute_interpreter():
    cmd = install.hook_command()
    assert cmd.startswith('"') and "\\" not in cmd and cmd.endswith("-m burnguard hook")


def test_cli_budget_flow(capsys):
    assert main(["budget", "set", "2_000_000"]) == 0
    assert Config.load().daily_token_limit == 2_000_000
    assert main(["budget"]) == 0
    assert "2,000,000" in capsys.readouterr().out
    assert main(["budget", "off"]) == 0
    assert Config.load().daily_token_limit is None


def test_cli_config(capsys):
    assert main(["config", "loop_max_repeats", "5"]) == 0
    assert Config.load().loop_max_repeats == 5
    assert main(["config", "flag_injection", "false"]) == 0
    assert Config.load().flag_injection is False
    assert main(["config", "nope", "1"]) == 2
    assert main(["config", "flag_injection", "maybe"]) == 2


def test_cli_scan(tmp_path, capsys):
    f = tmp_path / "x.txt"
    f.write_text("line one\nkey AKIA" + "IOSFODNN7EXAMPLE\n")
    assert main(["scan", str(f)]) == 1
    assert "secret:aws_access_key" in capsys.readouterr().out
    f.write_text("nothing here")
    assert main(["scan", str(f)]) == 0


def test_cli_status(capsys):
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Budget today" in out and "Loops blocked" in out
