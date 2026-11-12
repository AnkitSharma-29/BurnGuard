"""MCP server exposing BurnGuard to any MCP client (Cursor, Claude Desktop, ...).

Requires the optional extra:  pip install "burnguard[mcp]"
Run with:                      burnguard mcp
"""

from __future__ import annotations

from typing import Any

from burnguard import scanner as scan
from burnguard.budget import Budget


def build_server() -> Any:
    try:  # mcp >= 2 renamed FastMCP to MCPServer
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server
        except ImportError as e:
            raise SystemExit('MCP support is not installed. Run: pip install "burnguard[mcp]"') from e

    server = Server("burnguard")

    @server.tool()
    def budget_status() -> dict:
        """Today's weighted token usage, limit and remaining budget."""
        st = Budget().status()
        return {
            "day": st.day,
            "used": st.used,
            "limit": st.limit,
            "remaining": st.remaining,
            "exceeded": st.exceeded,
        }

    @server.tool()
    def record_tokens(tokens: int) -> dict:
        """Add tokens spent by an LLM call to today's budget. Returns the new status."""
        st = Budget().record(tokens)
        return {"used": st.used, "limit": st.limit, "exceeded": st.exceeded}

    @server.tool()
    def scan_text(text: str) -> list[dict]:
        """Find secrets, personal data and prompt-injection phrasing in text."""
        return [{"kind": f.kind, "start": f.start, "end": f.end} for f in scan.scan(text)]

    @server.tool()
    def redact_text(text: str) -> str:
        """Return text with secrets and personal data replaced by [REDACTED:<kind>]."""
        return scan.redact(text)

    return server


def main() -> None:
    build_server().run()  # stdio transport
