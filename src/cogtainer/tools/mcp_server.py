"""MCP server (stdio transport) exposing Code Mode tools for the ECS executor path.

Provides two tools:
  - search_tools: search available tools by query string
  - execute_code: run Python code in the sandbox with loaded tools
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import mcp.types as types  # type: ignore[import-not-found]
from mcp.server import Server  # type: ignore[import-not-found]
from mcp.server.stdio import stdio_server  # type: ignore[import-not-found]

from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.db import get_repo
from cogtainer.tools.sandbox import (
    execute_in_sandbox,
    load_and_wrap_tools,
    search_tools,
)

logger = logging.getLogger(__name__)

server = Server("cogent-sandbox")

# Parsed once at startup from the COGENT_TOOL_NAMES env var.
TOOL_NAMES: list[str] = []


def _get_tool_names() -> list[str]:
    global TOOL_NAMES
    if not TOOL_NAMES:
        raw = os.environ.get("COGENT_TOOL_NAMES", "")
        TOOL_NAMES = [t.strip() for t in raw.split(",") if t.strip()]
    return TOOL_NAMES


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_tools",
            description=(
                "Search available tools by keyword. Returns matching tool names, "
                "descriptions, instructions, and input schemas."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to search for in tool names, descriptions, and instructions.",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="execute_code",
            description=(
                "Execute Python code in a sandboxed environment with tools available "
                "as callable namespaces (e.g. cogtainer.task.create(name='foo')). "
                "Use search_tools first to discover available tools and their schemas."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute in the sandbox.",
                    },
                },
                "required": ["code"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    tool_names = _get_tool_names()
    repo = get_repo()

    if name == "search_tools":
        query = arguments.get("query", "")
        results = search_tools(query, tool_names, repo)
        return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

    if name == "execute_code":
        code = arguments.get("code", "")
        config = get_config()
        namespace = load_and_wrap_tools(tool_names, config, repo)
        result = execute_in_sandbox(code, namespace)
        return [types.TextContent(type="text", text=result)]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
