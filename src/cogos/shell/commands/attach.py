"""Attach command — tail a process's stdout/stderr."""

from __future__ import annotations

import time

from cogos.db.models import ChannelMessage
from cogos.shell.commands import CommandRegistry, ShellState

_DIM = "\033[90m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_RESET = "\033[0m"


def register(reg: CommandRegistry) -> None:

    @reg.register("attach", help="Attach to a process: attach [-i] <name>")
    def attach(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: attach [-i] <name>"

        interactive = "-i" in args
        name_args = [a for a in args if a != "-i"]
        if not name_args:
            return "Usage: attach [-i] <name>"
        name = name_args[0]

        proc = state.repo.get_process_by_name(name)
        if not proc:
            return f"attach: not found: {name}"

        stdout_ch = state.repo.get_channel_by_name(f"process:{name}:stdout")
        stderr_ch = state.repo.get_channel_by_name(f"process:{name}:stderr")
        stdin_ch = state.repo.get_channel_by_name(f"process:{name}:stdin") if interactive else None

        if not stdout_ch and not stderr_ch:
            return f"attach: no io channels for {name}"

        # Start from now (don't replay history)
        stdout_cursor = None
        stderr_cursor = None
        if stdout_ch:
            msgs = state.repo.list_channel_messages(stdout_ch.id, limit=1)
            stdout_cursor = msgs[-1].created_at if msgs else None
        if stderr_ch:
            msgs = state.repo.list_channel_messages(stderr_ch.id, limit=1)
            stderr_cursor = msgs[-1].created_at if msgs else None

        print(f"{_DIM}Attached to {name} (ctrl+c to detach){_RESET}")

        try:
            while True:
                found = False
                if stdout_ch:
                    msgs = state.repo.list_channel_messages(stdout_ch.id, limit=50, since=stdout_cursor)
                    for m in msgs:
                        text = m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload)
                        if text:
                            print(f"{_GREEN}stdout{_RESET} {text}")
                        stdout_cursor = m.created_at
                        found = True
                if stderr_ch:
                    msgs = state.repo.list_channel_messages(stderr_ch.id, limit=50, since=stderr_cursor)
                    for m in msgs:
                        text = m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload)
                        if text:
                            print(f"{_RED}stderr{_RESET} {text}")
                        stderr_cursor = m.created_at
                        found = True

                if interactive and stdin_ch:
                    try:
                        import select
                        import sys
                        if select.select([sys.stdin], [], [], 0)[0]:
                            line = sys.stdin.readline().strip()
                            if line:
                                state.repo.append_channel_message(ChannelMessage(
                                    channel=stdin_ch.id, sender_process=None,
                                    payload={"text": line, "source": "shell"},
                                ))
                    except Exception:
                        pass

                if not found:
                    time.sleep(1)
        except KeyboardInterrupt:
            return f"{_DIM}Detached from {name}{_RESET}"
