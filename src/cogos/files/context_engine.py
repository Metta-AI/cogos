"""Capability-scoped prompt resolver for CogOS authored prompt sources."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from cogos.files.store import FileStore

if TYPE_CHECKING:
    from cogos.db.models import File, Process
    from cogos.db.repository import Repository


INLINE_INCLUDE_RE = re.compile(r"@\{([^{}\n]+)\}")
GLOBAL_INCLUDE_PREFIX = "cogos/includes/"
CONTENT_KEY = "<content>"


@dataclass
class PromptResolution:
    text: str
    prompt_tree: list[dict]


@dataclass
class _PromptEntry:
    key: str
    content: str
    is_direct: bool


@dataclass
class _ResolutionState:
    root_keys: set[str]
    bundle_entries: list[_PromptEntry] = field(default_factory=list)
    emitted_bundle_keys: set[str] = field(default_factory=set)


class _FileAccessView:
    """Capability-scoped read view used during prompt assembly."""

    def __init__(self, repo: Repository, process: Process | None) -> None:
        self._repo = repo
        self._allow_all = process is None
        self._exact_keys: set[str] = set()
        self._prefixes: list[str] = []
        if process is not None:
            self._load_process_rules(process)

    def can_read(self, key: str) -> bool:
        if self._allow_all:
            return True
        if key in self._exact_keys:
            return True
        return any(key.startswith(prefix) for prefix in self._prefixes)

    def read(self, key: str) -> tuple[str | None, str]:
        if not self.can_read(key):
            return None, "access_denied"
        file = self._repo.get_file_by_key(key)
        if file is None:
            return None, "not_found"
        version = self._repo.get_active_file_version(file.id)
        if version is None:
            return None, "not_found"
        return version.content or "", "ok"

    def list_readable_files(self, *, prefix: str | None = None, limit: int = 10_000) -> list[File]:
        files = self._repo.list_files(prefix=prefix, limit=limit)
        return [file for file in files if self.can_read(file.key)]

    def _load_process_rules(self, process: Process) -> None:
        pcs = self._repo.list_process_capabilities(process.id)
        for pc in pcs:
            cap = self._repo.get_capability(pc.capability)
            if cap is None or not cap.enabled:
                continue

            cap_name = cap.name.split("/", 1)[0]
            if cap_name not in {"file", "dir", "files"}:
                continue

            config = pc.config or {}
            ops_raw = config.get("ops")
            if ops_raw is not None:
                ops = {str(op) for op in ops_raw}
                if "read" not in ops:
                    continue

            key = config.get("key")
            prefix = config.get("prefix")

            if key:
                self._exact_keys.add(str(key))
                continue
            if prefix:
                self._prefixes.append(str(prefix))
                continue

            # Unscoped file/dir/files grant implies unrestricted prompt reads.
            self._allow_all = True


class ContextEngine:
    """Resolve authored prompt text into a final system prompt."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo
        self._store = FileStore(repo)

    def resolve(self, key: str) -> str:
        file = self._store.get(key)
        if file is None:
            raise ValueError(f"File not found: {key}")
        access = _FileAccessView(self._repo, None)
        state = _ResolutionState(root_keys={key})
        rendered = self._render_file(file, access, state, stack=(key,))
        return self._compose_prompt([rendered], state.bundle_entries)

    def resolve_by_id(self, file_id: UUID) -> str:
        file = self._store.get_by_id(file_id)
        if file is None:
            raise ValueError(f"File not found: {file_id}")
        return self.resolve(file.key)

    def generate_full_prompt(self, process: Process) -> str:
        return self.resolve_prompt(process).text

    def resolve_prompt_tree(self, process: Process) -> list[dict]:
        return self.resolve_prompt(process).prompt_tree

    def resolve_prompt(self, process: Process) -> PromptResolution:
        access = _FileAccessView(self._repo, process)

        direct_files = self._direct_prompt_files(process)
        global_files = access.list_readable_files(prefix=GLOBAL_INCLUDE_PREFIX)

        root_entries: list[_PromptEntry] = []
        root_keys = {file.key for file in direct_files}
        root_keys.update(file.key for file in global_files)
        state = _ResolutionState(root_keys=root_keys)

        for file in global_files:
            rendered = self._render_file(file, access, state, stack=(file.key,))
            root_entries.append(_PromptEntry(key=file.key, content=rendered, is_direct=False))

        for file in direct_files:
            rendered = self._render_file(file, access, state, stack=(file.key,))
            root_entries.append(_PromptEntry(key=file.key, content=rendered, is_direct=True))

        if process.content:
            rendered_content = self._render_text(process.content, access, state, stack=())
            root_entries.append(_PromptEntry(key=CONTENT_KEY, content=rendered_content, is_direct=True))

        prompt_text = self._compose_prompt(
            [entry.content for entry in root_entries if entry.content],
            state.bundle_entries,
        )
        prompt_tree = [
            {
                "key": entry.key,
                "content": entry.content,
                "is_direct": entry.is_direct,
            }
            for entry in [*root_entries, *state.bundle_entries]
        ]
        return PromptResolution(text=prompt_text, prompt_tree=prompt_tree)

    def list_global_includes(self, process: Process) -> list[dict]:
        access = _FileAccessView(self._repo, process)
        includes: list[dict] = []
        for file in access.list_readable_files(prefix=GLOBAL_INCLUDE_PREFIX):
            content, status = access.read(file.key)
            if status == "ok":
                includes.append({"key": file.key, "content": content or ""})
        return includes

    def _direct_prompt_files(self, process: Process) -> list[File]:
        direct_files: list[File] = []
        seen: set[str] = set()

        for file_id in process.files or []:
            file = self._store.get_by_id(file_id)
            if file is None or file.key in seen:
                continue
            seen.add(file.key)
            direct_files.append(file)

        if process.code and not process.files:
            file = self._store.get_by_id(process.code)
            if file is not None and file.key not in seen:
                direct_files.append(file)

        return direct_files

    def _render_file(
        self,
        file: File,
        access: _FileAccessView,
        state: _ResolutionState,
        *,
        stack: tuple[str, ...],
    ) -> str:
        sections: list[str] = []
        for include_key in file.includes:
            marker = self._resolve_reference(include_key, access, state, stack=stack)
            if marker:
                sections.append(marker)

        content, status = access.read(file.key)
        if status == "not_found":
            sections.append(self._not_found_marker(file.key))
        else:
            # Direct prompt files are explicit process configuration. They are still
            # resolved recursively through scoped reads for nested dependencies.
            file_content = content if status == "ok" else self._store.get_content(file.key) or ""
            sections.append(self._render_text(file_content, access, state, stack=stack))

        return "\n\n".join(section for section in sections if section)

    def _render_text(
        self,
        text: str,
        access: _FileAccessView,
        state: _ResolutionState,
        *,
        stack: tuple[str, ...],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            return self._resolve_reference(match.group(1).strip(), access, state, stack=stack)

        return INLINE_INCLUDE_RE.sub(replace, text)

    def _resolve_reference(
        self,
        key: str,
        access: _FileAccessView,
        state: _ResolutionState,
        *,
        stack: tuple[str, ...],
    ) -> str:
        if not key:
            return self._not_found_marker(key)
        if key in stack:
            return self._circular_marker(key)
        if key in state.root_keys or key in state.emitted_bundle_keys:
            return self._uses_marker(key)

        content, status = access.read(key)
        if status == "access_denied":
            return self._access_denied_marker(key)
        if status == "not_found":
            return self._not_found_marker(key)

        file = self._store.get(key)
        if file is None:
            return self._not_found_marker(key)

        rendered = self._render_file(file, access, state, stack=(*stack, key))
        state.bundle_entries.append(_PromptEntry(key=key, content=rendered, is_direct=False))
        state.emitted_bundle_keys.add(key)
        return self._uses_marker(key)

    def _compose_prompt(self, sections: list[str], bundle_entries: list[_PromptEntry]) -> str:
        bundle = [
            f"{self._included_marker(entry.key)}\n{entry.content}"
            for entry in bundle_entries
        ]
        parts = [part for part in [*sections, *bundle] if part]
        return "\n\n".join(parts)

    @staticmethod
    def _uses_marker(key: str) -> str:
        return f"<!-- uses: {key} -->"

    @staticmethod
    def _included_marker(key: str) -> str:
        return f"<!-- included: {key} -->"

    @staticmethod
    def _not_found_marker(key: str) -> str:
        return f"<!-- include error: not found {key} -->"

    @staticmethod
    def _circular_marker(key: str) -> str:
        return f"<!-- include error: circular {key} -->"

    @staticmethod
    def _access_denied_marker(key: str) -> str:
        return f"<!-- include error: access denied {key} -->"
