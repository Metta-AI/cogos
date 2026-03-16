"""Me capability — scoped file/dir access for the current process and run."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class FileWriteResult(BaseModel):
    key: str
    version: int


# ── Scoped helpers ───────────────────────────────────────────


class FileHandle:
    """A scoped file handle that supports read/write on a fixed key."""

    def __init__(self, key: str, store: FileStore, repo):
        self._key = key
        self._store = store
        self._repo = repo

    @property
    def key(self) -> str:
        return self._key

    def read(self) -> str | None:
        f = self._store.get(self._key)
        if f is None:
            return None
        fv = self._repo.get_active_file_version(f.id)
        return fv.content if fv else None

    def write(self, content: str) -> FileWriteResult:
        result = self._store.upsert(self._key, content, source="process")
        if result is None:
            return FileWriteResult(key=self._key, version=0)
        if hasattr(result, "version"):
            return FileWriteResult(key=self._key, version=result.version)
        return FileWriteResult(key=self._key, version=1)

    def __repr__(self) -> str:
        return f"<File {self._key}>"


class DirHandle:
    """A scoped directory handle that supports list/read/write under a prefix."""

    def __init__(self, prefix: str, store: FileStore, repo):
        self._prefix = prefix
        self._store = store
        self._repo = repo

    @property
    def key(self) -> str:
        return self._prefix

    def list(self, limit: int = 50) -> list[str]:
        files = self._store.list_files(prefix=self._prefix, limit=limit)
        return [f.key for f in files]

    def read(self, name: str) -> str | None:
        fh = FileHandle(self._prefix + name, self._store, self._repo)
        return fh.read()

    def write(self, name: str, content: str) -> FileWriteResult:
        fh = FileHandle(self._prefix + name, self._store, self._repo)
        return fh.write(content)

    def file(self, name: str) -> FileHandle:
        return FileHandle(self._prefix + name, self._store, self._repo)

    def __repr__(self) -> str:
        return f"<Dir {self._prefix}>"


# ── Scope (shared base for RunScope / ProcessScope) ──────────


class Scope:
    """Base for scoped file/dir access under a key prefix."""

    def __init__(self, base: str, store: FileStore, repo):
        self._base = base
        self._store = store
        self._repo = repo

    def tmp(self) -> FileHandle:
        return FileHandle(f"{self._base}/tmp", self._store, self._repo)

    def tmp_dir(self) -> DirHandle:
        return DirHandle(f"{self._base}/tmp/", self._store, self._repo)

    def log(self) -> FileHandle:
        return FileHandle(f"{self._base}/log", self._store, self._repo)

    def scratch(self) -> FileHandle:
        return FileHandle(f"{self._base}/scratch", self._store, self._repo)

    def scratch_dir(self) -> DirHandle:
        return DirHandle(f"{self._base}/scratch/", self._store, self._repo)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._base}>"


class RunScope(Scope):
    """Scoped access to the current run's scratch/tmp/log."""

    def __init__(self, process_id: UUID, run_id: UUID, store: FileStore, repo):
        super().__init__(f"/proc/{process_id}/runs/{run_id}", store, repo)


class ProcessScope(Scope):
    """Scoped access to the current process's scratch/tmp/log."""

    def __init__(self, process_id: UUID, store: FileStore, repo):
        super().__init__(f"/proc/{process_id}", store, repo)


# ── Capability ───────────────────────────────────────────────


class MeCapability(Capability):
    """Self-referential capability for scoped file access.

    Usage:
        me.run().scratch().write("hello")
        me.run().tmp_dir().list()
        me.process().log().read()
        me.process().scratch_dir().write("notes", "content")
    """

    def __init__(self, repo, process_id: UUID, run_id: UUID | None = None) -> None:
        super().__init__(repo, process_id)
        self.run_id = run_id
        self._store = FileStore(repo)

    def run(self) -> RunScope:
        if self.run_id is None:
            raise RuntimeError("No active run — me.run() requires a run context")
        return RunScope(self.process_id, self.run_id, self._store, self.repo)

    def process(self) -> ProcessScope:
        return ProcessScope(self.process_id, self._store, self.repo)

    def _process_name(self) -> str:
        proc = self.repo.get_process(self.process_id)
        return proc.name if proc else str(self.process_id)

    def _publish_stream(self, stream: str, text: str) -> None:
        """Publish to process:<name>:<stream> and optionally forward to io:<stream>."""
        from cogos.db.models import ChannelMessage
        name = self._process_name()
        ch = self.repo.get_channel_by_name(f"process:{name}:{stream}")
        if ch:
            self.repo.append_channel_message(ChannelMessage(
                channel=ch.id, sender_process=self.process_id,
                payload={"text": text, "process": name},
            ))
        proc = self.repo.get_process(self.process_id)
        if proc and proc.tty:
            io_ch = self.repo.get_channel_by_name(f"io:{stream}")
            if io_ch:
                self.repo.append_channel_message(ChannelMessage(
                    channel=io_ch.id, sender_process=self.process_id,
                    payload={"text": text, "process": name},
                ))

    def stdout(self, text: str) -> None:
        """Write to process stdout (and io:stdout if tty)."""
        self._publish_stream("stdout", text)

    def stderr(self, text: str) -> None:
        """Write to process stderr (and io:stderr if tty)."""
        self._publish_stream("stderr", text)

    def stdin(self, limit: int = 1) -> str | list[str] | None:
        """Read next message(s) from process stdin."""
        name = self._process_name()
        ch = self.repo.get_channel_by_name(f"process:{name}:stdin")
        if not ch:
            return None
        msgs = self.repo.list_channel_messages(ch.id, limit=limit)
        if not msgs:
            return None
        texts = [m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload) for m in msgs]
        return texts[0] if limit == 1 else texts

    def __repr__(self) -> str:
        return f"<MeCapability process={self.process_id} run={self.run_id}>"
