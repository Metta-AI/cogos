"""Process commands — ps, kill, spawn, top."""

from __future__ import annotations

import time

from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.shell.commands import CommandRegistry, ShellState

_STATUS_COLORS = {
    "running": "\033[32m",
    "runnable": "\033[33m",
    "waiting": "\033[33m",
    "blocked": "\033[31m",
    "suspended": "\033[31m",
    "disabled": "\033[31m",
    "completed": "\033[90m",
}
_RESET = "\033[0m"


def _format_process_table(procs: list[Process]) -> str:
    if not procs:
        return "(no processes)"
    lines = [f"{'NAME':<24} {'STATUS':<12} {'MODE':<10} {'RUNNER':<8} {'TTY':<5} {'PRI':>5}"]
    lines.append("-" * 68)
    for p in procs:
        color = _STATUS_COLORS.get(p.status.value, "")
        tty = "*" if p.tty else ""
        lines.append(
            f"{p.name:<24} {color}{p.status.value:<12}{_RESET} "
            f"{p.mode.value:<10} {p.runner:<8} {tty:<5} {p.priority:>5.1f}"
        )
    return "\n".join(lines)


def register(reg: CommandRegistry) -> None:

    @reg.register("ps", help="List processes (--all to include completed)")
    def ps(state: ShellState, args: list[str]) -> str:
        show_all = "--all" in args or "-a" in args
        procs = state.repo.list_processes()
        if not show_all:
            procs = [p for p in procs if p.status != ProcessStatus.COMPLETED]
        procs.sort(key=lambda p: (p.status != ProcessStatus.RUNNING, p.name))
        return _format_process_table(procs)

    @reg.register("kill", help="Kill a process (-9=force, -HUP=restart)")
    def kill(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: kill [-9|-HUP] <name>"

        signal = None
        name = args[0]
        if name.startswith("-"):
            signal = name
            if len(args) < 2:
                return "Usage: kill [-9|-HUP] <name>"
            name = args[1]

        p = state.repo.get_process_by_name(name)
        if not p:
            return f"kill: not found: {name}"

        if signal == "-HUP":
            state.repo.update_process_status(p.id, ProcessStatus.RUNNABLE)
            return f"Restarted: {name} (RUNNABLE)"
        elif signal == "-9":
            state.repo.update_process_status(p.id, ProcessStatus.DISABLED)
            return f"Force killed: {name} (DISABLED, context cleared)"
        else:
            state.repo.update_process_status(p.id, ProcessStatus.DISABLED)
            return f"Killed: {name} (DISABLED)"

    @reg.register("spawn", help="Create a new process")
    def spawn(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: spawn <name> [--content '...'] [--runner lambda|ecs] [--model ...]"

        name = args[0]
        content = ""
        runner = "lambda"
        model = None
        mode = "one_shot"
        priority = 0.0
        tty = False

        i = 1
        while i < len(args):
            if args[i] == "--content" and i + 1 < len(args):
                content = args[i + 1]
                i += 2
            elif args[i] == "--runner" and i + 1 < len(args):
                runner = args[i + 1]
                i += 2
            elif args[i] == "--model" and i + 1 < len(args):
                model = args[i + 1]
                i += 2
            elif args[i] == "--mode" and i + 1 < len(args):
                mode = args[i + 1]
                i += 2
            elif args[i] == "--priority" and i + 1 < len(args):
                priority = float(args[i + 1])
                i += 2
            elif args[i] == "--tty":
                tty = True
                i += 1
            else:
                i += 1

        p = Process(
            name=name,
            mode=ProcessMode(mode),
            content=content,
            runner=runner,
            model=model,
            priority=priority,
            status=ProcessStatus.RUNNABLE,
            tty=tty,
        )
        pid = state.repo.upsert_process(p)
        return f"Spawned: {name} ({pid})"

    @reg.register("top", help="Live-refreshing process view (ctrl+c to exit)")
    def top(state: ShellState, args: list[str]) -> str:
        try:
            while True:
                procs = state.repo.list_processes()
                procs = [p for p in procs if p.status != ProcessStatus.COMPLETED]
                procs.sort(key=lambda p: (p.status != ProcessStatus.RUNNING, p.name))
                print("\033[2J\033[H", end="")
                print(f"cogent: {state.cogent_name}  (ctrl+c to exit)\n")
                print(_format_process_table(procs))
                time.sleep(2)
        except KeyboardInterrupt:
            return ""
