"""CogOS executor — runs processes via Bedrock converse API with search + run_code."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import boto3

from cogos.db.models import Event, Process, ProcessStatus, Run, RunStatus
from cogos.db.repository import Repository
from cogos.sandbox.executor import SandboxExecutor, VariableTable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutorConfig:
    region: str = "us-east-1"
    db_cluster_arn: str = ""
    db_secret_arn: str = ""
    db_name: str = ""
    max_turns: int = 20
    default_model: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"


def get_config() -> ExecutorConfig:
    return ExecutorConfig(
        region=os.environ.get("AWS_REGION", "us-east-1"),
        db_cluster_arn=os.environ.get("DB_CLUSTER_ARN", os.environ.get("DB_RESOURCE_ARN", "")),
        db_secret_arn=os.environ.get("DB_SECRET_ARN", ""),
        db_name=os.environ.get("DB_NAME", ""),
        max_turns=int(os.environ.get("MAX_TURNS", "20")),
        default_model=os.environ.get("DEFAULT_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0"),
    )


def get_repo(config: ExecutorConfig | None = None) -> Repository:
    config = config or get_config()
    return Repository.create(
        resource_arn=config.db_cluster_arn,
        secret_arn=config.db_secret_arn,
        database=config.db_name,
        region=config.region,
    )


# ── Meta-capability definitions ──────────────────────────────

TOOL_CONFIG = {"tools": [
    {"toolSpec": {
        "name": "search",
        "description": (
            "Search available capabilities by keyword. Returns names, descriptions, "
            "and schemas. Use this to discover what capabilities are available."
        ),
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword (e.g. 'files', 'events', 'procs')",
                },
            },
            "required": ["query"],
        }},
    }},
    {"toolSpec": {
        "name": "run_code",
        "description": (
            "Execute Python code with access to capability proxy objects. "
            "Use search() first to discover available capabilities. "
            "Capabilities are exposed as top-level objects: files, procs, events, resources. "
            "Print results to see them. Returns stdout output or error traceback."
        ),
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                },
            },
            "required": ["code"],
        }},
    }},
]}


def handler(event: dict, context: Any = None) -> dict:
    """Lambda entry point — parse payload and execute process."""
    config = get_config()
    repo = get_repo(config)

    process_id = event.get("process_id")
    event_id = event.get("event_id")

    if not process_id:
        return {"statusCode": 400, "error": "Missing process_id"}

    process = repo.get_process(UUID(process_id))
    if not process:
        return {"statusCode": 404, "error": f"Process not found: {process_id}"}

    # Mark as running
    repo.update_process_status(process.id, ProcessStatus.RUNNING)

    # Create run record
    run = Run(
        process=process.id,
        event=UUID(event_id) if event_id else None,
        status=RunStatus.RUNNING,
    )
    run_id = repo.create_run(run)
    logger.info(f"Starting run {run_id} for process {process.name}")

    start_time = time.time()
    try:
        run = execute_process(process, event, run, config, repo)
        run.status = RunStatus.COMPLETED
        duration_ms = int((time.time() - start_time) * 1000)

        repo.complete_run(
            run.id,
            status=RunStatus.COMPLETED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            duration_ms=duration_ms,
            result=run.result,
            scope_log=run.scope_log,
        )

        # Emit completion event
        repo.append_event(Event(
            event_type="process:run:success",
            source=process.name,
            payload={"run_id": str(run.id), "process_id": str(process.id),
                     "process_name": process.name, "duration_ms": duration_ms},
        ))

        # Transition process state: daemons go back to runnable, one-shots complete
        if process.mode.value == "daemon":
            repo.update_process_status(process.id, ProcessStatus.RUNNABLE)
        else:
            repo.update_process_status(process.id, ProcessStatus.COMPLETED)

        logger.info(f"Run {run_id} completed in {duration_ms}ms")
        return {"statusCode": 200, "run_id": str(run_id)}

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)

        repo.complete_run(
            run.id,
            status=RunStatus.FAILED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            duration_ms=duration_ms,
            error=str(e)[:4000],
        )

        repo.append_event(Event(
            event_type=f"process:failed:{process.name}",
            source=process.name,
            payload={"run_id": str(run.id), "error": str(e)[:1000]},
        ))

        # Retry logic
        if process.retry_count < process.max_retries:
            repo.increment_retry(process.id)
            repo.update_process_status(process.id, ProcessStatus.RUNNABLE)
        else:
            repo.update_process_status(process.id, ProcessStatus.DISABLED)

        logger.error(f"Run {run_id} failed: {e}")
        return {"statusCode": 500, "error": str(e)}


def execute_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: ExecutorConfig,
    repo: Repository,
    *,
    bedrock_client: Any | None = None,
) -> Run:
    """Execute process via Bedrock converse API with search + run_code tool loop."""
    bedrock = bedrock_client or boto3.client("bedrock-runtime", region_name=config.region)

    # Build system prompt using the shared ContextEngine
    from cogos.files.context_engine import ContextEngine
    from cogos.files.store import FileStore
    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)
    system_prompt = ctx.generate_full_prompt(process)

    if not system_prompt:
        system_prompt = "You are a CogOS process. Follow your instructions and use capabilities to accomplish your task."

    # Prepend includes — all files under "includes/" are auto-injected
    includes_content = _load_includes(repo)
    if includes_content:
        system_prompt = includes_content + "\n\n" + system_prompt

    system = [{"text": system_prompt}]

    # Build user message from process content + event
    user_text = ""
    if process.content:
        user_text += process.content + "\n\n"
    if event_data.get("event_type"):
        user_text += f"Event: {event_data.get('event_type', 'unknown')}\n"
        if event_data.get("payload"):
            user_text += f"Payload: {json.dumps(event_data['payload'], indent=2)}\n"
    if not user_text.strip():
        user_text = "Execute your task."

    messages = [{"role": "user", "content": [{"text": user_text}]}]

    # Set up sandbox with capability proxies
    vt = VariableTable()
    _setup_capability_proxies(vt, process, repo, run_id=run.id)
    sandbox = SandboxExecutor(vt)

    model_id = process.model or config.default_model
    run.model_version = model_id

    total_input_tokens = 0
    total_output_tokens = 0

    for _turn in range(config.max_turns):
        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "messages": messages,
            "system": system,
            "toolConfig": TOOL_CONFIG,
        }

        response = bedrock.converse(**kwargs)
        output_message = response["output"]["message"]
        messages.append(output_message)

        usage = response.get("usage", {})
        total_input_tokens += usage.get("inputTokens", 0)
        total_output_tokens += usage.get("outputTokens", 0)

        stop_reason = response.get("stopReason", "end_turn")

        if stop_reason == "tool_use":
            tool_results = []
            for block in output_message.get("content", []):
                if "toolUse" not in block:
                    continue
                tool_use = block["toolUse"]
                tool_name = tool_use.get("name", "")
                tool_input = tool_use.get("input", {})

                if tool_name == "search":
                    result = _handle_search(tool_input, process, repo)
                elif tool_name == "run_code":
                    result = sandbox.execute(tool_input.get("code", ""))
                else:
                    result = f"Unknown tool: {tool_name}"

                tool_results.append({
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": result}],
                    }
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    run.tokens_in = total_input_tokens
    run.tokens_out = total_output_tokens
    run.scope_log = sandbox.scope_log
    return run


def _load_includes(repo: Repository) -> str:
    """Load all files under 'includes/' and concatenate their content."""
    from cogos.files.store import FileStore
    file_store = FileStore(repo)
    files = file_store.list_files(prefix="includes/")
    parts = []
    for f in sorted(files, key=lambda f: f.key):
        fv = repo.get_active_file_version(f.id)
        if fv and fv.content:
            parts.append(fv.content)
    return "\n\n".join(parts)


def _handle_search(tool_input: dict, process: Process, repo: Repository) -> str:
    """Search capabilities available to this process."""
    query = tool_input.get("query", "").lower()
    caps = repo.search_capabilities(query, process_id=process.id)
    if not caps:
        # Fallback: search all capabilities
        caps = repo.search_capabilities(query)
    results = []
    for cap in caps:
        results.append({
            "name": cap.name,
            "description": cap.description,
            "instructions": cap.instructions,
            "input_schema": cap.input_schema,
        })
    return json.dumps(results, indent=2) if results else "No capabilities found matching query."


def _setup_capability_proxies(vt: VariableTable, process: Process, repo: Repository, *, run_id: UUID | None = None) -> None:
    """Inject capability proxy objects into the variable table.

    Dynamically loads all capabilities bound to this process via their
    handler class path, falling back to built-in proxies for files/procs/events.
    """
    import importlib
    import inspect

    from cogos.files.store import FileStore

    file_store = FileStore(repo)

    # Built-in proxies for core capabilities
    class FilesProxy:
        def read(self, key: str) -> dict | None:
            f = file_store.get(key)
            if f is None:
                return None
            fv = repo.get_active_file_version(f.id)
            return {"id": str(f.id), "key": f.key, "content": fv.content if fv else ""}

        def write(self, key: str, content: str) -> dict:
            result = file_store.upsert(key, content)
            if hasattr(result, "key"):
                return {"id": str(result.id), "key": result.key}
            return {"status": "updated"}

        def search(self, query: str) -> list[dict]:
            files = file_store.list_files(prefix=query)
            return [{"id": str(f.id), "key": f.key} for f in files]

    class ProcsProxy:
        def list(self) -> list[dict]:
            procs = repo.list_processes()
            return [{"id": str(p.id), "name": p.name, "status": p.status.value} for p in procs]

        def get(self, name: str) -> dict | None:
            p = repo.get_process_by_name(name)
            if p is None:
                return None
            return {"id": str(p.id), "name": p.name, "status": p.status.value, "mode": p.mode.value}

    class EventsProxy:
        def emit(self, event_type: str, payload: dict | None = None) -> str:
            evt = Event(event_type=event_type, source=process.name, payload=payload or {})
            eid = repo.append_event(evt)
            return str(eid)

        def query(self, event_type: str | None = None, limit: int = 20) -> list[dict]:
            evts = repo.get_events(event_type=event_type, limit=limit)
            return [{"id": str(e.id), "type": e.event_type, "payload": e.payload} for e in evts]

    vt.set("files", FilesProxy())
    vt.set("procs", ProcsProxy())
    vt.set("events", EventsProxy())
    vt.set("print", print)

    # "me" capability — needs run_id, injected separately
    from cogos.capabilities.me import MeCapability
    vt.set("me", MeCapability(repo, process.id, run_id=run_id))

    # Dynamically load additional capabilities bound to this process
    pcs = repo.list_process_capabilities(process.id)
    for pc in pcs:
        cap = repo.get_capability(pc.capability)
        if cap is None or not cap.enabled:
            continue
        ns = cap.name.split("/")[0] if "/" in cap.name else cap.name
        if ns in ("files", "procs", "events", "scheduler", "me"):
            continue  # already set up above
        if ":" in cap.handler:
            mod_path, attr_name = cap.handler.rsplit(":", 1)
        elif "." in cap.handler:
            mod_path, attr_name = cap.handler.rsplit(".", 1)
        else:
            continue
        try:
            mod = importlib.import_module(mod_path)
            handler_cls = getattr(mod, attr_name)
            if inspect.isclass(handler_cls):
                vt.set(ns, handler_cls(repo, process.id))
            else:
                vt.set(ns, handler_cls)
        except (ImportError, AttributeError) as exc:
            logger.warning("Could not load capability %s (%s): %s", cap.name, cap.handler, exc)
