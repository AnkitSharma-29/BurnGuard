"""burnguard command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from burnguard import __version__, _store, install
from burnguard import scanner as scan
from burnguard.budget import Budget
from burnguard.config import Config


def _parse_value(key: str, raw: str) -> Any:
    kind = {f.name: f.type for f in fields(Config)}[key]
    kind = str(kind)
    if "bool" in kind:
        if raw.lower() in ("true", "1", "yes", "on"):
            return True
        if raw.lower() in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"{key} expects true/false")
    if "int" in kind:
        if "None" in kind and raw.lower() in ("none", "off"):
            return None
        return int(raw.replace(",", "").replace("_", ""))
    if "float" in kind:
        return float(raw)
    return raw


def cmd_status(args: argparse.Namespace) -> int:
    cfg = Config.load()
    st = Budget(cfg).status()
    stats = _store.read_json(_store.home() / "stats.json", {})
    user = install.settings_path("user")
    project = install.settings_path("project")
    limit = "off" if st.limit is None else f"{st.limit:,}"
    print(f"BurnGuard {__version__}")
    print(f"  Budget today   {st.used:,} / {limit} weighted tokens")
    print(
        f"  Hooks          user: {'on' if install.installed(user) else 'off'}"
        f"   project ({Path.cwd().name}): {'on' if install.installed(project) else 'off'}"
    )
    labels = {
        "loops_blocked": "Loops blocked",
        "budget_stops": "Budget stops",
        "secrets_blocked": "Secrets blocked in prompts",
        "secrets_redacted": "Secrets redacted from output",
        "secret_files_blocked": "Secret files blocked",
        "injections_flagged": "Injections flagged",
    }
    print("  Since install:")
    for key, label in labels.items():
        print(f"    {label:<30} {int(stats.get(key, 0))}")
    print(f"  State          {_store.home()}")
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    budget = Budget()
    if args.action == "set":
        if args.tokens is None:
            print("usage: burnguard budget set <tokens>", file=sys.stderr)
            return 2
        Config.set("daily_token_limit", _parse_value("daily_token_limit", args.tokens))
        print(f"Daily budget set to {Config.load().daily_token_limit:,} weighted tokens.")
    elif args.action == "off":
        Config.set("daily_token_limit", None)
        print("Daily budget turned off.")
    elif args.action == "reset":
        budget.reset_today()
        print("Today's usage reset to 0.")
    else:
        st = Budget().status()
        print(f"Used today: {st.used:,}")
        print(f"Limit:      {'off' if st.limit is None else f'{st.limit:,}'}")
        if st.remaining is not None:
            print(f"Remaining:  {st.remaining:,}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    if args.key is None:
        print(json.dumps(asdict(Config.load()), indent=2))
        return 0
    if args.key not in {f.name for f in fields(Config)}:
        print(f"unknown setting: {args.key}", file=sys.stderr)
        return 2
    if args.value is None:
        print(json.dumps(getattr(Config.load(), args.key)))
        return 0
    try:
        Config.set(args.key, _parse_value(args.key, args.value))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"{args.key} = {json.dumps(getattr(Config.load(), args.key))}")
    return 0


def _settings_for(args: argparse.Namespace) -> Path:
    return install.settings_path(args.scope)


def cmd_install(args: argparse.Namespace) -> int:
    path = _settings_for(args)
    try:
        install.install(path)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Not touching {path}: {e}", file=sys.stderr)
        return 1
    print(f"BurnGuard hooks installed in {path}")
    print("Restart Claude Code (or open /hooks) for them to take effect.")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    path = _settings_for(args)
    removed = install.uninstall(path)
    print(f"Removed {removed} BurnGuard hook(s) from {path}" if removed else f"No BurnGuard hooks in {path}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8", errors="replace") if args.file else sys.stdin.read()
    if args.redact:
        sys.stdout.write(scan.redact(text))
        return 0
    findings = scan.scan(text)
    for f in findings:
        line = text.count("\n", 0, f.start) + 1 if f.category != "injection" else "-"
        print(f"{f.kind:<28} line {line}")
    return 1 if findings else 0


def cmd_hook(args: argparse.Namespace) -> int:
    from burnguard.hooks import main

    return main()


def cmd_mcp(args: argparse.Namespace) -> int:
    from burnguard.mcp_server import main

    main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="burnguard",
        description="Stop AI agents from burning tokens: loop blocking, daily budgets, secret guarding.",
    )
    p.add_argument("--version", action="version", version=f"burnguard {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("status", help="show budget, hook state and what BurnGuard has caught").set_defaults(
        func=cmd_status
    )

    b = sub.add_parser("budget", help="show or change the daily token budget")
    b.add_argument("action", nargs="?", choices=["show", "set", "off", "reset"], default="show")
    b.add_argument("tokens", nargs="?", help="limit for `set`, e.g. 2000000 or 2_000_000")
    b.set_defaults(func=cmd_budget)

    c = sub.add_parser("config", help="show or change a setting")
    c.add_argument("key", nargs="?")
    c.add_argument("value", nargs="?")
    c.set_defaults(func=cmd_config)

    for name, func, verb in (("install", cmd_install, "add"), ("uninstall", cmd_uninstall, "remove")):
        s = sub.add_parser(name, help=f"{verb} BurnGuard hooks in Claude Code settings")
        s.add_argument(
            "--scope",
            choices=["user", "project", "local"],
            default="user",
            help="user: ~/.claude/settings.json (default); project: ./.claude/settings.json; "
            "local: ./.claude/settings.local.json",
        )
        s.set_defaults(func=func)

    s = sub.add_parser("scan", help="scan text (stdin or file) for secrets, PII and injection")
    s.add_argument("file", nargs="?")
    s.add_argument("--redact", action="store_true", help="print the text with findings redacted")
    s.set_defaults(func=cmd_scan)

    sub.add_parser("hook", help="(internal) Claude Code hook entry point").set_defaults(func=cmd_hook)
    sub.add_parser("mcp", help='run the MCP server (needs "burnguard[mcp]")').set_defaults(func=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
