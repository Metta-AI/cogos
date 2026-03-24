"""Agent SDK executor — converts CogOS capabilities to @tool functions."""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, get_type_hints

from claude_agent_sdk import create_sdk_mcp_server, tool
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def get_public_methods(cap: Any) -> list[tuple[str, Any]]:
    skip = {"help", "scope"}
    results = []
    for name in dir(cap):
        if name.startswith("_") or name in skip:
            continue
        attr = getattr(cap, name, None)
        if callable(attr) and not isinstance(attr, type):
            results.append((name, attr))
    return results


def schema_from_method(method: Any) -> dict:
    try:
        hints = get_type_hints(method)
    except Exception:
        hints = {}

    sig = inspect.signature(method)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        ptype = hints.get(pname, str)
        origin = getattr(ptype, "__origin__", None)
        if origin is type(None):
            continue
        args = getattr(ptype, "__args__", None)
        if args and type(None) in args:
            ptype = next(a for a in args if a is not type(None))
        else:
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        json_type = _TYPE_MAP.get(ptype, "string")
        properties[pname] = {"type": json_type}

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


class _CallableTool:
    """Wraps SdkMcpTool to be directly callable and carry __tool_name__."""

    def __init__(self, sdk_tool: Any, tool_name: str) -> None:
        self._sdk_tool = sdk_tool
        self.__tool_name__ = tool_name

    async def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self._sdk_tool.handler(args)

    def unwrap(self) -> Any:
        return self._sdk_tool


def build_tool_functions(capabilities: dict[str, Any]) -> list[_CallableTool]:
    tools = []

    for cap_name, cap in capabilities.items():
        for method_name, method in get_public_methods(cap):
            tool_name = f"{cap_name}_{method_name}"
            description = (method.__doc__ or f"{cap_name}.{method_name}").strip().split("\n")[0]
            schema = schema_from_method(method)

            @tool(tool_name, description, schema)
            async def handler(
                args: dict[str, Any],
                _cap: Any = cap,
                _method: Any = method,
                _name: str = method_name,
            ) -> dict[str, Any]:
                try:
                    _cap._check(_name, **args)
                except PermissionError as e:
                    return {"content": [{"type": "text", "text": f"Error: {e}"}]}
                try:
                    result = _method(**args)
                    if isinstance(result, BaseModel):
                        text = json.dumps(result.model_dump(), default=str)
                    elif isinstance(result, (dict, list)):
                        text = json.dumps(result, default=str)
                    else:
                        text = str(result)
                    return {"content": [{"type": "text", "text": text}]}
                except Exception as e:
                    return {"content": [{"type": "text", "text": f"Error: {e}"}]}

            tools.append(_CallableTool(handler, tool_name))

    return tools


def build_mcp_server(capabilities: dict[str, Any]) -> Any:
    callable_tools = build_tool_functions(capabilities)
    sdk_tools = [ct.unwrap() for ct in callable_tools]
    return create_sdk_mcp_server(name="cogent", version="1.0.0", tools=sdk_tools)


def to_sdk_model(model_id: str) -> str:
    return model_id


import asyncio
from decimal import Decimal
from uuid import UUID

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from cogos.db.models import Process, Run
from cogos.db.repository import Repository
from cogos.executor.capabilities import build_process_capabilities


def execute_agent_sdk_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: Any,
    repo: Repository,
    *,
    trace_id: UUID | None = None,
) -> Run:
    return asyncio.run(_execute_agent_sdk_process(process, event_data, run, config, repo, trace_id=trace_id))


async def _execute_agent_sdk_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: Any,
    repo: Repository,
    *,
    trace_id: UUID | None = None,
) -> Run:
    capabilities = build_process_capabilities(process.id, repo, run_id=run.id, trace_id=trace_id)

    tools = build_tool_functions(capabilities)
    server = create_sdk_mcp_server(name="cogent", version="1.0.0", tools=[t.unwrap() for t in tools])
    tool_names = [f"mcp__cogent__{t.__tool_name__}" for t in tools]

    from cogos.files.context_engine import ContextEngine
    from cogos.files.store import FileStore

    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)
    system_prompt = ctx.generate_full_prompt(process)
    if not system_prompt:
        system_prompt = "You are a CogOS process. Follow your instructions and use capabilities to accomplish your task."

    # Inject capability help text into system prompt
    from cogos.executor.handler import _build_capability_help_text
    cap_help = _build_capability_help_text(capabilities)
    if cap_help:
        system_prompt += "\n\n--- Capabilities ---\n\n" + cap_help

    user_text = _build_user_message(process, event_data, repo)

    model = to_sdk_model(process.model or config.default_model)
    run.model_version = process.model or config.default_model

    options = ClaudeAgentOptions(
        mcp_servers={"cogent": server},
        allowed_tools=tool_names,
        permission_mode="bypassPermissions",
        max_turns=getattr(config, "max_turns", 20),
        system_prompt=system_prompt,
        model=model,
    )

    async for msg in query(prompt=user_text, options=options):
        if isinstance(msg, ResultMessage):
            usage = msg.usage or {}
            run.tokens_in = usage.get("input_tokens", 0)
            run.tokens_out = usage.get("output_tokens", 0)
            run.cost_usd = Decimal(str(msg.total_cost_usd or 0))
            if msg.subtype == "success":
                run.result = {"text": msg.result} if msg.result else None
            else:
                run.error = f"Agent stopped: {msg.subtype}"

    return run


def _build_user_message(process: Process, event_data: dict, repo: Repository) -> str:
    user_text = ""
    web_request = event_data.get("web_request")
    if web_request:
        user_text += f"Incoming web request:\n{json.dumps(web_request, indent=2)}\n"
    if event_data.get("payload"):
        user_text += f"Message payload: {json.dumps(event_data['payload'], indent=2)}\n"
    if not user_text.strip():
        user_text = "Execute your task."
    return user_text
