"""Dedicated STDIO entrypoint for Claude and Codex local hosts."""
from .server import create_server


def main() -> None:
    create_server().run("stdio")
