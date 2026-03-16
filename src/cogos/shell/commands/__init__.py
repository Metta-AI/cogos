"""Command registry and dispatch for the CogOS shell."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ShellState:
    cogent_name: str
    repo: Any
    cwd: str  # current prefix, e.g. "prompts/" or "" for root
    bedrock_client: Any = None
    raw_line: str = ""  # raw input line for commands that need unparsed text
    stdin_channel: Any = None    # Channel object for io:stdin
    stdout_channel: Any = None   # Channel object for io:stdout
    stderr_channel: Any = None   # Channel object for io:stderr
    stdout_cursor: Any = None    # datetime of last-seen stdout message
    stderr_cursor: Any = None    # datetime of last-seen stderr message


CommandFn = Callable[[ShellState, list[str]], str | None]


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandFn] = {}
        self._aliases: dict[str, str] = {}
        self._help: dict[str, str] = {}

    def register(self, name: str, *, aliases: list[str] | None = None, help: str = ""):
        """Decorator to register a command function."""
        def decorator(fn: CommandFn) -> CommandFn:
            self._commands[name] = fn
            if help:
                self._help[name] = help
            elif fn.__doc__:
                self._help[name] = fn.__doc__.strip().split("\n")[0]
            for alias in (aliases or []):
                self._aliases[alias] = name
            return fn
        return decorator

    def dispatch(self, state: ShellState, line: str) -> str | None:
        """Parse and dispatch a command line. Returns output string, empty for no-op, None for exit."""
        line = line.strip()
        if not line:
            return ""

        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()

        cmd_name = parts[0]
        args = parts[1:]

        # Resolve alias
        cmd_name = self._aliases.get(cmd_name, cmd_name)

        fn = self._commands.get(cmd_name)
        if fn is None:
            return f"Unknown command: {parts[0]}. Type 'help' for available commands."

        state.raw_line = line
        result = fn(state, args)
        if result is None:
            return None
        return result or ""

    @property
    def command_names(self) -> list[str]:
        return sorted(set(list(self._commands.keys()) + list(self._aliases.keys())))

    def get_help(self, name: str) -> str | None:
        name = self._aliases.get(name, name)
        return self._help.get(name)

    def get_canonical(self, name: str) -> str | None:
        """Resolve alias to canonical name, or return name if it's a command."""
        name = self._aliases.get(name, name)
        return name if name in self._commands else None


def build_registry() -> CommandRegistry:
    """Build the full command registry with all command modules."""
    reg = CommandRegistry()

    from cogos.shell.commands.attach import register as register_attach
    from cogos.shell.commands.builtins import register as register_builtins
    from cogos.shell.commands.caps import register as register_caps
    from cogos.shell.commands.channels import register as register_channels
    from cogos.shell.commands.files import register as register_files
    from cogos.shell.commands.procs import register as register_procs
    from cogos.shell.commands.runs import register as register_runs

    register_files(reg)
    register_procs(reg)
    register_channels(reg)
    register_caps(reg)
    register_attach(reg)
    register_runs(reg)
    register_builtins(reg)

    try:
        from cogos.shell.commands.llm import register as register_llm
        register_llm(reg)
    except ImportError:
        pass

    return reg