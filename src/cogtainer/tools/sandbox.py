"""Core sandbox execution module for Code Mode.

Provides search_tools, load_and_wrap_tools, and execute_in_sandbox for
the execute_code meta-tool used by Code Mode programs.
"""

from __future__ import annotations

import importlib
import io
import json
import logging
import traceback
import types
from dataclasses import dataclass
from typing import Any

import boto3

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_handler(handler_path: str) -> callable:
    """Import a handler from a dotted path like 'module.path:function_name'."""
    module_path, _, func_name = handler_path.partition(":")
    if not module_path or not func_name:
        raise ValueError(f"Invalid handler path '{handler_path}', expected 'module.path:function_name'")
    mod = importlib.import_module(module_path)
    return getattr(mod, func_name)


def _build_namespace(tools_map: dict[str, callable]) -> dict[str, types.SimpleNamespace]:
    """Build nested SimpleNamespace tree from slash-separated tool names.

    Given {"cogtainer/task/create": fn, "io/discord/send": fn2} returns:
        {"cogtainer": SimpleNamespace(task=SimpleNamespace(create=fn)),
         "channels": SimpleNamespace(discord=SimpleNamespace(send=fn2))}
    """
    root: dict[str, Any] = {}

    for tool_path, func in tools_map.items():
        parts = tool_path.split("/")
        if len(parts) < 2:
            # Top-level tool: just store directly
            root[parts[0]] = func
            continue

        top = parts[0]
        if top not in root:
            root[top] = {}

        # Walk / create intermediate dicts
        node = root
        for part in parts[:-1]:
            if part not in node:
                node[part] = {}
            elif not isinstance(node[part], dict):
                # Already a namespace from a previous pass — convert back to dict
                ns = node[part]
                node[part] = {k: getattr(ns, k) for k in vars(ns)}
            node = node[part]

        node[parts[-1]] = func

    # Convert nested dicts to SimpleNamespace recursively
    def _to_ns(d: Any) -> Any:
        if isinstance(d, dict):
            return types.SimpleNamespace(**{k: _to_ns(v) for k, v in d.items()})
        return d

    return {k: _to_ns(v) for k, v in root.items()}


# ---------------------------------------------------------------------------
# Scoped config for tools that need an assumed IAM role
# ---------------------------------------------------------------------------


@dataclass
class ScopedConfig:
    """Config wrapper that carries a scoped boto3 session for cross-account access."""
    cogent_name: str
    region: str
    db_cluster_arn: str
    db_secret_arn: str
    db_name: str
    sessions_bucket: str
    event_bus_name: str
    boto_session: boto3.Session | None = None


def _scoped_config_from(config, boto_session: boto3.Session | None = None) -> ScopedConfig:
    """Build a ScopedConfig from a LambdaConfig, optionally with a scoped session."""
    return ScopedConfig(
        cogent_name=config.cogent_name,
        region=config.region,
        db_cluster_arn=config.db_cluster_arn,
        db_secret_arn=config.db_secret_arn,
        db_name=config.db_name,
        sessions_bucket=config.sessions_bucket,
        event_bus_name=config.event_bus_name,
        boto_session=boto_session,
    )


def _assume_role(role_arn: str, region: str) -> boto3.Session:
    """Assume an IAM role and return a boto3 Session with temporary credentials."""
    sts = boto3.client("sts", region_name=region)
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName="cogent-sandbox")
    creds = resp["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_tools(query: str, tool_names: list[str], repo) -> list[dict]:
    """Search declared tools by substring match on name, description, and instructions.

    Returns list of dicts with keys: name, description, instructions, input_schema.
    Tool names use dot notation (slashes replaced with dots).
    """
    tools = repo.get_tools(tool_names)
    query_lower = query.lower()
    results = []
    for tool in tools:
        searchable = f"{tool.name} {tool.description} {tool.instructions}".lower()
        if query_lower in searchable:
            results.append({
                "name": tool.name.replace("/", "."),
                "description": tool.description,
                "instructions": tool.instructions,
                "input_schema": tool.input_schema,
            })
    return results


def load_and_wrap_tools(tool_names: list[str], config, repo) -> dict[str, types.SimpleNamespace]:
    """Load Tool records and build a callable namespace tree for sandbox execution.

    Each tool becomes a callable at its dot-path location:
        cogtainer/task/create  ->  namespace["cogtainer"].task.create(name="foo")

    The wrapper translates keyword-arg calls into handler(tool_name, input_dict, config).
    Handler results are JSON-parsed when possible, otherwise returned as raw strings.
    """
    tools = repo.get_tools(tool_names)
    tools_map: dict[str, callable] = {}

    for tool in tools:
        if not tool.handler:
            logger.warning("Tool %s has no handler, skipping", tool.name)
            continue

        handler = _import_handler(tool.handler)

        # Build scoped config if tool requires an assumed role
        if tool.iam_role_arn:
            session = _assume_role(tool.iam_role_arn, config.region)
            scoped = _scoped_config_from(config, boto_session=session)
        else:
            scoped = _scoped_config_from(config)

        # Capture tool.name, handler, and scoped in closure
        def _make_wrapper(t_name: str, t_handler: callable, t_config: ScopedConfig):
            def wrapper(**kwargs):
                raw = t_handler(t_name, kwargs, t_config)
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    return raw
            return wrapper

        tools_map[tool.name] = _make_wrapper(tool.name, handler, scoped)

    return _build_namespace(tools_map)


# Builtins allowed inside the sandbox
_SAFE_BUILTINS = {
    "print": print,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "sorted": sorted,
    "min": min,
    "max": max,
    "sum": sum,
    "str": str,
    "int": int,
    "float": float,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "bool": bool,
    "isinstance": isinstance,
    "type": type,
    "hasattr": hasattr,
    "map": map,
    "filter": filter,
    "any": any,
    "all": all,
    "abs": abs,
    "round": round,
    "reversed": reversed,
    "repr": repr,
}


def execute_in_sandbox(code: str, namespace: dict[str, types.SimpleNamespace]) -> str:
    """Execute Python code in a restricted sandbox with tool namespaces available.

    Returns captured stdout on success, or the traceback string on failure.
    """
    restricted_globals: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    restricted_globals["json"] = json
    restricted_globals.update(namespace)

    stdout_capture = io.StringIO()

    # Replace the print builtin with one that writes to our capture buffer
    def _sandbox_print(*args, **kwargs):
        kwargs.setdefault("file", stdout_capture)
        print(*args, **kwargs)

    restricted_globals["__builtins__"]["print"] = _sandbox_print

    try:
        exec(code, restricted_globals)  # noqa: S102
    except Exception:
        return traceback.format_exc()

    output = stdout_capture.getvalue()
    return output if output else "(no output)"
