"""Shell builtins — help, clear, exit, history."""

from __future__ import annotations

import os

from cogos.shell.commands import CommandRegistry, ShellState


def register(reg: CommandRegistry) -> None:

    @reg.register("help", help="Show available commands")
    def help_cmd(state: ShellState, args: list[str]) -> str:
        if args:
            name = args[0]
            h = reg.get_help(name)
            if h:
                return f"{name}: {h}"
            return f"No help for: {name}"
        lines = ["Available commands:", ""]
        for name in reg.command_names:
            canonical = reg.get_canonical(name)
            if canonical and canonical != name:
                continue  # skip aliases
            h = reg.get_help(name)
            if h is None:
                h = ""
            lines.append(f"  {name:<16} {h}")
        return "\n".join(lines)

    @reg.register("clear", help="Clear screen")
    def clear(state: ShellState, args: list[str]) -> str:
        os.system("clear" if os.name != "nt" else "cls")
        return ""

    @reg.register("history", help="Show command history [N]")
    def history_cmd(state: ShellState, args: list[str]) -> str:
        from cogos.files.store import FileStore
        fs = FileStore(state.repo)
        content = fs.get_content("home/root/.shell_history")
        if not content:
            return "(no history)"
        entries = [line for line in content.splitlines() if line]
        limit = 50
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                pass
        entries = entries[-limit:]
        lines = []
        for i, entry in enumerate(entries, 1):
            lines.append(f"  {i:4d}  {entry}")
        return "\n".join(lines)

    @reg.register("exit", aliases=["quit"], help="Exit the shell")
    def exit_cmd(state: ShellState, args: list[str]) -> str | None:
        return None
