"""Capability commands — cap ls, cap enable, cap disable."""

from __future__ import annotations

from cogos.shell.commands import CommandRegistry, ShellState


def register(reg: CommandRegistry) -> None:

    @reg.register("cap", help="Capability commands: cap ls | cap enable <name> | cap disable <name>")
    def cap(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: cap ls | cap enable <name> | cap disable <name>"

        subcmd = args[0]

        if subcmd == "ls":
            caps = state.repo.list_capabilities()
            if not caps:
                return "(no capabilities)"
            lines = [f"{'NAME':<20} {'ENABLED':<10} {'DESCRIPTION'}"]
            lines.append("-" * 60)
            for c in caps:
                enabled = "\033[32myes\033[0m" if c.enabled else "\033[31mno\033[0m"
                lines.append(f"{c.name:<20} {enabled:<19} {c.description if c.description is not None else ''}")
            return "\n".join(lines)

        elif subcmd == "enable":
            if len(args) < 2:
                return "Usage: cap enable <name>"
            name = args[1]
            cap_obj = state.repo.get_capability_by_name(name)
            if not cap_obj:
                return f"Capability not found: {name}"
            cap_obj.enabled = True
            state.repo.upsert_capability(cap_obj)
            return f"Enabled: {name}"

        elif subcmd == "disable":
            if len(args) < 2:
                return "Usage: cap disable <name>"
            name = args[1]
            cap_obj = state.repo.get_capability_by_name(name)
            if not cap_obj:
                return f"Capability not found: {name}"
            cap_obj.enabled = False
            state.repo.upsert_capability(cap_obj)
            return f"Disabled: {name}"

        else:
            return f"Unknown subcommand: cap {subcmd}"
