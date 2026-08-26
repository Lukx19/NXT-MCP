"""Dedicated Streamable HTTP entrypoint for local testing or a secure gateway."""
from __future__ import annotations

import os

from .server import main as server_main


def main() -> None:
    # Keep the CLI parser and remote-host guard in one place.
    os.environ.setdefault("NXT_MCP_TRANSPORT", "streamable-http")
    server_main()
