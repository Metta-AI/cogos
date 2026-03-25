"""Shell history backed by the CogOS file store."""

from __future__ import annotations

from typing import Iterable

from prompt_toolkit.history import History

from cogos.files.store import FileStore

_HISTORY_KEY = "home/root/.shell_history"


class CogOSHistory(History):
    """Persistent shell history stored in the CogOS versioned file store."""

    def __init__(self, repo) -> None:
        self._fs = FileStore(repo)
        super().__init__()

    def load_history_strings(self) -> Iterable[str]:
        content = self._fs.get_content(_HISTORY_KEY)
        if not content:
            return
        # Yield in reverse so most recent is first (prompt_toolkit convention)
        lines = [line for line in content.splitlines() if line]
        yield from reversed(lines)

    def store_string(self, string: str) -> None:
        content = self._fs.get_content(_HISTORY_KEY)
        if content is None:
            content = ""
        content += string + "\n"
        self._fs.upsert(_HISTORY_KEY, content, source="shell")
