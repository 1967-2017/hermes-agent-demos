"""Check that the Demo 4 MCP server can start and list tools."""

from __future__ import annotations

import json
import sys

from .env import get_mcp_command, get_mcp_timeout_seconds, load_repo_env
from .mcp_client import StdioMcpClient


def main() -> int:
    load_repo_env()
    command = get_mcp_command()
    with StdioMcpClient(command, request_timeout_seconds=get_mcp_timeout_seconds()) as client:
        tools = client.list_tools()
    print(json.dumps({"ok": True, "command": command, "tools": [tool.get("name") for tool in tools]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

