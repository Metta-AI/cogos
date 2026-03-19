"""Executor Lambda handler — runs programs via Bedrock converse API (Code Mode) or delegates to CogOS."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import boto3
from botocore.config import Config as BotoConfig

from cogtainer.db.models import Alert, AlertSeverity, Event, Program, ProgramType, Run, RunStatus, infer_program_type
from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.db import get_repo
from cogtainer.lambdas.shared.events import emit_run_result, put_event
from cogtainer.lambdas.shared.logging import setup_logging
from cogtainer.tools.sandbox import search_tools

logger = setup_logging()

# ── Code Mode: two meta-tools ────────────────────────────────

CODE_MODE_TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "search_tools",
                "description": (
                    "Search available tools by keyword. Returns tool names, descriptions, "
                    "usage instructions, and input schemas. Use this to discover what tools "
                    "are available before writing code."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search keyword (e.g. 'memory', 'task', 'event')",
                            },
                        },
                        "required": ["query"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "execute_code",
                "description": (
                    "Execute Python code with access to declared tools as callable functions. "
                    "Use search_tools first to discover available tools and their schemas. "
                    "Tools are organized as dot-notation namespaces matching their names "
                    "(e.g. cogtainer.task.create, channels.discord.send). "
                    "Print results to see them. Returns stdout output or error traceback."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute",
                            },
                        },
                        "required": ["code"],
                    }
                },
            }
        },
    ]
}


def handler(event: dict, context) -> dict:
    """Lambda entry point — parse payload and execute program."""
    # Delegate to CogOS executor if this is a cogos process invocation
    if event.get("process_id"):
        from cogos.executor.handler import handler as cogos_handler

        return cogos_handler(event, context)

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
        source = _resolve_program_source(program, repo)
        if infer_program_type(source) == ProgramType.PYTHON:
            run = execute_python_program(program, event_data, run, config, task_data=task_data if task_data else None)
        else:
            run = execute_program(program, event_data, run, config, task_data=task_data if task_data else None)
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

        try:
            repo.create_alert(
                Alert(
                    severity=AlertSeverity.WARNING,
                    alert_type="process:run:failed",
                    source="executor",
                    message=f"Run failed for '{program_name}': {str(e)[:500]}",
                    metadata={
                        "process_name": program_name,
                        "run_id": str(run.id),
                        "duration_ms": duration_ms,
                    },
                )
            )
        except Exception:
            logger.debug("Could not create alert for failed run %s", run.id)

        logger.error(f"Run {run_id} failed: {e}")
        return {"statusCode": 500, "error": str(e)}


def _handle_search_tools(tool_input: dict, tool_names: list[str], repo) -> str:
    """Handle search_tools call in-process."""
    query = tool_input.get("query", "")
    results = search_tools(query, tool_names, repo)
    return json.dumps(results, indent=2)


def _handle_execute_code(tool_input: dict, tool_names: list[str], config) -> str:
    """Handle execute_code by invoking the sandbox Lambda."""
    code = tool_input.get("code", "")
    if not code.strip():
        return "Error: no code provided"

    lambda_client = boto3.client("lambda", region_name=config.region)
    payload = {
        "code": code,
        "tool_names": tool_names,
        "cogent_name": config.cogent_name,
        "region": config.region,
    }

    response = lambda_client.invoke(
        FunctionName=config.sandbox_function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )

    resp_payload = json.loads(response["Payload"].read())

    if response.get("FunctionError"):
        error = resp_payload.get("errorMessage", "Sandbox execution failed")
        return f"Sandbox error: {error}"

    return resp_payload.get("result", "(no result)")


def execute_program(program: Program, event_data: dict, run: Run, config, task_data: dict | None = None) -> Run:
    """Execute program via Bedrock converse API with Code Mode tool loop."""
    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=config.region,
        config=BotoConfig(retries={"max_attempts": 12, "mode": "adaptive"}),
    )
    repo = get_repo()

    # Merge task tool overrides into a program copy
    if task_data:
        merged_tools = list(set((program.tools or []) + (task_data.get("tools") or [])))
        program = program.model_copy(
            update={
                "tools": merged_tools,
            }
        )

    # Build system prompt with memory context
    from memory.context_engine import ContextEngine
    from memory.store import MemoryStore

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

    # Code Mode: always use the two meta-tools
    tool_config = CODE_MODE_TOOL_CONFIG if program.tools else None
    tool_names = program.tools or []

    model_id = program.metadata.get("model_version") or "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
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
                if "toolUse" not in block:
                    continue
                tool_use = block["toolUse"]
                tool_name = tool_use.get("name", "")
                tool_input = tool_use.get("input", {})

                if tool_name == "search_tools":
                    result = _handle_search_tools(tool_input, tool_names, repo)
                elif tool_name == "execute_code":
                    result = _handle_execute_code(tool_input, tool_names, config)
                else:
                    result = f"Unknown tool: {tool_name}"

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


def _resolve_program_source(program: Program, repo) -> str:
    """Resolve program content from its linked memory."""
    from memory.store import MemoryStore

    if not program.memory_id:
        raise RuntimeError(f"Program {program.name} has no linked memory")
    store = MemoryStore(repo)
    mem = store.get_by_id(program.memory_id)
    if not mem:
        raise RuntimeError(f"Program {program.name}: memory {program.memory_id} not found")
    version = program.memory_version or mem.active_version
    mv = mem.versions.get(version)
    if not mv:
        raise RuntimeError(f"Program {program.name}: memory version {version} not found")
    return mv.content


def execute_python_program(
    program: Program,
    event_data: dict,
    run: Run,
    config,
    task_data: dict | None = None,
) -> Run:
    """Execute a Python program by calling its run(repo, event, config) function."""
    repo = get_repo()

    # Resolve program source from memory
    source = _resolve_program_source(program, repo)
    code = compile(source, f"<program:{program.name}>", "exec")
    namespace: dict = {}
    exec(code, namespace)  # noqa: S102

    run_fn = namespace.get("run")
    if not callable(run_fn):
        raise RuntimeError(f"Program {program.name} has no callable run() function")

    prog_config = {
        "cogent_name": config.cogent_name,
        "cogent_id": config.cogent_name,
        "event_bus_name": config.event_bus_name,
    }

    result_events = run_fn(repo, event_data, prog_config)

    if result_events:
        for evt in result_events:  # type: ignore[union-attr]
            if isinstance(evt, Event):
                put_event(evt, config.event_bus_name)
                run.events_emitted.append(evt.event_type)

    return run
