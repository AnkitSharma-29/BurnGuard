"""Talk to `burnguard mcp` over stdio with the official MCP client."""

import asyncio
import json
import os
import sys

import pytest

mcp = pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def _session_calls():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "burnguard", "mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {t.name for t in (await session.list_tools()).tools}
        redacted = await session.call_tool("redact_text", {"text": "mail a@b.co"})
        recorded = await session.call_tool("record_tokens", {"tokens": 42})
        status = await session.call_tool("budget_status", {})
        return tools, redacted, recorded, status


def test_mcp_server_end_to_end():
    tools, redacted, recorded, status = asyncio.run(_session_calls())
    assert tools == {"budget_status", "record_tokens", "scan_text", "redact_text"}
    assert "[REDACTED:email]" in redacted.content[0].text
    assert json.loads(status.content[0].text)["used"] == 42
