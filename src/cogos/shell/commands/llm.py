"""LLM execution — llm, source, . commands."""

from __future__ import annotations

import json
import time
from typing import Any

from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor.handler import get_config
from cogos.files.store import FileStore
from cogos.runtime.local import run_and_complete
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.files import _resolve_path

_DIM = "\033[90m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"


def _print_assistant_turn(turn_num: int, output_message: dict, verbose: bool) -> str | None:
    """Print an assistant turn. Returns the final text if this is a text-only response."""
    content = output_message.get("content", [])
    text_parts = []
    tool_uses = []

    for block in content:
        if not isinstance(block, dict):
            continue
        if "text" in block:
            text_parts.append(block["text"])
        elif "toolUse" in block:
            tool_uses.append(block["toolUse"])

    if verbose:
        print(f"{_DIM}── turn {turn_num} ──{_RESET}")

    if text_parts:
        text = "\n".join(text_parts)
        if verbose or not tool_uses:
            print(text)

    if verbose:
        for tu in tool_uses:
            name = tu.get("name", "?")
            inp = tu.get("input", {})
            if name == "run_code":
                code = inp.get("code", "")
                if len(code) > 500:
                    code = code[:500] + "..."
                print(f"  {_DIM}→ run_code:{_RESET}")
                for line in code.split("\n"):
                    print(f"    {_DIM}{line}{_RESET}")
            elif name == "search":
                print(f"  {_DIM}→ search({inp.get('query', '')}){_RESET}")
            else:
                print(f"  {_DIM}→ {name}({json.dumps(inp, default=str)[:200]}){_RESET}")

    return "\n".join(text_parts) if text_parts else None


def _print_tool_results(tool_results: list[dict], tool_names: list[str], verbose: bool) -> None:
    """Print tool result output. Always shows run_code stdout; verbose shows all."""
    for tr_block, tool_name in zip(tool_results, tool_names):
        tr = tr_block.get("toolResult", {})
        result_text = ""
        for c in tr.get("content", []):
            if "text" in c:
                result_text = c["text"]
        if not result_text:
            continue
        if verbose:
            if len(result_text) > 500:
                result_text = result_text[:500] + "..."
            print(f"  {_DIM}← {result_text}{_RESET}")
        elif tool_name == "run_code" and result_text.strip():
            # Always show run_code stdout — it's program output
            print(result_text)


def _execute_prompt(state: ShellState, content: str, *, verbose: bool = False) -> str:
    """Create a temp process, execute the prompt, return output."""
    ts = int(time.time())
    proc_name = f"shell-{ts}"

    process = Process(
        name=proc_name,
        mode=ProcessMode.ONE_SHOT,
        content=content,
        runner="local",
        status=ProcessStatus.RUNNING,
    )
    state.repo.upsert_process(process)

    run_obj = Run(process=process.id, status=RunStatus.RUNNING)
    state.repo.create_run(run_obj)

    final_text = ""

    def _verbose_executor(
        process: Any, event_data: Any, run: Any, config: Any, repo: Any, **kwargs: Any,
    ) -> Any:
        """Wraps execute_process to print turn-by-turn output."""
        nonlocal final_text
        from cogos.executor.handler import (
            TOOL_CONFIG,
            SandboxExecutor,
            VariableTable,
            _handle_search,
            _sanitize_tool_use_message,
            _setup_capability_proxies,
            build_prompt_fingerprint,
        )
        from cogos.executor.session_store import SessionStore
        from cogos.files.context_engine import ContextEngine

        import boto3
        from botocore.config import Config as BotoConfig

        bedrock = kwargs.get("bedrock_client") or boto3.client(
            "bedrock-runtime",
            region_name=config.region,
            config=BotoConfig(retries={"max_attempts": 12, "mode": "adaptive"}),
        )

        file_store = FileStore(repo)
        ctx = ContextEngine(file_store)
        system_prompt = ctx.generate_full_prompt(process) or (
            "You are a CogOS process. Follow your instructions and use capabilities to accomplish your task."
        )

        system = [{"text": system_prompt}]
        model_id = process.model or config.default_model

        user_text = ""
        if event_data.get("payload"):
            user_text += f"Message payload: {json.dumps(event_data['payload'], indent=2)}\n"
        if not user_text.strip():
            user_text = "Execute your task."
        user_message = {"role": "user", "content": [{"text": user_text}]}
        messages = [user_message]

        vt = VariableTable()
        _setup_capability_proxies(vt, process, repo, run_id=run.id)
        sandbox = SandboxExecutor(vt)

        total_in = 0
        total_out = 0
        turns = 0

        if verbose:
            print(f"{_DIM}model: {model_id}{_RESET}")
            print(f"{_CYAN}prompt:{_RESET} {content[:200]}{'...' if len(content) > 200 else ''}")
            print()

        for _turn in range(config.max_turns):
            turn_start = time.monotonic()
            response = bedrock.converse(
                modelId=model_id,
                messages=messages,
                system=system,
                toolConfig=TOOL_CONFIG,
            )
            bedrock_ms = int((time.monotonic() - turn_start) * 1000)
            turns += 1

            output_message, invalid_names = _sanitize_tool_use_message(
                response["output"]["message"],
                run_id=run.id, process_name=process.name, turn_number=turns,
            )
            messages.append(output_message)

            usage = response.get("usage", {})
            total_in += usage.get("inputTokens", 0)
            total_out += usage.get("outputTokens", 0)

            stop_reason = response.get("stopReason", "end_turn")

            if verbose:
                print(f"{_DIM}  [{bedrock_ms}ms, {usage.get('inputTokens', 0)}→{usage.get('outputTokens', 0)} tokens]{_RESET}")

            text = _print_assistant_turn(turns, output_message, verbose)
            if text:
                final_text = text

            if stop_reason == "tool_use":
                tool_results = []
                tool_names_for_results = []
                for block in output_message.get("content", []):
                    if "toolUse" not in block:
                        continue
                    tu = block["toolUse"]
                    tool_use_id = tu.get("toolUseId", "")
                    tool_name = tu.get("name", "")
                    tool_input = tu.get("input", {})

                    invalid = invalid_names.get(tool_use_id)
                    if invalid is not None:
                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use_id,
                                "content": [{"text": f"Error: invalid tool name '{invalid}'."}],
                            }
                        })
                        tool_names_for_results.append(invalid)
                        continue

                    tool_start = time.monotonic()
                    if tool_name == "search":
                        result = _handle_search(tool_input, process, repo)
                    elif tool_name == "run_code":
                        result = sandbox.execute(tool_input.get("code", ""))
                    else:
                        result = f"Unknown tool: {tool_name}"
                    tool_ms = int((time.monotonic() - tool_start) * 1000)

                    if verbose:
                        print(f"{_DIM}  [{tool_name} {tool_ms}ms]{_RESET}")

                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tu["toolUseId"],
                            "content": [{"text": result}],
                        }
                    })
                    tool_names_for_results.append(tool_name)

                _print_tool_results(tool_results, tool_names_for_results, verbose)
                messages.append({"role": "user", "content": tool_results})
                continue

            break

        run.tokens_in = total_in
        run.tokens_out = total_out
        run.scope_log = sandbox.scope_log
        return run

    config = get_config()

    if verbose:
        run_obj = run_and_complete(
            process, {}, run_obj, config, state.repo,
            execute_fn=_verbose_executor,
            bedrock_client=state.bedrock_client,
        )
    else:
        # Use default executor, then extract text from session
        run_obj = run_and_complete(
            process, {}, run_obj, config, state.repo,
            execute_fn=_verbose_executor,  # reuse to capture final_text
            bedrock_client=state.bedrock_client,
        )

    state.repo.update_process_status(process.id, ProcessStatus.COMPLETED)

    lines = []
    if not verbose:
        # In non-verbose mode, we already printed the final text via _print_assistant_turn
        # but only the last text response. If nothing was printed, show a message.
        if not final_text:
            if run_obj.status == RunStatus.FAILED:
                lines.append(f"{_RED}Error: {run_obj.error}{_RESET}")
            else:
                lines.append(f"{_DIM}(no text response){_RESET}")

    lines.append(
        f"{_DIM}tokens: {run_obj.tokens_in or 0} in, {run_obj.tokens_out or 0} out"
        f" ({run_obj.duration_ms or 0}ms){_RESET}"
    )
    if run_obj.status == RunStatus.FAILED:
        lines.append(f"{_RED}Error: {run_obj.error}{_RESET}")
    return "\n".join(lines)


def _execute_interactive(state: ShellState, initial_content: str = "", *, verbose: bool = False) -> str:
    """Interactive multi-turn LLM session."""
    from prompt_toolkit import PromptSession

    session: PromptSession = PromptSession()
    lines = []

    if initial_content:
        lines.append(f"{_DIM}(loaded context: {len(initial_content)} chars){_RESET}")
        output = _execute_prompt(state, initial_content, verbose=verbose)
        lines.append(output)

    try:
        while True:
            try:
                user_input = session.prompt("llm> ")
            except EOFError:
                break
            if user_input.strip() in ("/exit", "exit", "quit"):
                break
            if not user_input.strip():
                continue
            output = _execute_prompt(state, user_input, verbose=verbose)
            lines.append(output)
    except KeyboardInterrupt:
        pass

    return "\n".join(lines) if lines else "(session ended)"


_HELP = """\
Usage: llm [options] [prompt]

Options:
  -f <file>   Use file content as prompt
  -i          Interactive multi-turn mode
  -v          Verbose: show full turn-by-turn transcript with tool use and timing
  --help      Show this help

Examples:
  llm what files exist?
  llm -f prompts/init.md
  llm -v explain the system architecture
  llm -i -f prompts/init.md
  source prompts/hello.md"""


def register(reg: CommandRegistry) -> None:

    @reg.register("llm", help="Run an LLM prompt: llm <text> | llm -f <file> | llm -i | llm -v")
    def llm(state: ShellState, args: list[str]) -> str:
        if not args:
            return _HELP

        if "--help" in args or "-h" in args:
            return _HELP

        interactive = "-i" in args
        verbose = "-v" in args or "--verbose" in args
        file_path = None
        prompt_parts = []

        i = 0
        while i < len(args):
            if args[i] in ("-i", "-v", "--verbose"):
                i += 1
            elif args[i] == "-f" and i + 1 < len(args):
                file_path = args[i + 1]
                i += 2
            else:
                prompt_parts.append(args[i])
                i += 1

        content = ""
        if file_path:
            key = _resolve_path(state, file_path)
            fs = FileStore(state.repo)
            file_content = fs.get_content(key)
            if file_content is None:
                return f"File not found: {file_path}"
            content = file_content

        if prompt_parts:
            inline = " ".join(prompt_parts)
            content = f"{content}\n\n{inline}" if content else inline

        if interactive:
            return _execute_interactive(state, content, verbose=verbose)

        if not content:
            return _HELP

        return _execute_prompt(state, content, verbose=verbose)

    @reg.register("source", aliases=["."], help="Execute a file as an LLM prompt")
    def source(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: source <file>"
        verbose = "-v" in args or "--verbose" in args
        file_args = [a for a in args if a not in ("-v", "--verbose")]
        key = _resolve_path(state, file_args[0])
        fs = FileStore(state.repo)
        content = fs.get_content(key)
        if content is None:
            return f"File not found: {file_args[0]}"
        return _execute_prompt(state, content, verbose=verbose)
