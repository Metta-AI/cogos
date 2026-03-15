"""FileStore: high-level versioned file operations."""

from __future__ import annotations

import logging

from cogos.db.models import File, FileVersion
from cogos.files.references import extract_file_references

logger = logging.getLogger(__name__)


class FileStore:
    """Wraps a CogOS repository with versioned file operations."""

    def __init__(self, repo) -> None:  # noqa: ANN001
        self._repo = repo

    @property
    def repo(self):  # noqa: ANN201
        return self._repo

    def create(
        self,
        key: str,
        content: str,
        *,
        source: str = "cogent",
        read_only: bool = False,
    ) -> File:
        """Create a new file with version 1."""
        f = File(key=key, includes=extract_file_references(content, exclude_key=key))
        self._repo.insert_file(f)
        fv = FileVersion(
            file_id=f.id,
            version=1,
            content=content,
            source=source,
            read_only=read_only,
            is_active=True,
        )
        self._repo.insert_file_version(fv)
        return f

    def new_version(
        self,
        key: str,
        content: str,
        *,
        source: str = "cogent",
        read_only: bool = False,
    ) -> FileVersion | None:
        """Add a new version if content changed. Returns None if unchanged or not found."""
        f = self._repo.get_file_by_key(key)
        if f is None:
            return None
        active = self._repo.get_active_file_version(f.id)
        derived_includes = extract_file_references(content, exclude_key=key)
        if active and active.content == content:
            if f.includes != derived_includes:
                self._repo.update_file_includes(f.id, derived_includes)
            return None
        next_ver = self._repo.get_max_file_version(f.id) + 1
        # Deactivate current active
        if active:
            self._repo.set_active_file_version(f.id, next_ver)
        fv = FileVersion(
            file_id=f.id,
            version=next_ver,
            content=content,
            source=source,
            read_only=read_only,
            is_active=True,
        )
        self._repo.insert_file_version(fv)
        self._repo.update_file_includes(f.id, derived_includes)
        return fv

    def upsert(
        self,
        key: str,
        content: str,
        *,
        source: str = "cogent",
        read_only: bool = False,
    ) -> File | FileVersion | None:
        """Create or update a file. Returns File on create, FileVersion on update, None if unchanged."""
        f = self._repo.get_file_by_key(key)
        if f is None:
            return self.create(key, content, source=source, read_only=read_only)
        return self.new_version(key, content, source=source, read_only=read_only)

    def append(
        self,
        key: str,
        content: str,
        *,
        source: str = "cogent",
    ) -> File | FileVersion | None:
        """Append content to a file's active version in-place. Creates the file if it doesn't exist."""
        f = self._repo.get_file_by_key(key)
        if f is None:
            return self.create(key, content, source=source)
        fv = self._repo.get_active_file_version(f.id)
        if fv is None:
            return self.create(key, content, source=source)
        new_content = fv.content + content
        self._repo.update_file_version_content(f.id, fv.version, new_content)
        includes = extract_file_references(new_content, exclude_key=key)
        if f.includes != includes:
            self._repo.update_file_includes(f.id, includes)
        return fv

    def update_includes(self, key: str, includes: list[str]) -> bool:
        f = self._repo.get_file_by_key(key)
        if f is None:
            return False
        return self._repo.update_file_includes(f.id, includes)

    def get(self, key: str) -> File | None:
        return self._repo.get_file_by_key(key)

    def get_content(self, key: str) -> str | None:
        """Get the active version content for a file."""
        f = self._repo.get_file_by_key(key)
        if f is None:
            return None
        fv = self._repo.get_active_file_version(f.id)
        return fv.content if fv else None

    def get_by_id(self, file_id) -> File | None:
        return self._repo.get_file_by_id(file_id)

    def get_content_by_id(self, file_id) -> str | None:
        """Get the active version content by file ID."""
        f = self._repo.get_file_by_id(file_id)
        if f is None:
            return None
        fv = self._repo.get_active_file_version(f.id)
        return fv.content if fv else None

    def list_files(self, *, prefix: str | None = None, limit: int = 200) -> list[File]:
        return self._repo.list_files(prefix=prefix, limit=limit)

    def history(self, key: str) -> list[FileVersion]:
        f = self._repo.get_file_by_key(key)
        if f is None:
            return []
        return self._repo.list_file_versions(f.id)

    def delete(self, key: str) -> None:
        f = self._repo.get_file_by_key(key)
        if f is None:
            raise ValueError(f"file '{key}' not found")
        self._repo.delete_file(f.id)
