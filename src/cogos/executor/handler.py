"""CogOS executor — runs processes via Bedrock converse API with search + run_code."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from cogos.db.models import Process, ProcessStatus, Run, RunStatus
from cogos.db.models.channel_message import ChannelMessage
from cogos.db.repository import Repository
from cogos.executor.session_store import SessionStore, build_prompt_fingerprint
from cogos.sandbox.executor import SandboxExecutor, VariableTable

logger = logging.getLogger(__name__)


# ── Cost estimation ──────────────────────────────────────────
# Bedrock pricing per 1K tokens (USD) as of 2025-06.
# Keys are matched as prefixes against the model ID.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "us.anthropic.claude-sonnet-4": (0.003, 0.015),
    "us.anthropic.claude-haiku-4": (0.0008, 0.004),
    "us.anthropic.claude-opus-4": (0.015, 0.075),
    "anthropic.claude-sonnet-4": (0.003, 0.015),
    "anthropic.claude-haiku-4": (0.0008, 0.004),
    "anthropic.claude-opus-4": (0.015, 0.075),
    "us.anthropic.claude-3-5-sonnet": (0.003, 0.015),
    "us.anthropic.claude-3-haiku": (0.00025, 0.00125),
}


def _estimate_cost(model_id: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Estimate USD cost from model ID and token counts."""
    for prefix, (in_rate, out_rate) in _MODEL_PRICING.items():
        if model_id.startswith(prefix):
            cost = (tokens_in * in_rate + tokens_out * out_rate) / 1000.0
            return Decimal(str(round(cost, 6)))
    return Decimal("0")


TOOL_RESULT_SPILL_THRESHOLD = 4_000
"""Character count above which run_code output is written to the file store
instead of being inlined in the conversation.  The model receives a short
preview + a file key it can read back with files.read().
"""

TOOL_RESULT_PREVIEW_CHARS = 1_000
"""How many characters of a spilled tool result to include inline as a
preview so the model has immediate context without reading the file.
"""


@dataclass(frozen=True)
class ExecutorConfig:
    region: str = "us-east-1"
    db_cluster_arn: str = ""
    db_secret_arn: str = ""
    db_name: str = ""
    max_turns: int = 20
    default_model: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    llm_provider: str = "bedrock"


def get_config() -> ExecutorConfig:
    return ExecutorConfig(
        region=os.environ.get("AWS_REGION", "us-east-1"),
        db_cluster_arn=os.environ.get("DB_CLUSTER_ARN", os.environ.get("DB_RESOURCE_ARN", "")),
        db_secret_arn=os.environ.get("DB_SECRET_ARN", ""),
        db_name=os.environ.get("DB_NAME", ""),
        max_turns=int(os.environ.get("MAX_TURNS", "20")),
        default_model=os.environ.get("DEFAULT_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
        llm_provider=os.environ.get("LLM_PROVIDER", "bedrock"),
    )


_RUNTIME = None


def _get_runtime():
    """Lazily reconstruct a CogtainerRuntime from env vars."""
    global _RUNTIME
    if _RUNTIME is None:
        from cogtainer.runtime.factory import create_executor_runtime
        _RUNTIME = create_executor_runtime()
    return _RUNTIME


def _get_repo(config: ExecutorConfig | None = None) -> Repository:
    """Get repo from CogtainerRuntime."""
    cogent_name = os.environ["COGENT"]
    return _get_runtime().get_repository(cogent_name)


# ── Meta-capability definitions ──────────────────────────────

TOOL_CONFIG = {"tools": [
    {"toolSpec": {
        "name": "search",
        "description": (
            "Search available capabilities by keyword. Returns names and descriptions. "
            "Your capabilities are already injected as top-level objects — use "
            "dir(obj) or obj.help() to see methods. Only use search to discover "
            "capabilities you haven't used yet."
        ),
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword (e.g. 'discord', 'files', 'channels', 'procs', 'data')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5)",
                },
            },
            "required": ["query"],
        }},
    }},
    {"toolSpec": {
        "name": "run_code",
        "description": (
            "Execute Python code in a sandboxed environment. "
            "Variables persist between calls — define a variable in one call, use it in the next. "
            "Capability proxies are pre-injected as top-level objects. "
            "print(__capabilities__) lists available objects. Use obj.help() for method signatures. "
            "Available builtins: print, len, range, sorted, min, max, sum, "
            "str, int, float, list, dict, set, tuple, bool, isinstance, hasattr, getattr, "
            "type, map, filter, any, all, repr, json (pre-loaded). "
            "Use `import time` for timestamps, `import random` for randomness. "
            "Print results to see them."
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

def _spill_tool_result(
    text: str,
    *,
    file_store: Any,
    run_id: UUID,
    turn: int,
    tool_idx: int,
    threshold: int = TOOL_RESULT_SPILL_THRESHOLD,
    preview_chars: int = TOOL_RESULT_PREVIEW_CHARS,
) -> str:
    """If *text* exceeds *threshold*, write it to the file store and return a
    short preview + file key.  Otherwise return *text* unchanged.
    """
    if len(text) <= threshold:
        return text
    key = f"run_output/{run_id}/{turn}-{tool_idx}"
    try:
        file_store.upsert(key, text, source="executor")
    except Exception:
        logger.warning("Could not spill tool output to %s; truncating instead", key)
        return text[:preview_chars] + f"\n\n... [output truncated — {len(text)} chars total] ..."
    preview = text[:preview_chars]
    return (
        f"{preview}\n\n"
        f"... [{len(text)} chars total — full output saved to @{{{key}}}] ...\n"
        f"Use files.read(\"{key}\") to retrieve the complete output."
    )


VALID_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
SUPPORTED_TOOL_NAMES = {
    tool["toolSpec"]["name"]
    for tool in TOOL_CONFIG["tools"]
}
TOOL_NAME_PLACEHOLDER = "search"


def _reply_trace_link(repo, process: Process, event_data: dict, trace_id: UUID) -> None:
    """Reply to the originating Discord message with a trace viewer link."""
    dashboard_url = os.environ.get("DASHBOARD_URL", "")
    if not dashboard_url:
        return

    # Extract Discord metadata from the event payload
    payload = event_data.get("payload", {})
    if not isinstance(payload, dict):
        return

    channel_id = payload.get("channel_id")
    message_id = payload.get("message_id")
    if not channel_id or not message_id:
        return

    trace_link = f"{dashboard_url}/#trace-viewer:{trace_id}"
    try:
        # Write to the Discord output channel via SQS (same mechanism as discord.send)
        from cogos.io.discord.capability import _send_sqs, _with_reply_meta
        body = {
            "channel": channel_id,
            "content": f"\U0001f50d Trace: {trace_link}",
            "reply_to": message_id,
        }
        _send_sqs(_with_reply_meta(body, process_id=process.id, run_id=None, trace_id=trace_id), runtime=_get_runtime())
    except Exception:
        logger.debug("Failed to reply with trace link", exc_info=True)


def handler(event: dict, context: Any = None) -> dict:
    """Lambda entry point — parse payload and execute process."""
    config = get_config()
    repo = _get_repo(config)

    process_id = event.get("process_id")
    message_id = event.get("message_id")
    run_id_str = event.get("run_id")

    if not process_id:
        return {"statusCode": 400, "error": "Missing process_id"}

    process = repo.get_process(UUID(process_id))
    if not process:
        return {"statusCode": 404, "error": f"Process not found: {process_id}"}

    # Use existing run from dispatcher, or create a new one for legacy callers.
    if run_id_str:
        dispatch_run_id = UUID(run_id_str)
        run = None
        for attempt in range(5):
            run = repo.get_run(dispatch_run_id)
            if run:
                break
            if attempt < 4:
                time.sleep(0.2)
        if not run:
            logger.warning("Dispatch run %s not found for process %s; recreating it", run_id_str, process.name)
            run = Run(
                id=dispatch_run_id,
                process=process.id,
                message=UUID(message_id) if message_id else None,
                status=RunStatus.RUNNING,
            )
            try:
                repo.create_run(run)
            except Exception:
                logger.exception("Failed to recreate dispatch run %s; falling back to a new run", run_id_str)
                run = repo.get_run(dispatch_run_id)
                if run is None:
                    run = Run(process=process.id, message=UUID(message_id) if message_id else None, status=RunStatus.RUNNING)
                    repo.create_run(run)
        run_id = run.id
    else:
        # Legacy: no run_id in payload — create one (and mark process running)
        repo.update_process_status(process.id, ProcessStatus.RUNNING)
        run = Run(process=process.id, message=UUID(message_id) if message_id else None, status=RunStatus.RUNNING)
        run_id = repo.create_run(run)

    repo.mark_run_deliveries_delivered(run.id)

    # Extract trace context from dispatch event
    trace_id_str = event.get("trace_id")
    dispatched_at_ms = event.get("dispatched_at_ms")
    executor_started_at_ms = int(time.time() * 1000)
    trace_id = None
    if trace_id_str:
        try:
            trace_id = UUID(trace_id_str)
            # Ensure run has trace_id set (may already be set by scheduler)
            if run.trace_id is None:
                run.trace_id = trace_id
        except (ValueError, Exception):
            logger.debug("Invalid trace_id in event: %s", trace_id_str)

    # Initialize distributed trace context
    from cogos.trace import init_trace
    parent_span_id = None
    if event.get("parent_span_id"):
        try:
            parent_span_id = UUID(event["parent_span_id"])
        except (ValueError, Exception):
            pass

    trace_ctx = init_trace(
        repo,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        source=event.get("source", ""),
        source_ref=event.get("source_ref"),
        cogent_id=os.environ["COGENT"],
    )
    trace_id = trace_ctx.trace_id

    logger.info(f"Starting run {run_id} for process {process.name}")

    start_time = time.time()
    try:
        with trace_ctx.start_span(f"process:{process.name}", coglet=process.name):
            run = execute_process(process, event, run, config, repo, trace_id=trace_id)
        run.status = RunStatus.COMPLETED
        duration_ms = int((time.time() - start_time) * 1000)

        cost = _estimate_cost(run.model_version or "", run.tokens_in, run.tokens_out)
        run.cost_usd = cost

        repo.complete_run(
            run.id,
            status=RunStatus.COMPLETED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=cost,
            duration_ms=duration_ms,
            model_version=run.model_version,
            result=run.result,
            snapshot=run.snapshot,
            scope_log=run.scope_log,
        )
        _log_run_completion_latency(run, process.name, duration_ms)

        if trace_id_str:
            logger.info(
                "CogOS trace executor_timing trace_id=%s run=%s process=%s "
                "dispatched_at_ms=%s executor_started_at_ms=%s executor_duration_ms=%s",
                trace_id_str, run.id, process.name,
                dispatched_at_ms, executor_started_at_ms, duration_ms,
            )

        # Emit lifecycle message to implicit process channel
        _emit_lifecycle_message(repo, process, {
            "type": "process:run:success",
            "run_id": str(run.id),
            "process_id": str(process.id),
            "process_name": process.name,
            "duration_ms": duration_ms,
        })

        _notify_parent_on_exit(repo, process, run, exit_code=0, duration_ms=duration_ms)

        # Transition process state — respect out-of-band status changes
        # Re-fetch to get current mode and status (mode may have changed during execution)
        current = repo.get_process(process.id)
        if current and current.status not in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
            if current.mode.value == "daemon":
                next_status = (
                    ProcessStatus.RUNNABLE
                    if repo.has_pending_deliveries(process.id)
                    else ProcessStatus.WAITING
                )
                repo.update_process_status(process.id, next_status)
            else:
                repo.update_process_status(process.id, ProcessStatus.COMPLETED)

        logger.info(f"Run {run_id} completed in {duration_ms}ms")
        _reply_trace_link(repo, process, event, trace_ctx.trace_id)
        result = {"statusCode": 200, "run_id": str(run_id)}

        web_request_id = event.get("web_request_id")
        if web_request_id:
            result["web_response"] = event.get("_web_response") or {"status": 204, "headers": {}, "body": ""}

        return result

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)

        cost = _estimate_cost(run.model_version or "", run.tokens_in, run.tokens_out)
        run.cost_usd = cost

        # Preserve THROTTLED status set by execute_process
        final_status = run.status if run.status == RunStatus.THROTTLED else RunStatus.FAILED
        repo.complete_run(
            run.id,
            status=final_status,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=cost,
            duration_ms=duration_ms,
            model_version=run.model_version,
            error=str(e)[:4000],
            snapshot=run.snapshot,
        )
        _log_run_completion_latency(run, process.name, duration_ms)

        _emit_lifecycle_message(repo, process, {
            "type": "process:run:failed",
            "run_id": str(run.id),
            "process_id": str(process.id),
            "process_name": process.name,
            "error": str(e)[:1000],
        })

        alert_type = "process:run:failed"
        alert_severity = "warning"
        alert_meta: dict[str, Any] = {
            "process_id": str(process.id),
            "process_name": process.name,
            "run_id": str(run.id),
            "duration_ms": duration_ms,
        }

        # Detect context-overflow specifically so operators can act on it.
        error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if error_code:
            error_msg = str(e).lower()
            if error_code == "ValidationException" and (
                "token" in error_msg or "too long" in error_msg or "context" in error_msg or "input" in error_msg
            ):
                alert_type = "process:context_overflow"
                alert_severity = "critical"
                alert_meta["tokens_in"] = run.tokens_in
                alert_meta["tokens_out"] = run.tokens_out
                alert_meta["model"] = run.model_version or ""

        try:
            repo.create_alert(
                severity=alert_severity,
                alert_type=alert_type,
                source="executor",
                message=f"Run failed for '{process.name}': {str(e)[:500]}",
                metadata=alert_meta,
            )
        except Exception:
            logger.debug("Could not create alert for failed run %s", run.id)

        # Notify parent process via spawn channel
        _exit_code = 3 if final_status == RunStatus.THROTTLED else 1
        _notify_parent_on_exit(
            repo, process, run,
            exit_code=_exit_code, duration_ms=duration_ms, error=str(e),
        )

        # Retry logic — respect out-of-band status changes
        # Re-fetch to get current mode and status (mode may have changed during execution)
        current = repo.get_process(process.id)
        if current and current.status in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
            pass  # someone disabled/suspended it while running
        elif current and current.mode.value == "daemon":
            # Circuit breaker: suspend daemon after consecutive failures
            if _daemon_should_suspend(repo, process):
                repo.update_process_status(process.id, ProcessStatus.SUSPENDED)
                logger.error(
                    "Daemon %s suspended after consecutive failures (run %s)",
                    process.name,
                    run.id,
                )
                try:
                    repo.create_alert(
                        severity="critical",
                        alert_type="process:daemon_suspended",
                        source="executor",
                        message=f"Daemon '{process.name}' suspended after consecutive failures: {str(e)[:300]}",
                        metadata={
                            "process_id": str(process.id),
                            "process_name": process.name,
                            "run_id": str(run.id),
                            "error": str(e)[:500],
                        },
                    )
                except Exception:
                    logger.debug("Could not create suspension alert for %s", process.name)
            else:
                next_status = (
                    ProcessStatus.RUNNABLE
                    if repo.has_pending_deliveries(process.id)
                    else ProcessStatus.WAITING
                )
                repo.update_process_status(process.id, next_status)
                logger.warning(
                    "Daemon process %s failed run %s but remains %s",
                    process.name,
                    run.id,
                    next_status.value,
                )
        elif process.retry_count < process.max_retries:
            repo.increment_retry(process.id)
            repo.update_process_status(process.id, ProcessStatus.RUNNABLE)
        else:
            repo.update_process_status(process.id, ProcessStatus.DISABLED)

        logger.error(f"Run {run_id} failed: {e}", exc_info=True)
        result = {"statusCode": 500, "error": str(e)}
        web_request_id = event.get("web_request_id")
        if web_request_id:
            result["web_response"] = {"status": 502, "headers": {}, "body": json.dumps({"error": str(e)[:1000]})}
        return result


def _extract_web_response(vt: VariableTable, event_data: dict) -> None:
    web_request_id = event_data.get("web_request_id")
    if not web_request_id:
        return
    web_cap = vt.get("web")
    if web_cap is not None and hasattr(web_cap, "get_pending_response"):
        resp = web_cap.get_pending_response(web_request_id)
        if resp:
            event_data["_web_response"] = resp


def _execute_python_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: ExecutorConfig,
    repo: Repository,
    *,
    trace_id: UUID | None = None,
) -> Run:
    """Execute process by running resolved content as Python in the sandbox."""
    from cogos.files.references import extract_file_references
    from cogos.files.store import FileStore

    file_store = FileStore(repo)

    # For Python executor, resolve @{file-key} references by reading raw content
    # (no headers/decoration like the LLM context engine adds).
    content = process.content or ""
    refs = extract_file_references(content)
    if len(refs) == 1 and content.strip() == f"@{{{refs[0]}}}":
        # Entire content is a single file reference — use raw file content
        code = file_store.get_content(refs[0])
    else:
        # Inline refs — expand them in place
        import re
        def _replace(match):
            key = match.group(1).strip()
            return file_store.get_content(key) or f"# [not found: {key}]"
        code = re.sub(r"@\{([^{}\n]+)\}", _replace, content)

    if not code:
        run.result = {"output": "(no content to execute)"}
        return run

    # Set up sandbox with capability proxies — same as LLM path
    vt = VariableTable()
    _setup_capability_proxies(vt, process, repo, run_id=run.id, trace_id=trace_id)

    # Inject event payload as a variable
    vt.set("event", event_data)

    sandbox = SandboxExecutor(vt)
    result = sandbox.execute(code)

    run.result = {"output": result}
    run.tokens_in = 0
    run.tokens_out = 0
    run.scope_log = sandbox.scope_log
    _extract_web_response(vt, event_data)

    # Detect sandbox crash and create alert so failures aren't silent
    if sandbox.error:
        try:
            repo.create_alert(
                severity="critical",
                alert_type="process:sandbox_crash",
                source="executor",
                message=f"Python sandbox crashed for '{process.name}': {sandbox.error[:500]}",
                metadata={
                    "process_id": str(process.id),
                    "process_name": process.name,
                    "run_id": str(run.id),
                },
            )
        except Exception:
            logger.debug("Could not create sandbox crash alert for %s", process.name)

    return run


def _publish_io(repo, process, channel_name: str, text: str) -> None:
    """Publish text to a named channel if it exists."""
    if not text or not text.strip():
        return
    try:
        ch = repo.get_channel_by_name(channel_name)
        if ch:
            repo.append_channel_message(ChannelMessage(
                channel=ch.id,
                sender_process=process.id,
                payload={"text": text, "process": process.name},
            ))
    except Exception:
        logger.debug("Failed to publish to %s", channel_name, exc_info=True)


def _publish_process_io(repo, process, stream: str, text: str) -> None:
    """Publish to process:<name>:<stream>, coglet alias io:<stream>:<name>, and optionally io:<stream>."""
    _publish_io(repo, process, f"process:{process.name}:{stream}", text)
    _publish_io(repo, process, f"io:{stream}:{process.name}", text)
    if process.tty:
        _publish_io(repo, process, f"io:{stream}", text)


def execute_process(
    process: Process,
    event_data: dict,
    run: Run,
    config: ExecutorConfig,
    repo: Repository,
    *,
    trace_id: UUID | None = None,
) -> Run:
    """Execute a process run — via runtime converse loop (LLM) or direct Python sandbox."""
    if process.executor == "python":
        return _execute_python_process(process, event_data, run, config, repo, trace_id=trace_id)

    from cogos.executor.llm_client import LLMClient
    runtime = _get_runtime()

    def _on_bedrock_fallback(error_code: str, model_id: str) -> None:
        try:
            repo.create_alert(
                severity="warning",
                alert_type="llm:bedrock_fallback",
                source="executor",
                message=f"Bedrock {error_code} for {model_id}, using Anthropic API fallback",
                metadata={"error_code": error_code, "model_id": model_id, "process": process.name},
            )
        except Exception:
            logger.debug("Could not create bedrock fallback alert")

    llm = LLMClient(runtime=runtime, region=config.region, provider=config.llm_provider, secrets_provider=runtime.get_secrets_provider(), on_fallback=_on_bedrock_fallback)

    # Build system prompt using the shared ContextEngine
    from cogos.files.context_engine import ContextEngine
    from cogos.files.store import FileStore
    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)
    system_prompt = ctx.generate_full_prompt(process)

    if not system_prompt:
        system_prompt = "You are a CogOS process. Follow your instructions and use capabilities to accomplish your task."

    system = [{"text": system_prompt}]
    model_id = process.model or config.default_model
    run.model_version = model_id
    prompt_fingerprint = build_prompt_fingerprint(system_prompt, model_id, TOOL_CONFIG)
    session_store = SessionStore(repo)
    session = session_store.resolve_session(process, event_data, run.id)
    loaded_checkpoint = session_store.load_checkpoint(
        session,
        prompt_fingerprint=prompt_fingerprint,
        model_id=model_id,
    )
    checkpoint_key = session.checkpoint_key if session.resume_enabled else None
    resume_skipped_reason = loaded_checkpoint.resume_skipped_reason
    session_store.write_manifest(
        session,
        latest_run_id=run.id,
        checkpoint_key=checkpoint_key,
    )

    # Build user message from the triggering event only. Process instructions
    # already live in the system prompt, including any `@{file-key}` refs.
    user_text = ""
    web_request = event_data.get("web_request")
    if web_request:
        user_text += f"Incoming web request:\n{json.dumps(web_request, indent=2)}\n"
    if event_data.get("payload"):
        user_text += f"Message payload: {json.dumps(event_data['payload'], indent=2)}\n"
    if not user_text.strip():
        user_text = "Execute your task."

    # Inject pending cog:from messages into context (parent cog guidance)
    cog_from_msgs = _read_cog_from_messages(repo, process)
    if cog_from_msgs:
        user_text += "\n\n--- Messages from your cog ---\n"
        for msg in cog_from_msgs:
            payload = msg.payload
            if isinstance(payload, dict) and "text" in payload:
                user_text += f"\n{payload['text']}\n"
            else:
                user_text += f"\n{json.dumps(payload, indent=2)}\n"

    user_message = {"role": "user", "content": [{"text": user_text}]}

    messages = list(loaded_checkpoint.messages)
    messages.append(user_message)
    session_store.write_trigger(session, event_data=event_data, user_message=user_message)

    # Set up sandbox with capability proxies
    vt = VariableTable()
    _setup_capability_proxies(vt, process, repo, run_id=run.id, trace_id=trace_id)
    sandbox = SandboxExecutor(vt)

    total_input_tokens = 0
    total_output_tokens = 0
    turns_executed = 0
    tool_turns = 0
    tool_calls = 0
    invalid_tool_calls = 0
    bedrock_total_ms = 0
    tool_total_ms = 0
    tool_latency_by_name: dict[str, int] = defaultdict(int)
    final_stop_reason = "end_turn"
    step_seq = 0

    def _record_step(step_type: str, payload: dict[str, Any], *, refresh_checkpoint: bool) -> None:
        nonlocal step_seq, checkpoint_key, resume_skipped_reason
        step_seq += 1
        session_store.write_step(session, seq=step_seq, step_type=step_type, payload=payload)
        if not refresh_checkpoint:
            return
        checkpoint_result = session_store.update_checkpoint(
            session,
            messages=messages,
            model_id=model_id,
            prompt_fingerprint=prompt_fingerprint,
            last_completed_step=step_seq,
            source_run_id=run.id,
        )
        checkpoint_key = checkpoint_result.checkpoint_key
        if checkpoint_result.resume_disabled_reason is not None:
            resume_skipped_reason = checkpoint_result.resume_disabled_reason

    _record_step(
        "trigger_loaded",
        {
            "message": user_message,
            "resumed": loaded_checkpoint.resumed,
            "resumed_from_run_id": loaded_checkpoint.resumed_from_run_id,
            "resume_skipped_reason": loaded_checkpoint.resume_skipped_reason,
        },
        refresh_checkpoint=True,
    )

    turn_span = None
    try:
        for _turn in range(config.max_turns):
            turn_number = _turn + 1

            from cogos.trace import current_trace
            trace_ctx = current_trace()
            turn_span = None
            if trace_ctx:
                turn_span = trace_ctx.start_span(
                    f"llm_turn:{turn_number}",
                    metadata={"model": model_id},
                )
                turn_span.__enter__()

            kwargs: dict[str, Any] = {
                "modelId": model_id,
                "messages": messages,
                "system": system,
                "toolConfig": TOOL_CONFIG,
            }

            bedrock_started = time.monotonic()
            response = llm.converse(**kwargs)
            bedrock_latency_ms = int((time.monotonic() - bedrock_started) * 1000)
            turns_executed += 1
            bedrock_total_ms += bedrock_latency_ms
            output_message, invalid_tool_names = _sanitize_tool_use_message(
                response["output"]["message"],
                run_id=run.id,
                process_name=process.name,
                turn_number=turn_number,
            )
            messages.append(output_message)

            usage = response.get("usage", {})
            total_input_tokens += usage.get("inputTokens", 0)
            total_output_tokens += usage.get("outputTokens", 0)

            stop_reason = response.get("stopReason", "end_turn")
            final_stop_reason = stop_reason
            logger.info(
                "CogOS latency bedrock_turn=%sms run=%s process=%s turn=%s stop_reason=%s "
                "input_tokens=%s output_tokens=%s",
                bedrock_latency_ms,
                run.id,
                process.name,
                turn_number,
                stop_reason,
                usage.get("inputTokens", 0),
                usage.get("outputTokens", 0),
            )
            _record_step(
                "assistant_message",
                {
                    "turn_number": turn_number,
                    "message": output_message,
                    "stop_reason": stop_reason,
                    "input_tokens": usage.get("inputTokens", 0),
                    "output_tokens": usage.get("outputTokens", 0),
                },
                refresh_checkpoint=True,
            )

            if stop_reason == "tool_use":
                tool_turns += 1
                # Publish any assistant text blocks to stdout (thinking alongside tool calls)
                for block in output_message.get("content", []):
                    if isinstance(block, dict) and "text" in block:
                        _publish_process_io(repo, process, "stdout", block["text"])
                tool_results = []
                tool_idx = 0
                for block in output_message.get("content", []):
                    if "toolUse" not in block:
                        continue
                    tool_use = block["toolUse"]
                    tool_use_id = tool_use.get("toolUseId", "")
                    tool_name = tool_use.get("name", "")
                    tool_input = tool_use.get("input", {})
                    invalid_tool_name = invalid_tool_names.get(tool_use_id)
                    if invalid_tool_name is not None:
                        invalid_tool_calls += 1
                        tool_calls += 1
                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use_id,
                                "content": [{
                                    "text": (
                                        f"Error: invalid tool name '{invalid_tool_name}'. "
                                        f"Valid tools: {', '.join(sorted(SUPPORTED_TOOL_NAMES))}."
                                    ),
                                }],
                            }
                        })
                        continue
                    tool_started = time.monotonic()

                    if tool_name == "search":
                        result = _handle_search(tool_input, process, repo)
                    elif tool_name == "run_code":
                        result = sandbox.execute(tool_input.get("code", ""))
                        # Publish run_code output to process io channels
                        if result and result != "(no output)":
                            _publish_process_io(repo, process, "stdout", result)
                    else:
                        result = f"Unknown tool: {tool_name}"

                    tool_latency_ms = int((time.monotonic() - tool_started) * 1000)
                    tool_calls += 1
                    tool_total_ms += tool_latency_ms
                    tool_latency_by_name[tool_name] += tool_latency_ms
                    logger.info(
                        "CogOS latency tool=%sms run=%s process=%s turn=%s tool=%s",
                        tool_latency_ms,
                        run.id,
                        process.name,
                        turn_number,
                        tool_name,
                    )
                    context_result = _spill_tool_result(
                        result,
                        file_store=file_store,
                        run_id=run.id,
                        turn=turn_number,
                        tool_idx=tool_idx,
                    )
                    tool_idx += 1
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"text": context_result}],
                        }
                    })
                tool_result_message = {"role": "user", "content": tool_results}
                messages.append(tool_result_message)
                _record_step(
                    "tool_results_appended",
                    {
                        "turn_number": turn_number,
                        "message": tool_result_message,
                    },
                    refresh_checkpoint=True,
                )
                if turn_span:
                    turn_span.__exit__(None, None, None)
                continue

            # Publish final assistant commentary to process stderr
            for block in output_message.get("content", []):
                if isinstance(block, dict) and "text" in block:
                    _publish_process_io(repo, process, "stderr", block["text"])
            if turn_span:
                turn_span.__exit__(None, None, None)
            break
        else:
            final_stop_reason = "max_turns"

        run.tokens_in = total_input_tokens
        run.tokens_out = total_output_tokens
        run.scope_log = sandbox.scope_log
        _extract_web_response(vt, event_data)
        _record_step(
            "final_stop",
            {
                "status": RunStatus.COMPLETED.value,
                "final_stop_reason": final_stop_reason,
                "tokens_in": total_input_tokens,
                "tokens_out": total_output_tokens,
            },
            refresh_checkpoint=True,
        )
        run.snapshot = session_store.finalize_run(
            session,
            status=RunStatus.COMPLETED.value,
            resumed=loaded_checkpoint.resumed,
            resumed_from_run_id=loaded_checkpoint.resumed_from_run_id,
            resume_skipped_reason=resume_skipped_reason,
            final_stop_reason=final_stop_reason,
            error=None,
            last_completed_step=step_seq,
            message_count=len(messages),
            checkpoint_key=checkpoint_key,
        )
        logger.info(
            "CogOS execution breakdown run=%s process=%s model=%s turns=%s final_stop_reason=%s "
            "bedrock_calls=%s tool_turns=%s tool_calls=%s invalid_tool_calls=%s "
            "bedrock_total_ms=%s tool_total_ms=%s "
            "search_ms=%s run_code_ms=%s tokens_in=%s tokens_out=%s",
            run.id,
            process.name,
            model_id,
            turns_executed,
            final_stop_reason,
            turns_executed,
            tool_turns,
            tool_calls,
            invalid_tool_calls,
            bedrock_total_ms,
            tool_total_ms,
            tool_latency_by_name.get("search", 0),
            tool_latency_by_name.get("run_code", 0),
            total_input_tokens,
            total_output_tokens,
        )
        return run
    except Exception as exc:
        if turn_span:
            turn_span.__exit__(type(exc), exc, exc.__traceback__)
            turn_span = None
        _publish_process_io(repo, process, "stderr", f"[{process.name}] {exc}")
        # Detect throttling so dispatcher can apply cooldown
        exc_str = str(exc)
        if "ThrottlingException" in exc_str or "Too many tokens" in exc_str:
            run.status = RunStatus.THROTTLED
        run.tokens_in = total_input_tokens
        run.tokens_out = total_output_tokens
        run.scope_log = sandbox.scope_log
        final_stop_reason = "exception"
        _record_step(
            "final_stop",
            {
                "status": RunStatus.FAILED.value,
                "final_stop_reason": final_stop_reason,
                "error": str(exc)[:4000],
                "tokens_in": total_input_tokens,
                "tokens_out": total_output_tokens,
            },
            refresh_checkpoint=False,
        )
        run.snapshot = session_store.finalize_run(
            session,
            status=RunStatus.FAILED.value,
            resumed=loaded_checkpoint.resumed,
            resumed_from_run_id=loaded_checkpoint.resumed_from_run_id,
            resume_skipped_reason=resume_skipped_reason,
            final_stop_reason=final_stop_reason,
            error=str(exc)[:4000],
            last_completed_step=step_seq,
            message_count=len(messages),
            checkpoint_key=checkpoint_key,
        )
        raise


def _sanitize_tool_use_message(
    output_message: dict[str, Any],
    *,
    run_id: UUID,
    process_name: str,
    turn_number: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    content = output_message.get("content", [])
    if not isinstance(content, list):
        return output_message, {}

    invalid_tool_names: dict[str, str] = {}
    sanitized_content: list[dict[str, Any]] = []

    for idx, block in enumerate(content):
        if not isinstance(block, dict):
            sanitized_content.append(block)
            continue
        tool_use = block.get("toolUse")
        if not isinstance(tool_use, dict):
            sanitized_content.append(block)
            continue

        tool_name = tool_use.get("name")
        if _is_supported_tool_name(tool_name):
            sanitized_content.append(block)
            continue

        raw_tool_use_id = tool_use.get("toolUseId")
        tool_use_id = raw_tool_use_id if isinstance(raw_tool_use_id, str) and raw_tool_use_id else f"invalid-tool-{turn_number}-{idx}"
        invalid_tool_name = str(tool_name) if tool_name is not None else "<missing>"
        invalid_tool_names[tool_use_id] = invalid_tool_name
        logger.warning(
            "CogOS suppressed invalid tool request run=%s process=%s turn=%s tool=%r tool_use_id=%r",
            run_id,
            process_name,
            turn_number,
            tool_name,
            raw_tool_use_id,
        )
        sanitized_content.append({
            "toolUse": {
                "toolUseId": tool_use_id,
                "name": TOOL_NAME_PLACEHOLDER,
                "input": {"query": f"invalid tool placeholder for {invalid_tool_name}"},
            }
        })

    if not invalid_tool_names:
        return output_message, {}

    sanitized_message = dict(output_message)
    sanitized_message["content"] = sanitized_content
    return sanitized_message, invalid_tool_names


def _is_supported_tool_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and VALID_TOOL_NAME_RE.fullmatch(name) is not None
        and name in SUPPORTED_TOOL_NAMES
    )



_DAEMON_CONSECUTIVE_FAILURE_LIMIT = 3


def _daemon_should_suspend(repo: Repository, process: Process) -> bool:
    """Check if a daemon has hit the consecutive failure limit.

    Looks at the most recent runs for this process and returns True if
    the last N runs (including the current one that just failed) all failed.
    """
    recent_runs = repo.list_runs(process_id=process.id, limit=_DAEMON_CONSECUTIVE_FAILURE_LIMIT)
    if len(recent_runs) < _DAEMON_CONSECUTIVE_FAILURE_LIMIT:
        return False
    return all(r.status in (RunStatus.FAILED, RunStatus.THROTTLED) for r in recent_runs)


def _log_run_completion_latency(run: Run, process_name: str, duration_ms: int) -> None:
    if not run.created_at:
        return
    created_at = run.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    completed_at = datetime.now(UTC)
    latency_ms = int((completed_at - created_at).total_seconds() * 1000)
    logger.info(
        "CogOS latency run->completion=%sms run=%s process=%s executor_duration_ms=%s",
        latency_ms,
        run.id,
        process_name,
        duration_ms,
    )


def _notify_parent_on_exit(
    repo: Repository,
    process: Process,
    run: Run,
    *,
    exit_code: int,
    duration_ms: int,
    error: str | None = None,
) -> None:
    """Notify the parent process that this child exited (success or failure)."""
    if not process.parent_process:
        return
    try:
        ch_name = f"spawn:{process.id}\u2192{process.parent_process}"
        ch = repo.get_channel_by_name(ch_name)
        if ch:
            repo.append_channel_message(ChannelMessage(
                channel=ch.id,
                sender_process=process.id,
                payload={
                    "type": "child:exited",
                    "exit_code": exit_code,
                    "process_name": process.name,
                    "process_id": str(process.id),
                    "run_id": str(run.id),
                    "duration_ms": duration_ms,
                    "error": error[:1000] if error else None,
                    "result": run.result,
                },
            ))
            logger.info(
                "Notified parent %s of child %s exit (code=%s)",
                process.parent_process, process.name, exit_code,
            )
    except Exception:
        logger.warning(
            "Failed to notify parent of child %s exit",
            process.name, exc_info=True,
        )


def _emit_lifecycle_message(repo: Repository, process: Process, payload: dict) -> None:
    """Write a lifecycle event to the implicit process channel."""
    try:
        implicit_ch = repo.get_channel_by_name(f"process:{process.name}")
        if implicit_ch:
            repo.append_channel_message(ChannelMessage(
                channel=implicit_ch.id,
                sender_process=process.id,
                payload=payload,
            ))
    except Exception:
        logger.warning("Failed to emit lifecycle message for process %s", process.name, exc_info=True)


def _read_cog_from_messages(repo: Repository, process: Process) -> list:
    """Read pending messages from the cog:from channel for this process."""
    ch = repo.get_channel_by_name(f"cog:from:{process.name}")
    if ch is None:
        return []
    return repo.list_channel_messages(ch.id, limit=50)


def _handle_search(tool_input: dict, process: Process, repo: Repository) -> str:
    """Search capabilities available to this process."""
    query = tool_input.get("query", "").lower().strip()
    if not query:
        # Empty query: list all capabilities bound to this process
        pcs = repo.list_process_capabilities(process.id)
        caps = []
        for pc in pcs:
            cap = repo.get_capability(pc.capability)
            if cap and cap.enabled:
                caps.append(cap)
        if not caps:
            return (
                "No capabilities bound to this process. "
                "Your capabilities are already available as top-level objects — "
                "use help() on them (e.g. discord.help()) or dir() to see their methods."
            )
    else:
        caps = repo.search_capabilities(query, process_id=process.id)
        if not caps:
            caps = repo.search_capabilities(query)
    limit = min(tool_input.get("limit", 5), 20)
    caps = caps[:limit]
    results = []
    for cap in caps:
        results.append({
            "name": cap.name,
            "description": cap.description,
            "instructions": cap.instructions,
        })
    return json.dumps(results, indent=2) if results else "No capabilities found matching query."


def _wrap_capability_with_tracing(instance, namespace: str):
    """Wrap capability methods to automatically create trace spans."""
    from cogos.trace import current_trace

    class TracingProxy:
        def __init__(self, target, ns):
            object.__setattr__(self, '_target', target)
            object.__setattr__(self, '_ns', ns)

        def __getattr__(self, name):
            attr = getattr(self._target, name)
            if not callable(attr) or name.startswith('_'):
                return attr
            ns = self._ns

            def traced_method(*args, **kwargs):
                ctx = current_trace()
                if ctx:
                    with ctx.start_span(f"tool:{ns}.{name}"):
                        return attr(*args, **kwargs)
                return attr(*args, **kwargs)
            return traced_method

        def help(self):
            return self._target.help() if hasattr(self._target, 'help') else str(self._target)

    return TracingProxy(instance, namespace)


def _setup_capability_proxies(vt: VariableTable, process: Process, repo: Repository, *, run_id: UUID | None = None, trace_id: UUID | None = None) -> None:
    """Inject capability instances into the variable table.

    Only capabilities explicitly bound to the process via ProcessCapability
    are injected. Applies scope from ProcessCapability.config when present.
    No ambient/unconditional capabilities — if a process needs files, procs,
    or events, it must have a binding.
    """
    import importlib
    import inspect

    vt.set("print", print)

    pcs = repo.list_process_capabilities(process.id)
    for pc in pcs:
        cap_model = repo.get_capability(pc.capability)
        if cap_model is None or not cap_model.enabled:
            continue

        # Determine namespace — use grant name from ProcessCapability
        ns = pc.name or (cap_model.name.split("/")[0] if "/" in cap_model.name else cap_model.name)
        logger.info("Injecting capability %s as '%s' (handler=%s)", cap_model.name, ns, cap_model.handler)

        # Load the handler class
        handler_path = cap_model.handler
        if not handler_path:
            continue
        if ":" in handler_path:
            mod_path, attr_name = handler_path.rsplit(":", 1)
        elif "." in handler_path:
            mod_path, attr_name = handler_path.rsplit(".", 1)
        else:
            continue

        try:
            mod = importlib.import_module(mod_path)
            handler_cls = getattr(mod, attr_name)
            if not inspect.isclass(handler_cls):
                vt.set(ns, handler_cls)
                continue
            init_params = inspect.signature(handler_cls.__init__).parameters
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in init_params.values())
            kwargs = {}
            if "run_id" in init_params or has_var_keyword:
                kwargs["run_id"] = run_id
            if "trace_id" in init_params or has_var_keyword:
                kwargs["trace_id"] = trace_id
            if "runtime" in init_params or has_var_keyword:
                kwargs["runtime"] = _get_runtime()
            if "secrets_provider" in init_params or has_var_keyword:
                kwargs["secrets_provider"] = _get_runtime().get_secrets_provider()
            instance = handler_cls(repo, process.id, **kwargs)
            # Apply scope from config if present
            if pc.config:
                instance = instance.scope(**pc.config)
            instance = _wrap_capability_with_tracing(instance, ns)
            vt.set(ns, instance)
        except (ImportError, AttributeError) as exc:
            logger.warning("Could not load capability %s (%s): %s", cap_model.name, handler_path, exc)

    # Expose a summary of what's available with method signatures so the model
    # doesn't waste turns probing with dir()/help()/search.
    cap_entries = []
    for name in sorted(k for k in vt.as_dict() if k != "print"):
        obj = vt.get(name)
        if hasattr(obj, "help") and callable(obj.help):
            cap_entries.append(f"{name}: {obj.help()}")
        else:
            cap_entries.append(name)
    vt.set("__capabilities__", "\n\n".join(cap_entries))

    # Create implicit process channel and per-process IO channels if they don't exist
    try:
        from cogos.db.models import Channel, ChannelType

        for suffix in ("", ":stdout", ":stderr", ":stdin"):
            ch_name = f"process:{process.name}{suffix}"
            if repo.get_channel_by_name(ch_name) is None:
                ch = Channel(
                    name=ch_name,
                    owner_process=process.id,
                    channel_type=ChannelType.IMPLICIT,
                )
                repo.upsert_channel(ch)
    except Exception as exc:
        logger.warning("Could not create implicit channels for process %s: %s", process.name, exc)
