from __future__ import annotations

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.files.store import FileStore


_PENDING_RESPONSES: dict[str, dict] = {}


class PublishResult(BaseModel):
    path: str
    version: int
    created: bool


class UnpublishResult(BaseModel):
    path: str
    deleted: bool


class WebResponse(BaseModel):
    request_id: str
    status: int


class ListResult(BaseModel):
    files: list[str]


class WebError(BaseModel):
    error: str


def get_pending_response(request_id: str) -> dict | None:
    return _PENDING_RESPONSES.pop(request_id, None)


class WebCapability(Capability):
    ALL_OPS = {"publish", "unpublish", "respond", "list"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}

        e_ops = existing.get("ops")
        r_ops = requested.get("ops")
        if e_ops is not None and r_ops is not None:
            result["ops"] = set(e_ops) & set(r_ops)
        elif e_ops is not None:
            result["ops"] = e_ops
        elif r_ops is not None:
            result["ops"] = r_ops

        e_pfx = existing.get("path_prefix")
        r_pfx = requested.get("path_prefix")
        if e_pfx is not None and r_pfx is not None:
            if r_pfx.startswith(e_pfx):
                result["path_prefix"] = r_pfx
            else:
                result["path_prefix"] = e_pfx
        elif e_pfx is not None:
            result["path_prefix"] = e_pfx
        elif r_pfx is not None:
            result["path_prefix"] = r_pfx

        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed by scope")
        path = context.get("path")
        path_prefix = self._scope.get("path_prefix")
        if path and path_prefix and not str(path).startswith(path_prefix):
            raise PermissionError(f"Path '{path}' outside allowed prefix '{path_prefix}'")

    def publish(
        self,
        path: str,
        content: str,
    ) -> PublishResult | WebError:
        if not path:
            return WebError(error="'path' is required")
        if not content:
            return WebError(error="'content' is required")
        self._check("publish", path=path)

        store = FileStore(self.repo)
        key = f"web/{path}"
        result = store.upsert(key, content, source="web")

        if result is None:
            existing = store.get(key)
            if existing:
                active = self.repo.get_active_file_version(existing.id)
                return PublishResult(path=path, version=active.version if active else 1, created=False)
            return WebError(error="failed to publish")

        from cogos.db.models import File, FileVersion
        if isinstance(result, File):
            return PublishResult(path=path, version=1, created=True)
        return PublishResult(path=path, version=result.version, created=False)

    def unpublish(self, path: str) -> UnpublishResult | WebError:
        if not path:
            return WebError(error="'path' is required")
        self._check("unpublish", path=path)

        store = FileStore(self.repo)
        key = f"web/{path}"
        try:
            store.delete(key)
            return UnpublishResult(path=path, deleted=True)
        except ValueError:
            return UnpublishResult(path=path, deleted=False)

    def respond(
        self,
        request_id: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: str = "",
    ) -> WebResponse | WebError:
        if not request_id:
            return WebError(error="'request_id' is required")
        self._check("respond")

        if request_id not in _PENDING_RESPONSES:
            entry: dict = {"status": status, "body": body}
            if headers:
                entry["headers"] = headers
            _PENDING_RESPONSES[request_id] = entry

        return WebResponse(request_id=request_id, status=_PENDING_RESPONSES[request_id]["status"])

    def list(self, prefix: str = "") -> ListResult | WebError:
        self._check("list")

        store = FileStore(self.repo)
        full_prefix = f"web/{prefix}"
        files = store.list_files(prefix=full_prefix)
        paths = [f.key.removeprefix("web/") for f in files]
        return ListResult(files=paths)
