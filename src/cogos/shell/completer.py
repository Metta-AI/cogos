"""Context-aware tab completer for the CogOS shell."""

from __future__ import annotations

import time
from typing import Iterable

from prompt_toolkit.completion import CompleteEvent, Completion, Completer
from prompt_toolkit.document import Document

from cogos.shell.commands import CommandRegistry, ShellState

_FILE_COMMANDS = {"cat", "less", "rm", "vim", "vi", "edit", "source", "."}
_DIR_COMMANDS = {"cd", "ls", "tree"}
_PROC_COMMANDS = {"kill", "attach"}
_CHANNEL_SUBCMDS = {"send", "log"}
_CAP_SUBCMDS = {"enable", "disable"}

_CACHE_TTL = 2.0


class ShellCompleter(Completer):
    def __init__(self, state: ShellState, registry: CommandRegistry) -> None:
        self._state = state
        self._registry = registry
        self._cache: dict[str, tuple[float, list]] = {}

    def _cached(self, key: str, fetch):
        now = time.time()
        if key in self._cache:
            ts, data = self._cache[key]
            if now - ts < _CACHE_TTL:
                return data
        data = fetch()
        self._cache[key] = (now, data)
        return data

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        text = document.text_before_cursor
        parts = text.split()

        # Completing the command name
        if not parts or (len(parts) == 1 and not text.endswith(" ")):
            prefix = parts[0] if parts else ""
            for name in self._registry.command_names:
                if name.startswith(prefix):
                    yield Completion(name, start_position=-len(prefix))
            return

        cmd = parts[0]
        current = parts[-1] if not text.endswith(" ") else ""
        start_pos = -len(current)

        # File path completion
        if cmd in _FILE_COMMANDS or cmd in _DIR_COMMANDS:
            yield from self._complete_paths(current, start_pos, dirs_only=(cmd in _DIR_COMMANDS))
            return

        # llm -f <file>
        if cmd == "llm" and "-f" in parts:
            f_idx = parts.index("-f")
            if len(parts) == f_idx + 2 and not text.endswith(" "):
                yield from self._complete_paths(current, start_pos)
                return
            if len(parts) == f_idx + 1 and text.endswith(" "):
                yield from self._complete_paths("", 0)
                return

        # Process name completion
        if cmd in _PROC_COMMANDS:
            yield from self._complete_processes(current, start_pos)
            return

        # Channel subcommand completion
        if cmd == "ch" and len(parts) >= 2:
            subcmd = parts[1]
            if subcmd in _CHANNEL_SUBCMDS and (len(parts) == 2 and text.endswith(" ") or len(parts) == 3 and not text.endswith(" ")):
                yield from self._complete_channels(current, start_pos)
                return

        # Capability subcommand completion
        if cmd == "cap" and len(parts) >= 2:
            subcmd = parts[1]
            if subcmd in _CAP_SUBCMDS:
                yield from self._complete_capabilities(current, start_pos)
                return

        # spawn --runner completion
        if cmd == "spawn" and len(parts) >= 2 and parts[-2] == "--runner":
            for r in ("lambda", "ecs"):
                if r.startswith(current):
                    yield Completion(r, start_position=start_pos)
            return

        # runs --process completion
        if cmd == "runs" and len(parts) >= 2 and parts[-2] == "--process":
            yield from self._complete_processes(current, start_pos)
            return

    def _complete_paths(self, current: str, start_pos: int, dirs_only: bool = False) -> Iterable[Completion]:
        state = self._state

        if "/" in current:
            search_prefix_rel = current.rsplit("/", 1)[0] + "/"
            if current.startswith("/"):
                search_prefix = search_prefix_rel.lstrip("/")
            else:
                search_prefix = state.cwd + search_prefix_rel
        else:
            search_prefix = state.cwd
            search_prefix_rel = ""

        all_files = self._cached(
            f"files:{search_prefix}",
            lambda: state.repo.list_files(prefix=search_prefix or None, limit=500),
        )

        seen_dirs: set[str] = set()
        prefix_len = len(search_prefix)

        for f in all_files:
            remainder = f.key[prefix_len:]
            if "/" in remainder:
                dir_name = remainder.split("/")[0] + "/"
                full = search_prefix_rel + dir_name
                if full.startswith(current) and dir_name not in seen_dirs:
                    seen_dirs.add(dir_name)
                    yield Completion(full, start_position=start_pos)
            elif not dirs_only:
                full = search_prefix_rel + remainder
                if full.startswith(current):
                    yield Completion(full, start_position=start_pos)

    def _complete_processes(self, current: str, start_pos: int) -> Iterable[Completion]:
        procs = self._cached("procs", lambda: self._state.repo.list_processes())
        for p in procs:
            if p.name.startswith(current):
                yield Completion(p.name, start_position=start_pos)

    def _complete_channels(self, current: str, start_pos: int) -> Iterable[Completion]:
        channels = self._cached("channels", lambda: self._state.repo.list_channels())
        for ch in channels:
            if ch.name.startswith(current):
                yield Completion(ch.name, start_position=start_pos)

    def _complete_capabilities(self, current: str, start_pos: int) -> Iterable[Completion]:
        caps = self._cached("caps", lambda: self._state.repo.list_capabilities())
        for c in caps:
            if c.name.startswith(current):
                yield Completion(c.name, start_position=start_pos)
