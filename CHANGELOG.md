# Changelog

## 0.2.1

**Upgrade note:** run `burnguard install` again after upgrading. It adds the new
`PostToolUseFailure` hook. Without it, failing commands are still not counted.

### Fixed
- **Loops of failing commands were never blocked.** Claude Code reports a failed
  tool call (such as a test command exiting non-zero) only through
  `PostToolUseFailure`, which BurnGuard did not handle. Failed calls now count,
  with the error as their result.
- **Identical calls sent in one parallel batch slipped past the limit.** All
  their PreToolUse checks ran before any call finished. Running calls are now
  reserved and counted under the lock.
- The `status` counter is renamed to "Repeat calls blocked", because it counts
  blocked calls, not loops.

### Added
- Demo GIF in the README, replayed from real Claude Code sessions.

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
