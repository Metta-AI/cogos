"""Google Docs capability — create, read, and update Google Docs."""

from __future__ import annotations

import logging
from typing import Union

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.io.google.auth import get_service

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class DocInfo(BaseModel):
    id: str
    title: str
    url: str


class DocContent(BaseModel):
    id: str
    title: str
    content: str


class DocsError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────


class DocsCapability(Capability):
    """Create, read, and update Google Docs.

    Usage:
        docs.create("My Document", "Hello, world!")
        docs.read("<document_id>")
        docs.update("<document_id>", "New content")
    """

    ALL_OPS = {"create", "read", "update"}

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

        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed by scope")

    def create(
        self, title: str, content: str = ""
    ) -> Union[DocInfo, DocsError]:
        """Create a new Google Doc.

        Args:
            title: The document title.
            content: Optional initial text content.

        Returns:
            DocInfo with the new document's id, title, and url.
        """
        try:
            self._check("create")
            svc = get_service("docs", "v1", self._secrets_provider)

            body = {"title": title}
            doc = svc.documents().create(body=body).execute()
            doc_id = doc["documentId"]

            if content:
                requests = [
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": content,
                        }
                    }
                ]
                svc.documents().batchUpdate(
                    documentId=doc_id, body={"requests": requests}
                ).execute()

            return DocInfo(
                id=doc_id,
                title=doc.get("title", title),
                url=f"https://docs.google.com/document/d/{doc_id}",
            )
        except PermissionError:
            raise
        except Exception as e:
            logger.exception("Failed to create Google Doc")
            return DocsError(error=str(e))

    def read(self, doc_id: str) -> Union[DocContent, DocsError]:
        """Read the plain-text content of a Google Doc.

        Args:
            doc_id: The Google Doc document ID.

        Returns:
            DocContent with the document's id, title, and extracted text.
        """
        try:
            self._check("read")
            svc = get_service("docs", "v1", self._secrets_provider)

            doc = svc.documents().get(documentId=doc_id).execute()

            text_parts: list[str] = []
            for element in doc.get("body", {}).get("content", []):
                paragraph = element.get("paragraph")
                if paragraph:
                    for elem in paragraph.get("elements", []):
                        text_run = elem.get("textRun")
                        if text_run:
                            text_parts.append(text_run.get("content", ""))

            return DocContent(
                id=doc["documentId"],
                title=doc.get("title", ""),
                content="".join(text_parts),
            )
        except PermissionError:
            raise
        except Exception as e:
            logger.exception("Failed to read Google Doc %s", doc_id)
            return DocsError(error=str(e))

    def update(
        self, doc_id: str, content: str
    ) -> Union[DocInfo, DocsError]:
        """Replace the entire content of a Google Doc.

        Deletes existing content and inserts the new text.

        Args:
            doc_id: The Google Doc document ID.
            content: The new text content for the document.

        Returns:
            DocInfo with the updated document's id, title, and url.
        """
        try:
            self._check("update")
            svc = get_service("docs", "v1", self._secrets_provider)

            # Get the current document to find end index.
            doc = svc.documents().get(documentId=doc_id).execute()
            body_content = doc.get("body", {}).get("content", [])

            # The last structural element's endIndex tells us the doc length.
            end_index = 1
            if body_content:
                end_index = body_content[-1].get("endIndex", 1)

            requests: list[dict] = []

            # Delete existing content (index 1 to endIndex-1).
            if end_index > 2:
                requests.append(
                    {
                        "deleteContentRange": {
                            "range": {
                                "startIndex": 1,
                                "endIndex": end_index - 1,
                            }
                        }
                    }
                )

            # Insert new content at index 1.
            if content:
                requests.append(
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": content,
                        }
                    }
                )

            if requests:
                svc.documents().batchUpdate(
                    documentId=doc_id, body={"requests": requests}
                ).execute()

            return DocInfo(
                id=doc_id,
                title=doc.get("title", ""),
                url=f"https://docs.google.com/document/d/{doc_id}",
            )
        except PermissionError:
            raise
        except Exception as e:
            logger.exception("Failed to update Google Doc %s", doc_id)
            return DocsError(error=str(e))

    def __repr__(self) -> str:
        return "<DocsCapability create() read() update()>"
