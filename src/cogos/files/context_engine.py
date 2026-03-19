"""Context engine -- resolves file references to build full prompt context.

Files in CogOS reference other files with inline ``@{file-key}`` syntax.
The context engine parses those references from file content, resolves
them recursively, concatenates their content with section headers, and
returns a single string suitable for injection into an LLM prompt.

Circular references are detected and reported as errors in the output.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from uuid import UUID

from cogos.files.references import extract_file_references
from cogos.files.store import FileStore

if TYPE_CHECKING:
    from cogos.db.models import Process

logger = logging.getLogger(__name__)
PROMPT_REF_RE = re.compile(r"@\{([^{}\n]+)\}")


class ContextEngine:
    """Resolves file references into a single concatenated context string."""

    def __init__(self, file_store: FileStore) -> None:
        self._store = file_store

    def resolve(self, key: str) -> str:
        """Resolve a file by *key*, recursively expanding includes.

        Returns the fully assembled context string.
        Raises ``ValueError`` if the root file is not found.
        """
        file = self._store.get(key)
        if file is None:
            raise ValueError(f"File not found: {key}")
        return self._resolve_key(key, visited=set())

    def resolve_by_id(self, file_id: UUID) -> str:
        """Resolve a file by *file_id*, recursively expanding includes.

        Returns the fully assembled context string.
        Raises ``ValueError`` if the root file is not found.
        """
        file = self._store.get_by_id(file_id)
        if file is None:
            raise ValueError(f"File not found: {file_id}")
        return self._resolve_key(file.key, visited=set())

    def generate_full_prompt(self, process: Process) -> str:
        """Build the complete prompt for a process.

        The process prompt now comes entirely from ``process.content``.
        Any inline ``@{file-key}`` references the process can read are
        expanded recursively, and referenced files still honor their own
        inline references.
        """
        return self._expand_process_text(process, process.content, visited=set())

    def resolve_prompt_tree(self, process: Process) -> list[dict]:
        """Build a structured dependency tree for the process prompt.

        Returns a list of dicts in include-order (deepest deps first):
        ``[{"key": str, "content": str, "is_direct": bool}, ...]``

        Each file appears at most once. ``is_direct`` is True for files
        referenced directly from ``process.content`` via ``@{file-key}``.
        The final entry (if ``process.content`` is set) has
        ``key = "<content>"`` and ``is_direct = True``.
        """
        result: list[dict] = []
        seen: set[str] = set()
        prompt_reference_keys = self._resolve_prompt_reference_keys(process)
        direct_keys = set(prompt_reference_keys)

        for key in prompt_reference_keys:
            if key not in seen:
                self._collect_tree(key, seen, result, direct_keys)

        # Append process.content last
        if process.content:
            result.append({
                "key": "<content>",
                "content": process.content,
                "is_direct": True,
            })

        return result

    def _collect_tree(
        self,
        key: str,
        seen: set[str],
        result: list[dict],
        direct_keys: set[str],
    ) -> None:
        """Recursively collect files in dependency order (deps first)."""
        if key in seen:
            return
        seen.add(key)

        file = self._store.get(key)
        if file is None:
            result.append({"key": key, "content": f"[not found: {key}]", "is_direct": key in direct_keys})
            return

        content = self._store.get_content(key) or ""
        for ref_key in self._extract_refs(content):
            self._collect_tree(ref_key, seen, result, direct_keys)
        result.append({"key": key, "content": content, "is_direct": key in direct_keys})

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_prompt_reference_keys(self, process: Process) -> list[str]:
        keys: list[str] = []
        for key in extract_file_references(process.content or ""):
            if self._can_process_read_key(process, key):
                keys.append(key)
            else:
                logger.warning("Process %s cannot read prompt reference %s", process.name, key)
        return keys

    def _can_process_read_key(self, process: Process, key: str) -> bool:
        repo = self._store.repo
        for grant in repo.list_process_capabilities(process.id):
            capability = repo.get_capability(grant.capability)
            if not capability:
                continue

            cfg = grant.config or {}
            ops = cfg.get("ops")
            if isinstance(ops, list) and "read" not in ops:
                continue

            if capability.name == "file":
                scoped_key = cfg.get("key")
                if scoped_key is None or str(scoped_key) == key:
                    return True
            elif capability.name in {"root_dir", "dir", "files"}:
                prefix = cfg.get("prefix")
                if prefix is None or key.startswith(str(prefix)):
                    return True
        return False

    def _resolve_key(self, key: str, *, visited: set[str]) -> str:
        """Recursively resolve *key* and its referenced files.

        *visited* tracks keys already seen on the current resolution path
        to detect circular references.
        """
        if key in visited:
            msg = f"[circular include: {key}]"
            logger.warning("Circular include detected: %s", key)
            return msg

        visited.add(key)

        file = self._store.get(key)
        if file is None:
            msg = f"[include not found: {key}]"
            logger.warning("Included file not found: %s", key)
            return msg

        content = self._store.get_content(key) or ""

        header = f"--- {key} ---"
        return f"{header}\n{self._expand_text(content, visited=set(visited))}"

    def _expand_text(self, text: str, *, visited: set[str]) -> str:
        if not text:
            return ""

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            return self._resolve_key(key, visited=set(visited))

        return PROMPT_REF_RE.sub(_replace, text)

    def _expand_process_text(self, process: Process, text: str, *, visited: set[str]) -> str:
        if not text:
            return ""

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            if not self._can_process_read_key(process, key):
                logger.warning("Process %s cannot read prompt reference %s", process.name, key)
                return match.group(0)
            return self._resolve_key(key, visited=set(visited))

        return PROMPT_REF_RE.sub(_replace, text)

    @staticmethod
    def _extract_refs(text: str) -> list[str]:
        seen: set[str] = set()
        refs: list[str] = []
        for match in PROMPT_REF_RE.finditer(text or ""):
            key = match.group(1).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            refs.append(key)
        return refs
