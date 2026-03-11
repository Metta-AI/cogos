from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import File, FileVersion
from cogos.files.store import FileStore
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-files"])


# ── Request / response models ──────────────────────────────────────


class FileOut(BaseModel):
    id: str
    key: str
    includes: list[str]
    created_at: str | None = None
    updated_at: str | None = None


class FileVersionOut(BaseModel):
    id: str
    file_id: str
    version: int
    read_only: bool
    content: str
    source: str
    is_active: bool
    created_at: str | None = None


class FileDetail(BaseModel):
    file: FileOut
    versions: list[FileVersionOut]


class FilesResponse(BaseModel):
    count: int
    files: list[FileOut]


class FileCreate(BaseModel):
    key: str
    content: str
    source: str = "cogent"
    read_only: bool = False
    includes: list[str] | None = None


class FileUpdate(BaseModel):
    content: str
    source: str = "cogent"
    read_only: bool = False


class VersionContentUpdate(BaseModel):
    content: str


# ── Helpers ─────────────────────────────────────────────────────────


def _store() -> FileStore:
    return FileStore(get_repo())


def _file_out(f: File) -> FileOut:
    return FileOut(
        id=str(f.id),
        key=f.key,
        includes=f.includes,
        created_at=str(f.created_at) if f.created_at else None,
        updated_at=str(f.updated_at) if f.updated_at else None,
    )


def _version_out(fv: FileVersion) -> FileVersionOut:
    return FileVersionOut(
        id=str(fv.id),
        file_id=str(fv.file_id),
        version=fv.version,
        read_only=fv.read_only,
        content=fv.content,
        source=fv.source,
        is_active=fv.is_active,
        created_at=str(fv.created_at) if fv.created_at else None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/files", response_model=FilesResponse)
def list_files(
    name: str,
    prefix: str | None = Query(None, description="Filter by key prefix"),
) -> FilesResponse:
    store = _store()
    items = store.list_files(prefix=prefix)
    out = [_file_out(f) for f in items]
    return FilesResponse(count=len(out), files=out)


@router.get("/files/{key:path}", response_model=FileDetail)
def get_file(name: str, key: str) -> FileDetail:
    store = _store()
    f = store.get(key)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    versions = store.history(key)
    return FileDetail(
        file=_file_out(f),
        versions=[_version_out(v) for v in versions],
    )


@router.post("/files", response_model=FileOut)
def create_file(name: str, body: FileCreate) -> FileOut:
    store = _store()
    f = store.create(
        key=body.key,
        content=body.content,
        source=body.source,
        read_only=body.read_only,
        includes=body.includes,
    )
    return _file_out(f)


@router.put("/files/{key:path}", response_model=FileVersionOut)
def update_file(name: str, key: str, body: FileUpdate) -> FileVersionOut:
    store = _store()
    fv = store.new_version(key, body.content, source=body.source, read_only=body.read_only)
    if fv is None:
        raise HTTPException(status_code=404, detail="File not found or content unchanged")
    return _version_out(fv)


@router.post("/files/{key:path}/versions/{version}/activate")
def activate_file_version(name: str, key: str, version: int) -> dict:
    repo = get_repo()
    f = repo.get_file_by_key(key)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    versions = repo.list_file_versions(f.id)
    if not any(v.version == version for v in versions):
        raise HTTPException(status_code=404, detail="Version not found")
    repo.set_active_file_version(f.id, version)
    return {"activated": True, "key": key, "version": version}


@router.put("/files/{key:path}/versions/{version}/content")
def update_file_version_content(name: str, key: str, version: int, body: VersionContentUpdate) -> FileVersionOut:
    repo = get_repo()
    f = repo.get_file_by_key(key)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if not repo.update_file_version_content(f.id, version, body.content):
        raise HTTPException(status_code=404, detail="Version not found")
    versions = repo.list_file_versions(f.id)
    fv = next((v for v in versions if v.version == version), None)
    if not fv:
        raise HTTPException(status_code=404, detail="Version not found")
    return _version_out(fv)


@router.delete("/files/{key:path}/versions/{version}")
def delete_file_version(name: str, key: str, version: int) -> dict:
    repo = get_repo()
    f = repo.get_file_by_key(key)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if not repo.delete_file_version(f.id, version):
        raise HTTPException(status_code=404, detail="Version not found")
    return {"deleted": True, "key": key, "version": version}


@router.delete("/files/{key:path}")
def delete_file(name: str, key: str) -> dict:
    store = _store()
    try:
        store.delete(key)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"deleted": True, "key": key}
