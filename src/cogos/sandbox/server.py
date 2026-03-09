"""MCP server exposing search + run_code for CogOS ECS runner.

Runs as a stdio-transport MCP server. Claude Code connects to it and uses
the two meta-capabilities (search, run_code) to interact with the CogOS
system on behalf of a process.

Usage:
    python -m cogos.sandbox.server --process-id <UUID>

Environment variables for DB connection:
    DB_RESOURCE_ARN, DB_SECRET_ARN, DB_NAME, AWS_REGION
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from uuid import UUID

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from cogos.db.repository import Repository
from cogos.sandbox.executor import SandboxExecutor, VariableTable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_capability_proxies(repo: Repository, process_id: UUID) -> dict[str, object]:
    """Load capabilities bound to a process and build proxy objects.

    Each capability class is instantiated with (repo, process_id) and
    injected into the sandbox namespace under its name (e.g. 'files', 'email').
    """
    import importlib
    import inspect

    pcs = repo.list_process_capabilities(process_id)
    proxies: dict[str, object] = {}
    for pc in pcs:
        cap = repo.get_capability(pc.capability)
        if cap is None or not cap.enabled:
            continue
        # Resolve handler dotted path -> callable or class
        if ":" in cap.handler:
            mod_path, attr_name = cap.handler.rsplit(":", 1)
        elif "." in cap.handler:
            mod_path, attr_name = cap.handler.rsplit(".", 1)
        else:
            continue
        try:
            mod = importlib.import_module(mod_path)
            handler = getattr(mod, attr_name)
        except (ImportError, AttributeError) as exc:
            logger.warning("Could not load handler %s: %s", cap.handler, exc)
            continue

        # Use the top-level namespace from the capability name (e.g. "files" from "files/read")
        ns = cap.name.split("/")[0] if "/" in cap.name else cap.name

        # Class capabilities get instantiated with repo and process_id
        if inspect.isclass(handler):
            proxies[ns] = handler(repo, process_id)
        else:
            proxies[ns] = handler
    return proxies


def _format_capabilities(caps: list) -> str:
    """Format capability list for the search tool response."""
    lines: list[str] = []
    for cap in caps:
        lines.append(f"## {cap.name}")
        if cap.description:
            lines.append(f"  {cap.description}")
        if cap.instructions:
            lines.append(f"  Instructions: {cap.instructions}")
        if cap.input_schema:
            lines.append(f"  Input: {json.dumps(cap.input_schema, indent=2)}")
        if cap.output_schema:
            lines.append(f"  Output: {json.dumps(cap.output_schema, indent=2)}")
        lines.append("")
    return "\n".join(lines) if lines else "No capabilities matched."


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def create_server(process_id: UUID, repo: Repository) -> Server:
    """Create an MCP server with search and run_code tools for *process_id*."""

    server = Server("cogos-sandbox")

    # Build sandbox once -- shared across all run_code calls in this session.
    vt = VariableTable()
    proxies = _build_capability_proxies(repo, process_id)
    for name, proxy in proxies.items():
        vt.set(name, proxy)
    executor = SandboxExecutor(vt)

    # -- Tool list --------------------------------------------------------

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search",
                description=(
                    "Search available capabilities by keyword. Returns names, "
                    "descriptions, and schemas for capabilities bound to this process."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keyword to search capabilities by name or description.",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="run_code",
                description=(
                    "Execute Python code in a sandboxed environment. Capability "
                    "proxy objects are pre-injected (e.g. files, procs, events). "
                    "Returns stdout/stderr output."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python code to execute.",
                        },
                    },
                    "required": ["code"],
                },
            ),
        ]

    # -- Tool dispatch ----------------------------------------------------

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "search":
            query = arguments.get("query", "")
            caps = repo.search_capabilities(query, process_id=process_id)
            return [TextContent(type="text", text=_format_capabilities(caps))]

        if name == "run_code":
            code = arguments.get("code", "")
            result = executor.execute(code)
            return [TextContent(type="text", text=result)]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CogOS MCP sandbox server")
    parser.add_argument(
        "--process-id",
        type=str,
        required=True,
        help="UUID of the process this server serves.",
    )
    parser.add_argument("--db-resource-arn", type=str, default=None)
    parser.add_argument("--db-secret-arn", type=str, default=None)
    parser.add_argument("--db-name", type=str, default=None)
    parser.add_argument("--aws-region", type=str, default=None)
    return parser.parse_args()


async def amain() -> None:
    args = parse_args()
    process_id = UUID(args.process_id)

    repo = Repository.create(
        resource_arn=args.db_resource_arn,
        secret_arn=args.db_secret_arn,
        database=args.db_name,
        region=args.aws_region,
    )

    server = create_server(process_id, repo)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
