"""Executor Lambda handler — runs programs via Bedrock converse API."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import boto3

from brain.db.models import Event, Program, ProgramType, Run, RunStatus
from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.db import get_repo
from brain.lambdas.shared.events import emit_run_result, put_event
from brain.lambdas.shared.logging import setup_logging

logger = setup_logging()


def handler(event: dict, context) -> dict:
    """Lambda entry point — parse payload and execute program."""
    config = get_config()
    repo = get_repo()

    trigger_data = event.get("trigger", {})
    event_data = event.get("event", {})
    task_data = event.get("task", {})
    program_name = trigger_data.get("program_name", "")

    # Load program
    program = repo.get_program(program_name)
    if not program:
        logger.error(f"Program not found: {program_name}")
        return {"statusCode": 404, "error": f"Program not found: {program_name}"}

    # Create run record
    trigger_id_raw = trigger_data.get("id")
    try:
        trigger_id = UUID(trigger_id_raw) if trigger_id_raw else None
    except ValueError:
        trigger_id = None
    run = Run(
        program_name=program_name,
        trigger_id=trigger_id,
        status=RunStatus.RUNNING,
    )
    task_id_str = task_data.get("id")
    if task_id_str:
        run.task_id = UUID(task_id_str)
    run_id = repo.insert_run(run)
    logger.info(f"Starting run {run_id} for program {program_name}")

    start_time = time.time()
    try:
        if program.program_type == ProgramType.PYTHON:
            run = execute_python_program(program, event_data, run, config,
                                         task_data=task_data if task_data else None)
        else:
            run = execute_program(program, event_data, run, config,
                                  task_data=task_data if task_data else None)
        run.status = RunStatus.COMPLETED
        run.duration_ms = int((time.time() - start_time) * 1000)
        run.completed_at = datetime.now(timezone.utc)
        repo.update_run(run)

        # Emit completion event
        put_event(
            Event(
                event_type=f"program:completed:{program_name}",
                source=program_name,
                payload={"run_id": str(run.id), "duration_ms": run.duration_ms},
                parent_event_id=event_data.get("id"),
            ),
            config.event_bus_name,
        )

        emit_run_result(
            succeeded=True,
            run_id=str(run.id),
            task_id=task_id_str,
            source=program_name,
            parent_event_id=event_data.get("id"),
            bus_name=config.event_bus_name,
        )

        logger.info(f"Run {run_id} completed in {run.duration_ms}ms")
        return {"statusCode": 200, "run_id": str(run_id)}

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        run.status = RunStatus.FAILED
        run.error = str(e)[:4000]
        run.duration_ms = duration_ms
        run.completed_at = datetime.now(timezone.utc)
        repo.update_run(run)

        # Emit failure event
        put_event(
            Event(
                event_type=f"program:failed:{program_name}",
                source=program_name,
                payload={"run_id": str(run.id), "error": str(e)[:1000]},
                parent_event_id=event_data.get("id"),
            ),
            config.event_bus_name,
        )

        emit_run_result(
            succeeded=False,
            run_id=str(run.id),
            task_id=task_id_str,
            source=program_name,
            parent_event_id=event_data.get("id"),
            bus_name=config.event_bus_name,
            error=str(e),
        )

        logger.error(f"Run {run_id} failed: {e}")
        return {"statusCode": 500, "error": str(e)}


def execute_program(program: Program, event_data: dict, run: Run, config,
                    task_data: dict | None = None) -> Run:
    """Execute program via Bedrock converse API with tool-use loop."""
    bedrock = boto3.client("bedrock-runtime", region_name=config.region)

    # Merge task overrides into a program copy
    if task_data:
        merged_memory_keys = list(set(
            (program.memory_keys or []) + (task_data.get("memory_keys") or [])
        ))
        merged_tools = list(set(
            (program.tools or []) + (task_data.get("tools") or [])
        ))
        program = program.model_copy(update={
            "memory_keys": merged_memory_keys,
            "tools": merged_tools,
        })

    # Build system prompt with memory context
    from memory.context_engine import ContextEngine
    from memory.store import MemoryStore

    repo = get_repo()
    memory_store = MemoryStore(repo)
    context_engine = ContextEngine(memory_store)

    system = context_engine.build_system_prompt(program, event_data)

    # Build user message: task content + event context
    user_text = ""
    if task_data and task_data.get("content"):
        user_text += task_data["content"] + "\n\n"
    user_text += f"Event: {event_data.get('event_type', 'unknown')}\n"
    if event_data.get("payload"):
        user_text += f"Payload: {json.dumps(event_data['payload'], indent=2)}\n"

    messages = [{"role": "user", "content": [{"text": user_text}]}]

    # Build tool config from merged program tools
    tool_config = _build_tool_config(program.tools) if program.tools else None

    model_id = program.metadata.get("model_version") or "us.anthropic.claude-sonnet-4-20250514-v1:0"
    run.model_version = model_id

    total_input_tokens = 0
    total_output_tokens = 0

    # Tool-use loop
    max_turns = 20
    for _turn in range(max_turns):
        kwargs: dict = {
            "modelId": model_id,
            "messages": messages,
            "system": system,
        }
        if tool_config:
            kwargs["toolConfig"] = tool_config

        response = bedrock.converse(**kwargs)

        output_message = response["output"]["message"]
        messages.append(output_message)

        # Track usage
        usage = response.get("usage", {})
        total_input_tokens += usage.get("inputTokens", 0)
        total_output_tokens += usage.get("outputTokens", 0)

        stop_reason = response.get("stopReason", "end_turn")

        if stop_reason == "tool_use":
            tool_results = []
            for block in output_message.get("content", []):
                if "toolUse" in block:
                    tool_use = block["toolUse"]
                    result = _execute_tool(tool_use, config)
                    tool_results.append(
                        {
                            "toolResult": {
                                "toolUseId": tool_use["toolUseId"],
                                "content": [{"text": result}],
                            }
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    run.tokens_input = total_input_tokens
    run.tokens_output = total_output_tokens
    # Rough cost estimate (Claude Sonnet pricing)
    run.cost_usd = Decimal(str(total_input_tokens * 0.000003 + total_output_tokens * 0.000015))

    return run


TOOL_SCHEMAS: dict[str, dict] = {
    "memory_get": {
        "description": "Retrieve a memory value by key name.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {"key": {"type": "string", "description": "The memory key to retrieve"}},
            "required": ["key"],
        }},
    },
    "memory_put": {
        "description": "Store a value in memory under a key name.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The memory key name"},
                "value": {"type": "string", "description": "The value to store"},
            },
            "required": ["key", "value"],
        }},
    },
    "event_send": {
        "description": "Send an event to the event bus.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "description": "The event type (e.g. 'greeting', 'alert')"},
                "payload": {"type": "object", "description": "JSON payload for the event", "default": {}},
            },
            "required": ["event_type"],
        }},
    },
}

# Register Gmail tools from channels
from channels.gmail.tools import TOOL_SCHEMAS as _GMAIL_SCHEMAS
TOOL_SCHEMAS.update(_GMAIL_SCHEMAS)


def _build_tool_config(tools: list[str]) -> dict:
    """Build Bedrock tool config from program tool names."""
    tool_specs = []
    for tool_name in tools:
        safe_name = tool_name.replace(":", "_").replace("-", "_").replace(" ", "_")
        schema = TOOL_SCHEMAS.get(safe_name)
        if schema:
            tool_specs.append({"toolSpec": {"name": safe_name, **schema}})
        else:
            # Fallback for unknown tools
            tool_specs.append({
                "toolSpec": {
                    "name": safe_name,
                    "description": f"Execute command: {tool_name}",
                    "inputSchema": {"json": {
                        "type": "object",
                        "properties": {"args": {"type": "string", "description": f"Arguments for {tool_name}"}},
                    }},
                }
            })
    return {"tools": tool_specs}


def _execute_tool(tool_use: dict, config) -> str:
    """Execute a tool natively in-process (no subprocess/CLI dependency)."""
    tool_name = tool_use.get("name", "")
    tool_input = tool_use.get("input", {})

    repo = get_repo()

    try:
        if tool_name == "memory_get":
            key = tool_input.get("key", "").strip()
            if not key:
                return "Error: memory get requires a key"
            results = repo.query_memory(name=key)
            if results:
                return f"{results[0].name}: {results[0].content}"
            return f"Memory '{key}' not found"

        elif tool_name == "memory_put":
            key = tool_input.get("key", "").strip()
            value = tool_input.get("value", "")
            if not key or not value:
                return "Error: memory put requires key and value"
            from brain.db.models import MemoryRecord, MemoryScope
            mem = MemoryRecord(name=key, scope=MemoryScope.COGENT, content=value)
            repo.insert_memory(mem)
            return f"Stored memory '{key}'"

        elif tool_name == "event_send":
            event_type = tool_input.get("event_type", "").strip()
            if not event_type:
                return "Error: event send requires event_type"
            payload = tool_input.get("payload", {})
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {"message": payload}
            ev = Event(event_type=event_type, source="tool", payload=payload)
            event_id = repo.append_event(ev)
            put_event(ev, config.event_bus_name)
            return f"Event sent: id={event_id} type={event_type}"

        elif tool_name in _GMAIL_SCHEMAS:
            from channels.gmail.tools import execute_tool as gmail_execute
            return gmail_execute(tool_name, tool_input, config.cogent_name, config.region)

        else:
            return f"Unknown tool: {tool_name}"

    except Exception as e:
        return f"Tool {tool_name} failed: {e}"


def execute_python_program(
    program: Program, event_data: dict, run: Run, config,
    task_data: dict | None = None,
) -> Run:
    """Execute a Python program by calling its run(repo, event, config) function.

    The program source is stored in program.content. We compile and exec it,
    then call the `run` function which returns a list of Event objects to emit.
    """
    repo = get_repo()

    # Compile and execute the program source to get the run function
    code = compile(program.content, f"<program:{program.name}>", "exec")
    namespace: dict = {}
    exec(code, namespace)  # noqa: S102

    run_fn = namespace.get("run")
    if not callable(run_fn):
        raise RuntimeError(f"Program {program.name} has no callable run() function")

    # Build config dict for the program
    prog_config = {
        "cogent_name": config.cogent_name,
        "cogent_id": config.cogent_id,
        "event_bus_name": config.event_bus_name,
    }

    # Call the program's run function
    result_events = run_fn(repo, event_data, prog_config)

    # Emit any events returned by the program
    if result_events:
        for evt in result_events:
            if isinstance(evt, Event):
                put_event(evt, config.event_bus_name)
                run.events_emitted.append(evt.event_type)

    return run
