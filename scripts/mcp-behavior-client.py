"""Submit and run NXT behavior files through the MCP stdio transport."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("list", "get", "submit", "run"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def unpack(result: Any) -> Any:
    if result.is_error:
        raise RuntimeError(result.content[0].text if result.content else "MCP tool failed")
    if result.structured_content is not None:
        return result.structured_content
    if result.content and getattr(result.content[0], "text", None):
        try:
            return json.loads(result.content[0].text)
        except json.JSONDecodeError:
            return result.content[0].text
    return None


async def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    executable = root / ".venv" / "Scripts" / "nxt-mcp.exe"
    if not executable.exists():
        raise SystemExit(f"MCP server executable not found: {executable}")

    params = StdioServerParameters(
        command=str(executable),
        cwd=root,
        env=dict(os.environ),
    )
    async with Client(params, read_timeout_seconds=max(10, args.timeout + 5)) as client:
        if args.command == "list":
            result = await client.call_tool("list_behaviors")
        elif args.command == "get":
            if not args.name:
                raise SystemExit("get requires NAME")
            result = await client.call_tool("get_behavior", {"name": args.name})
        elif args.command == "submit":
            if not args.name or not args.source:
                raise SystemExit("submit requires NAME SOURCE.py")
            result = await client.call_tool(
                "submit_behavior",
                {"name": args.name, "source": args.source.read_text(encoding="utf-8")},
            )
        else:
            if not args.name:
                raise SystemExit("run requires NAME")
            result = await client.call_tool(
                "run_behavior",
                {"name": args.name, "timeout_seconds": args.timeout},
                read_timeout_seconds=args.timeout + 5,
            )
        print(json.dumps(unpack(result), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
