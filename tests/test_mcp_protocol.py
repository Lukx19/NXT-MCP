from __future__ import annotations

import asyncio
import json

from mcp import Client

from nxt_mcp.server import create_server


class FakeController:
    def info(self):
        return {"name": "TEST", "battery_mv": 7600}

    def close(self):
        pass


def test_mcp_initialization_lists_annotated_tools() -> None:
    """In-process protocol smoke test: negotiation, tools/list and tools/call."""
    async def check() -> None:
        async with Client(create_server(controller=FakeController())) as client:
            tools = await client.list_tools()
            by_name = {tool.name: tool for tool in tools.tools}
            assert "nxt_info" in by_name
            assert {"drive_sync", "read_sensor_relative", "log_start", "i2c_transaction"} <= set(by_name)
            assert by_name["nxt_info"].annotations.read_only_hint is True
            assert by_name["run_motor"].annotations.read_only_hint is False
            result = await client.call_tool("nxt_info")
            assert result.is_error is False
            assert json.loads(result.content[0].text)["name"] == "TEST"

    asyncio.run(check())
