"""File commands — ls, cd, pwd, tree, cat, less, rm, mkdir, vim/edit."""

from __future__ import annotations

import os
import subprocess
import tempfile

from cogos.files.store import FileStore
from cogos.shell.commands import CommandRegistry, ShellState


def _resolve_path(state: ShellState, path: str) -> str:
    """Resolve a path relative to cwd, returning a file store key."""
    if path.startswith("/"):
        resolved = path.lstrip("/")
    else:
        resolved = state.cwd + path

    parts = resolved.split("/")
    normalized: list[str] = []
    for p in parts:
        if p == "..":
            if normalized:
                normalized.pop()
        elif p and p != ".":
            normalized.append(p)
    return "/".join(normalized)


def _ensure_trailing_slash(prefix: str) -> str:
    if prefix and not prefix.endswith("/"):
        return prefix + "/"
    return prefix


def _list_children(repo, prefix: str) -> tuple[list[str], list[str]]:
    """List immediate children (dirs and files) under a prefix."""
    prefix = _ensure_trailing_slash(prefix) if prefix else ""
    all_files = repo.list_files(prefix=prefix or None, limit=1000)
    dirs: set[str] = set()
    files: list[str] = []
    prefix_len = len(prefix)

    for f in all_files:
        remainder = f.key[prefix_len:]
        if "/" in remainder:
            dir_name = remainder.split("/")[0]
            dirs.add(dir_name)
        else:
            files.append(remainder)

    return sorted(dirs), sorted(files)


def register(reg: CommandRegistry) -> None:

    @reg.register("pwd", help="Print working directory")
    def pwd(state: ShellState, args: list[str]) -> str:
        return "/" + state.cwd.rstrip("/") if state.cwd else "/"

    @reg.register("ls", help="List files and directories")
    def ls(state: ShellState, args: list[str]) -> str:
        target = _resolve_path(state, args[0]) if args else state.cwd.rstrip("/")
        dirs, files = _list_children(state.repo, target)
        lines: list[str] = []
        for d in dirs:
            lines.append(f"\033[1;34m{d}/\033[0m")
        for f in files:
            lines.append(f)
        if not lines:
            return "(empty)"
        return "\n".join(lines)

    @reg.register("cd", help="Change directory")
    def cd(state: ShellState, args: list[str]) -> str:
        if not args or args[0] == "/":
            state.cwd = ""
            return ""
        resolved = _resolve_path(state, args[0])
        if not resolved:
            state.cwd = ""
            return ""
        new_prefix = _ensure_trailing_slash(resolved)
        files = state.repo.list_files(prefix=new_prefix, limit=1)
        if not files:
            return f"cd: no such directory: {args[0]}"
        state.cwd = new_prefix
        return ""

    @reg.register("cat", help="Print file content")
    def cat(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: cat <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        content = fs.get_content(key)
        if content is None:
            return f"cat: not found: {args[0]}"
        return content

    @reg.register("less", help="Page file content through system pager")
    def less(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: less <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        content = fs.get_content(key)
        if content is None:
            return f"less: not found: {args[0]}"
        pager = os.environ.get("PAGER", "less")
        try:
            proc = subprocess.Popen([pager], stdin=subprocess.PIPE)
            proc.communicate(input=content.encode())
        except FileNotFoundError:
            return content
        return ""

    @reg.register("rm", help="Delete a file")
    def rm(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: rm <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        try:
            fs.delete(key)
        except ValueError:
            return f"rm: not found: {args[0]}"
        return f"Removed: {key}"

    @reg.register("mkdir", help="Create a directory (no-op — directories are implicit)")
    def mkdir(state: ShellState, args: list[str]) -> str:
        return "Directories are implicit from file key prefixes."

    @reg.register("tree", help="Recursive file listing")
    def tree(state: ShellState, args: list[str]) -> str:
        target = _resolve_path(state, args[0]) if args else state.cwd.rstrip("/")
        prefix = _ensure_trailing_slash(target) if target else ""
        all_files = state.repo.list_files(prefix=prefix or None, limit=1000)
        if not all_files:
            return "(empty)"
        prefix_len = len(prefix)
        tree_map: dict[str, list[str]] = {}
        for f in all_files:
            remainder = f.key[prefix_len:]
            parts = remainder.rsplit("/", 1)
            if len(parts) == 2:
                dir_path, filename = parts
                tree_map.setdefault(dir_path, []).append(filename)
            else:
                tree_map.setdefault(".", []).append(remainder)

        lines: list[str] = []
        for dir_path in sorted(tree_map.keys()):
            if dir_path != ".":
                lines.append(f"\033[1;34m{dir_path}/\033[0m")
            for filename in sorted(tree_map[dir_path]):
                indent = "  " if dir_path != "." else ""
                lines.append(f"{indent}{filename}")
        return "\n".join(lines)

    @reg.register("edit", aliases=["vim", "vi"], help="Edit a file with $EDITOR")
    def edit(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: edit <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        existing_content = fs.get_content(key)
        content = existing_content if existing_content is not None else ""
        is_new = existing_content is None

        editor = os.environ.get("EDITOR", "vim")
        suffix = "." + key.rsplit(".", 1)[-1] if "." in key else ".txt"

        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            subprocess.call([editor, tmp_path])
            with open(tmp_path) as f:
                new_content = f.read()
        finally:
            os.unlink(tmp_path)

        if new_content == content:
            return "(no changes)"

        fs.upsert(key, new_content, source="shell")
        verb = "Created" if is_new else "Updated"
        return f"{verb}: {key}"
