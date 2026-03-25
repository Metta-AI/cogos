"""Run commands — runs, run show."""

from __future__ import annotations

import json
from uuid import UUID

from cogos.shell.commands import CommandRegistry, ShellState


def register(reg: CommandRegistry) -> None:

    @reg.register("runs", help="List recent runs [--process <name>] [--limit N]")
    def runs(state: ShellState, args: list[str]) -> str:
        process_name = None
        limit = 20
        i = 0
        while i < len(args):
            if args[i] == "--process" and i + 1 < len(args):
                process_name = args[i + 1]
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            else:
                i += 1

        pid = None
        if process_name:
            p = state.repo.get_process_by_name(process_name)
            if p:
                pid = p.id

        run_list = state.repo.list_runs(process_id=pid, limit=limit)
        if not run_list:
            return "(no runs)"

        proc_cache: dict[str, str] = {}
        lines = [f"{'ID':<12} {'PROCESS':<20} {'STATUS':<12} {'TOKENS':>12} {'DURATION':>10}"]
        lines.append("-" * 70)
        for r in run_list:
            pkey = str(r.process)
            if pkey not in proc_cache:
                proc = state.repo.get_process(r.process)
                proc_cache[pkey] = proc.name if proc else pkey[:8]
            t_in = r.tokens_in if r.tokens_in is not None else 0
            t_out = r.tokens_out if r.tokens_out is not None else 0
            tokens = f"{t_in}/{t_out}"
            dur = f"{r.duration_ms if r.duration_ms is not None else 0}ms"
            lines.append(
                f"{str(r.id)[:12]} {proc_cache[pkey]:<20} {r.status.value:<12} {tokens:>12} {dur:>10}"
            )
        return "\n".join(lines)

    @reg.register("run", help="Run subcommands: run show <id>")
    def run_cmd(state: ShellState, args: list[str]) -> str:
        if not args or args[0] != "show" or len(args) < 2:
            return "Usage: run show <run-id>"

        try:
            run_id = UUID(args[1])
        except ValueError:
            return f"Invalid run ID: {args[1]}"

        r = state.repo.get_run(run_id)
        if not r:
            return f"Run not found: {args[1]}"

        data = r.model_dump(mode="json")
        lines = []
        for k, v in data.items():
            if v is not None:
                lines.append(f"  {k}: {json.dumps(v, default=str) if isinstance(v, (dict, list)) else v}")
        return "\n".join(lines)
