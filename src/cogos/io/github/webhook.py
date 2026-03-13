"""GitHub channel: on-demand webhook receiver with HMAC verification."""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import logging

from aiohttp import web

from cogos.io.base import IOAdapter, IOMode, InboundEvent

logger = logging.getLogger(__name__)

GITHUB_EVENT_MAP = {
    ("issues", "assigned"): "issue.assigned",
    ("issues", "opened"): "issue.opened",
    ("issues", "closed"): "issue.closed",
    ("issue_comment", "created"): "issue.comment",
    ("pull_request", "opened"): "pr.opened",
    ("pull_request", "closed"): "pr.closed",
    ("pull_request", "review_requested"): "pr.review_requested",
    ("pull_request_review", "submitted"): "pr.review",
    ("pull_request_review_comment", "created"): "pr.comment",
    ("check_suite", "completed"): "ci.completed",
    ("check_run", "completed"): "ci.check_completed",
    ("push", None): "push",
}


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac_mod.compare_digest(signature[7:], expected)


class GitHubIO(IOAdapter):
    mode = IOMode.ON_DEMAND

    def __init__(self, name="github", webhook_secret=None, watched_repos=None):
        super().__init__(name)
        self.webhook_secret = webhook_secret
        self.watched_repos = set(watched_repos) if watched_repos else set()
        self._pending_events = []

    async def poll(self):
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def ingest_webhook(self, gh_event, action, payload):
        """Convert raw GitHub webhook to InboundEvent and queue it."""
        event_type = GITHUB_EVENT_MAP.get(
            (gh_event, action), f"github.{gh_event}.{action}"
        )
        sender = payload.get("sender", {}).get("login", "unknown")
        repo_name = payload.get("repository", {}).get("full_name", "")
        content = ""
        external_id = None
        external_url = None

        if gh_event in ("issues", "issue_comment"):
            issue = payload.get("issue", {})
            external_id = f"github:issue:{repo_name}:{issue.get('number')}"
            external_url = issue.get("html_url")
            if gh_event == "issue_comment":
                comment = payload.get("comment", {})
                content = comment.get("body", "")
                external_url = comment.get("html_url", external_url)
            else:
                content = issue.get("body", "")
        elif gh_event in (
            "pull_request",
            "pull_request_review",
            "pull_request_review_comment",
        ):
            pr = payload.get("pull_request", {})
            external_id = f"github:pr:{repo_name}:{pr.get('number')}"
            external_url = pr.get("html_url")
            if gh_event == "pull_request_review_comment":
                comment = payload.get("comment", {})
                content = comment.get("body", "")
                external_url = comment.get("html_url", external_url)
            elif gh_event == "pull_request_review":
                review = payload.get("review", {})
                content = review.get("body", "")
            else:
                content = pr.get("body", "")
        elif gh_event in ("check_suite", "check_run"):
            conclusion = payload.get("conclusion", "")
            content = f"CI {gh_event}: {conclusion}"
            if conclusion == "failure":
                event_type = "ci.failure"

        event = InboundEvent(
            channel="github",
            event_type=event_type,
            payload=payload,
            raw_content=content or "",
            author=sender,
            external_id=external_id,
            external_url=external_url,
        )
        self._pending_events.append(event)
        return event

    async def handle_webhook(self, request):
        body = await request.read()
        if self.webhook_secret:
            sig = request.headers.get("X-Hub-Signature-256", "")
            if not verify_signature(body, sig, self.webhook_secret):
                return web.Response(status=403, text="Invalid signature")
        gh_event = request.headers.get("X-GitHub-Event", "")
        if gh_event == "ping":
            return web.Response(text="pong")
        try:
            payload = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")
        action = payload.get("action")
        repo_name = payload.get("repository", {}).get("full_name", "")
        if self.watched_repos and repo_name not in self.watched_repos:
            return web.Response(text="ignored")
        self.ingest_webhook(gh_event, action, payload)
        return web.Response(text="ok")

    def add_event(self, event):
        self._pending_events.append(event)
