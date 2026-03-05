"""Executor Lambda handler — runs programs via Bedrock converse API."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import boto3

from brain.db.models import Event, Program, Run, RunStatus
from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.db import get_repo
from brain.lambdas.shared.events import put_event
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
    run = Run(
        program_name=program_name,
        trigger_id=trigger_data.get("id"),
        status=RunStatus.RUNNING,
    )
    task_id_str = task_data.get("id")
    if task_id_str:
        run.task_id = UUID(task_id_str)
    run_id = repo.insert_run(run)
    logger.info(f"Starting run {run_id} for program {program_name}")

    start_time = time.time()
    try:
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

    model_id = program.model_version or "anthropic.claude-sonnet-4-20250514"
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


def _build_tool_config(tools: list[str]) -> dict:
    """Build Bedrock tool config from program tool names (mind CLI commands)."""
    tool_specs = []
    for tool_name in tools:
        tool_specs.append(
            {
                "toolSpec": {
                    "name": tool_name.replace(":", "_").replace("-", "_"),
                    "description": f"Execute mind CLI command: {tool_name}",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "args": {
                                    "type": "string",
                                    "description": f"Arguments for the {tool_name} command",
                                }
                            },
                        }
                    },
                }
            }
        )
    return {"tools": tool_specs}


def _execute_tool(tool_use: dict, config) -> str:
    """Execute a mind CLI tool and return result."""
    tool_name = tool_use.get("name", "")
    tool_input = tool_use.get("input", {})
    args = tool_input.get("args", "")

    # Convert tool name back to CLI command format
    cmd_name = tool_name.replace("_", "-")

    try:
        result = subprocess.run(
            ["mind", cmd_name] + (args.split() if args else []),
            capture_output=True,
            text=True,
            timeout=300,
            cwd="/tmp",
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\nError (exit {result.returncode}): {result.stderr}"
        return output[:10000]
    except subprocess.TimeoutExpired:
        return f"Tool {cmd_name} timed out after 300s"
    except Exception as e:
        return f"Tool {cmd_name} failed: {e}"
