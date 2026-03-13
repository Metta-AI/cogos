import hashlib
import hmac

from cogos.io.base import IOMode, InboundEvent
from cogos.io.github import GitHubIO
from cogos.io.github.webhook import verify_signature


class TestGitHubSignature:
    def test_valid_signature(self):
        secret = "test-secret"
        payload = b'{"action":"opened"}'
        sig = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        assert verify_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        assert verify_signature(b"payload", "sha256=invalid", "secret") is False

    def test_missing_prefix(self):
        assert verify_signature(b"payload", "invalid", "secret") is False


class TestGitHubIO:
    def test_mode_is_on_demand(self):
        ch = GitHubIO(name="github")
        assert ch.mode == IOMode.ON_DEMAND

    async def test_poll_returns_queued_events(self):
        ch = GitHubIO(name="github")
        event = InboundEvent(source="github", message_type="push", payload={})
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].message_type == "push"

    async def test_poll_drains_queue(self):
        ch = GitHubIO(name="github")
        for i in range(3):
            ch.add_event(
                InboundEvent(
                    source="github", message_type=f"event.{i}", payload={}
                )
            )
        events = await ch.poll()
        assert len(events) == 3
        events = await ch.poll()
        assert len(events) == 0

    def test_ingest_issue_assigned(self):
        ch = GitHubIO(name="github")
        event = ch.ingest_webhook(
            "issues",
            "assigned",
            {
                "sender": {"login": "testuser"},
                "repository": {"full_name": "org/repo"},
                "issue": {
                    "number": 42,
                    "body": "Fix this",
                    "html_url": "https://github.com/org/repo/issues/42",
                },
            },
        )
        assert event.message_type == "issue.assigned"
        assert event.author == "testuser"
        assert event.external_id == "github:issue:org/repo:42"

    def test_ingest_ci_failure(self):
        ch = GitHubIO(name="github")
        event = ch.ingest_webhook(
            "check_suite",
            "completed",
            {
                "sender": {"login": "github-actions"},
                "repository": {"full_name": "org/repo"},
                "conclusion": "failure",
            },
        )
        assert event.message_type == "ci.failure"

    def test_ingest_unknown_event(self):
        ch = GitHubIO(name="github")
        event = ch.ingest_webhook(
            "unknown_event",
            "triggered",
            {
                "sender": {"login": "bot"},
                "repository": {"full_name": "org/repo"},
            },
        )
        assert event.message_type == "github.unknown_event.triggered"
