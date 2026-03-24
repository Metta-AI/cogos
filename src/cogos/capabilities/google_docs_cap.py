"""Google Docs/Drive capability — create, read, and format Google Docs."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from cogos.capabilities._secrets_helper import fetch_secret
from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except ImportError:
    service_account = None  # type: ignore[assignment]
    build = None  # type: ignore[assignment]


# ── IO Models ────────────────────────────────────────────────


class DocResult(BaseModel):
    id: str
    name: str
    url: str = ""


class DocContent(BaseModel):
    id: str
    title: str = ""
    body_text: str = ""


class FileEntry(BaseModel):
    id: str
    name: str
    mime_type: str = ""
    created_time: str = ""


class CommentEntry(BaseModel):
    id: str
    content: str = ""
    author: str = ""
    created_time: str = ""
    resolved: bool = False
    quoted_text: str = ""
    replies: list[dict] = []


class BatchUpdateResult(BaseModel):
    doc_id: str
    replies_count: int = 0


class GoogleDocsError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────

SECRET_KEY = "cogent/{cogent}/google_service_account"
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


class GoogleDocsCapability(Capability):
    """Google Docs and Drive access.

    Usage:
        google_docs.create_doc("Report Title", "folder_id")
        google_docs.list_files("folder_id")
    """

    ALL_OPS = {
        "create_doc",
        "batch_update",
        "get_doc",
        "list_files",
        "get_comments",
        "update_comment",
    }

    def __init__(self, repo, process_id, **kwargs) -> None:
        super().__init__(repo, process_id, **kwargs)
        self._creds = None
        self._docs_service = None
        self._drive_service = None

    def _get_creds(self):
        if self._creds is None:
            raw = fetch_secret(SECRET_KEY, secrets_provider=self._secrets_provider)
            if isinstance(raw, str):
                sa_info = json.loads(raw)
            else:
                sa_info = raw
            # Get impersonation subject if configured
            subject = None
            try:
                subject = fetch_secret(
                    "cogent/{cogent}/google_impersonate_user",
                    secrets_provider=self._secrets_provider,
                )
            except (RuntimeError, KeyError):
                pass
            creds = service_account.Credentials.from_service_account_info(
                sa_info, scopes=SCOPES,
            )
            if subject:
                creds = creds.with_subject(subject)
            self._creds = creds
        return self._creds

    def _get_docs(self):
        if self._docs_service is None:
            self._docs_service = build("docs", "v1", credentials=self._get_creds())
        return self._docs_service

    def _get_drive(self):
        if self._drive_service is None:
            self._drive_service = build("drive", "v3", credentials=self._get_creds())
        return self._drive_service

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        for key in ("ops", "folders"):
            old = existing.get(key)
            new = requested.get(key)
            if old is not None and new is not None:
                result[key] = [v for v in old if v in new]
            elif old is not None:
                result[key] = old
            elif new is not None:
                result[key] = new
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")

    def create_doc(
        self, name: str, folder_id: str | None = None,
    ) -> DocResult | GoogleDocsError:
        """Create a new Google Doc, optionally in a specific Drive folder."""
        self._check("create_doc")
        try:
            drive = self._get_drive()
            metadata: dict = {
                "name": name,
                "mimeType": "application/vnd.google-apps.document",
            }
            if folder_id:
                metadata["parents"] = [folder_id]
            result = drive.files().create(body=metadata, fields="id,name").execute()
            doc_id = result["id"]
            return DocResult(
                id=doc_id,
                name=result.get("name", name),
                url=f"https://docs.google.com/document/d/{doc_id}/edit",
            )
        except Exception as exc:
            return GoogleDocsError(error=str(exc))

    def batch_update(
        self, doc_id: str, requests: list[dict],
    ) -> BatchUpdateResult | GoogleDocsError:
        """Apply a list of batchUpdate requests to a Google Doc."""
        self._check("batch_update")
        try:
            docs = self._get_docs()
            result = docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()
            replies = result.get("replies", [])
            return BatchUpdateResult(doc_id=doc_id, replies_count=len(replies))
        except Exception as exc:
            return GoogleDocsError(error=str(exc))

    def get_doc(self, doc_id: str) -> DocContent | GoogleDocsError:
        """Read a Google Doc and return its text content."""
        self._check("get_doc")
        try:
            docs = self._get_docs()
            doc = docs.documents().get(documentId=doc_id).execute()
            title = doc.get("title", "")
            # Extract body text
            text_parts = []
            body = doc.get("body", {})
            for elem in body.get("content", []):
                paragraph = elem.get("paragraph")
                if paragraph:
                    for run in paragraph.get("elements", []):
                        text_run = run.get("textRun")
                        if text_run:
                            text_parts.append(text_run.get("content", ""))
            return DocContent(
                id=doc_id,
                title=title,
                body_text="".join(text_parts),
            )
        except Exception as exc:
            return GoogleDocsError(error=str(exc))

    def list_files(
        self,
        folder_id: str,
        query: str = "",
        order_by: str = "createdTime desc",
        limit: int = 10,
    ) -> list[FileEntry] | GoogleDocsError:
        """List files in a Google Drive folder."""
        self._check("list_files")
        try:
            drive = self._get_drive()
            q = f"'{folder_id}' in parents and trashed = false"
            if query:
                q += f" and {query}"
            result = drive.files().list(
                q=q,
                orderBy=order_by,
                pageSize=limit,
                fields="files(id,name,mimeType,createdTime)",
            ).execute()
            files = result.get("files", [])
            return [
                FileEntry(
                    id=f["id"],
                    name=f.get("name", ""),
                    mime_type=f.get("mimeType", ""),
                    created_time=f.get("createdTime", ""),
                )
                for f in files
            ]
        except Exception as exc:
            return GoogleDocsError(error=str(exc))

    def get_comments(
        self, file_id: str, include_resolved: bool = False,
    ) -> list[CommentEntry] | GoogleDocsError:
        """List comments on a Google Drive file."""
        self._check("get_comments")
        try:
            drive = self._get_drive()
            result = drive.comments().list(
                fileId=file_id,
                fields="comments(id,content,author,replies,resolved,createdTime,quotedFileContent)",
                includeDeleted=False,
            ).execute()
            comments = result.get("comments", [])
            entries = []
            for c in comments:
                if not include_resolved and c.get("resolved", False):
                    continue
                author_obj = c.get("author", {})
                quoted = c.get("quotedFileContent", {})
                replies_raw = c.get("replies", [])
                replies = [
                    {
                        "content": r.get("content", ""),
                        "author": r.get("author", {}).get("displayName", ""),
                        "created_time": r.get("createdTime", ""),
                    }
                    for r in replies_raw
                ]
                entries.append(CommentEntry(
                    id=c["id"],
                    content=c.get("content", ""),
                    author=author_obj.get("displayName", ""),
                    created_time=c.get("createdTime", ""),
                    resolved=c.get("resolved", False),
                    quoted_text=quoted.get("value", ""),
                    replies=replies,
                ))
            return entries
        except Exception as exc:
            return GoogleDocsError(error=str(exc))

    def update_comment(
        self, file_id: str, comment_id: str, resolved: bool = True,
    ) -> dict | GoogleDocsError:
        """Resolve or unresolve a comment on a Google Drive file."""
        self._check("update_comment")
        try:
            drive = self._get_drive()
            drive.comments().update(
                fileId=file_id,
                commentId=comment_id,
                body={"resolved": resolved},
                fields="id,resolved",
            ).execute()
            return {"ok": True, "comment_id": comment_id, "resolved": resolved}
        except Exception as exc:
            return GoogleDocsError(error=str(exc))

    def __repr__(self) -> str:
        return (
            "<GoogleDocsCapability create_doc() batch_update() get_doc() "
            "list_files() get_comments() update_comment()>"
        )
