"""MCP server exposing run_code for CogOS ECS runner.

Runs as a stdio-transport MCP server. Claude Code connects to it and uses
the run_code meta-capability to interact with the CogOS system on behalf
of a process.  Capability discovery happens inside the sandbox via the
`capabilities` directory object.

Usage:
    python -m cogos.sandbox.server --process-id <UUID>

Environment variables for DB connection:
    DB_RESOURCE_ARN, DB_SECRET_ARN, DB_NAME, AWS_REGION
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import UUID

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from cogos.capabilities.loader import build_capability_proxies
from cogos.db.repository import Repository
from cogos.sandbox.executor import SandboxExecutor, VariableTable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def create_server(process_id: UUID, repo: Repository) -> Server:
    """Create an MCP server with the run_code tool for *process_id*."""
    from cogos.capabilities.base import Capability
    from cogos.capabilities.directory import CapabilitiesDirectory

    server = Server("cogos-sandbox")

    # Build sandbox once -- shared across all run_code calls in this session.
    vt = VariableTable()
    proxies = build_capability_proxies(repo, process_id)
    for name, proxy in proxies.items():
        vt.set(name, proxy)

    # Inject CapabilitiesDirectory for in-sandbox discovery
    cap_entries = {n: p for n, p in proxies.items() if isinstance(p, Capability)}
    directory = CapabilitiesDirectory(cap_entries)
    vt.set("capabilities", directory)

    executor = SandboxExecutor(vt)

    # Build the system description that tells Claude what's available
    cap_names = sorted(cap_entries.keys())
    cap_list = ", ".join(cap_names)
    dir_note = (
        f"Available capabilities: [{cap_list}]. "
        "Use capabilities.list(), capabilities.search(query), or <name>.help() "
        "to discover methods and schemas."
    )

    # -- Tool list --------------------------------------------------------

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="run_code",
                description=(
                    "Execute Python code in the CogOS sandbox. "
                    "Capability proxy objects are pre-injected as variables: "
                    f"{cap_list}. "
                    "A `capabilities` directory is also available for discovery. "
                    f"{dir_note}"
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
