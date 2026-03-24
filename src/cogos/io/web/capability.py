from __future__ import annotations

import logging
import os

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


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


class WebCapability(Capability):
    """Publish static files to the web and respond to HTTP requests."""

    ALL_OPS = {"publish", "unpublish", "respond", "list", "url"}

    def __init__(self, repo, process_id, **kwargs):
        super().__init__(repo, process_id, **kwargs)
        self._pending_responses: dict[str, dict] = {}

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
        content_encoding: str | None = None,
    ) -> PublishResult | WebError:
        """Publish a static file at the given path. Supports base64 encoding."""
        if not path:
            return WebError(error="'path' is required")
        if not content:
            return WebError(error="'content' is required")
        if content_encoding is not None and content_encoding != "base64":
            return WebError(error="Unsupported encoding: only 'base64' is allowed")
        self._check("publish", path=path)

        store = FileStore(self.repo)
        key = f"web/{path}"
        stored_content = f"base64:{content}" if content_encoding == "base64" else content
        result = store.upsert(key, stored_content, source="web")

        if result is None:
            existing = store.get(key)
            if existing:
                active = self.repo.get_active_file_version(existing.id)
                return PublishResult(path=path, version=active.version if active else 1, created=False)
            return WebError(error="failed to publish")

        from cogos.db.models import File

        if isinstance(result, File):
            return PublishResult(path=path, version=1, created=True)
        return PublishResult(path=path, version=result.version, created=False)

    def unpublish(self, path: str) -> UnpublishResult | WebError:
        """Remove a published file."""
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
        """Respond to an inbound HTTP request."""
        if not request_id:
            return WebError(error="'request_id' is required")
        self._check("respond")

        if request_id in self._pending_responses:
            logger.debug("Duplicate respond() for request_id=%s, ignoring", request_id)
        else:
            entry: dict = {"status": status, "body": body}
            if headers:
                entry["headers"] = headers
            self._pending_responses[request_id] = entry

        return WebResponse(request_id=request_id, status=self._pending_responses[request_id]["status"])

    def get_pending_response(self, request_id: str) -> dict | None:
        """Retrieve and consume a pending HTTP response by request_id."""
        return self._pending_responses.pop(request_id, None)

    def list(self, prefix: str = "") -> ListResult | WebError:
        """List published file paths."""
        self._check("list")

        store = FileStore(self.repo)
        full_prefix = f"web/{prefix}"
        files = store.list_files(prefix=full_prefix)
        paths = [f.key.removeprefix("web/") for f in files]
        return ListResult(files=paths)

    def url(self, path: str = "") -> str:
        """Return the public URL for a published static file or directory."""
        self._check("url")

        base_url = self._static_base_url()
        normalized = path.strip().lstrip("/")
        if not normalized:
            return base_url
        return f"{base_url}/{normalized}"

    def _static_base_url(self) -> str:
        override = (os.environ.get("WEB_BASE_URL") or "").strip().rstrip("/")
        if override:
            return override

        if os.environ.get("USE_LOCAL_DB") == "1":
            frontend_port = (os.environ.get("DASHBOARD_FE_PORT") or "").strip()
            backend_port = (os.environ.get("DASHBOARD_BE_PORT") or "").strip()
            if frontend_port:
                return f"http://localhost:{frontend_port}/web/static"
            if backend_port:
                return f"http://localhost:{backend_port}/web/static"

        cogent_name = (os.environ.get("COGENT") or "").strip()
        safe_name = cogent_name.replace(".", "-") if cogent_name else "local"
        domain = self._get_web_domain()
        return f"https://{safe_name}.{domain}/web/static"

    def _get_web_domain(self) -> str:
        """Read web domain from cogtainer secrets."""
        cogtainer = (os.environ.get("COGTAINER") or "").strip()
        if self._secrets_provider and cogtainer:
            try:
                return self._secrets_provider.get_secret(f"cogtainer/{cogtainer}/web/domain")
            except Exception:
                pass
        return ""
