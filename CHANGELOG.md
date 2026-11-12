# Changelog

## 0.2.0: BurnGuard

The project formerly called Qutato, rebuilt and renamed. Breaking: new package
name, CLI, state directory and Python API.

### Added
- Claude Code hooks (`burnguard install`): loop blocking, daily token budget
  read from session transcripts, secret blocking/redaction, `.env` read
  protection, prompt-injection flags.
- Working MCP server (`burnguard[mcp]`), compatible with MCP SDK 1.x and 2.x.
- Cross-process file locking and atomic writes (hooks run in parallel).
- Test suite (unit, real hook subprocesses, MCP client) and CI on
  Linux/macOS/Windows.

### Fixed
- `pip install` failed on a fresh clone (broken package layout).
- `redis` and `requests` were imported but not declared as dependencies.
- Loop detector state was lost between processes, so it never triggered from the CLI.
- Credit-card redaction matched any 13–16 digit run (no Luhn check).
- Injection check was bypassed by changing case or wording.
- `status` made a network request on every run and compared versions as strings.
- MCP server imported a function that does not exist and never started.

### Removed
- Claims the code did not implement: AES/hardware-bound encryption,
  LiteLLM gateway, "Lagrangian" abstention.
- Abstention engine, agent router, gstack bridge, memory store, Redis quota
  manager, self-updater, and duplicate `qutato-devkit` package. They were
  either placeholders or duplicates. Focus is now on the one job above.
