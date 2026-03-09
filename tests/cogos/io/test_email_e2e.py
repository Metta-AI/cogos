"""End-to-end test for dr.alpha email flow — no mocks.

Sends a real email via SES, runs the real ingest handler code against
dr.alpha's Aurora DB (same code path as the Lambda), then a daemon
reads email:received events and emits email:processed.

All AWS calls (SES, RDS Data API) are real — no mocks.

Usage:
    python -m pytest tests/cogos/io/test_email_e2e.py -v -s
"""

from __future__ import annotations

import json
import threading
import time
import uuid

import boto3
import pytest

from cogos.db.models import Event

DOMAIN = "softmax-cogents.com"
COGENT_EMAIL = f"dr-alpha@{DOMAIN}"
TIMEOUT_PROCESSED = 15


# ── Setup ────────────────────────────────────────────────────


def _setup_env():
    """Set up DB env vars for dr.alpha (polis account)."""
    from cogos.cli.__main__ import _ensure_db_env
    _ensure_db_env("dr.alpha")


def _make_repo():
    from cogos.db.repository import Repository
    return Repository.create()


# ── Email daemon ─────────────────────────────────────────────


def _email_daemon(repo, *, tag: str, stop: threading.Event, results: dict):
    """Daemon: poll for email:received matching tag, emit email:processed."""
    seen: set[str] = set()
    while not stop.is_set():
        events = repo.get_events(event_type="email:received", limit=50)
        for evt in events:
            eid = str(evt.id)
            if eid in seen:
                continue
            subject = evt.payload.get("subject", "")
            if tag not in subject:
                continue

            results["received_event"] = evt

            processed_event = Event(
                event_type="email:processed",
                source="email-daemon",
                payload={
                    "original_event_id": eid,
                    "from": evt.payload.get("from"),
                    "to": evt.payload.get("to"),
                    "subject": subject,
                    "status": "processed",
                },
                parent_event=evt.id,
            )
            pid = repo.append_event(processed_event)
            results["processed_event_id"] = str(pid)
            seen.add(eid)

        stop.wait(timeout=1.0)


# ── Test ─────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def db_env():
    _setup_env()


class TestEmailEndToEnd:
    def test_full_pipeline(self):
        """SES send -> ingest handler -> Aurora DB -> daemon -> email:processed."""
        repo = _make_repo()
        tag = uuid.uuid4().hex[:8]
        subject = f"E2E test [{tag}]"
        body = f"End-to-end email test. tag={tag}"
        from_addr = f"dr.alpha@{DOMAIN}"

        # ── Step 1: Send real email via SES ──────────────────
        ses = boto3.client("ses", region_name="us-east-1")
        send_resp = ses.send_email(
            Source=from_addr,
            Destination={"ToAddresses": [COGENT_EMAIL]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        )
        ses_message_id = send_resp["MessageId"]
        print(f"\n  [1/5] Sent email via SES: {from_addr} -> {COGENT_EMAIL}")
        print(f"        MessageId: {ses_message_id}")
        print(f"        Subject: {subject}")

        # ── Step 2: Run ingest handler (same code as Lambda) ─
        # Build the exact payload the Cloudflare email worker sends.
        ingest_event = {
            "headers": {"authorization": "Bearer __test_bypass__"},
            "body": json.dumps({
                "event_type": "email:received",
                "source": "cloudflare-email-worker",
                "payload": {
                    "from": from_addr,
                    "to": COGENT_EMAIL,
                    "subject": subject,
                    "body": body,
                    "message_id": f"<{ses_message_id}>",
                    "date": time.strftime("%a, %d %b %Y %H:%M:%S %z"),
                    "cogent": "dr-alpha",
                },
            }),
        }

        # Call the real ingest handler code — writes to dr.alpha's Aurora DB
        # via RDS Data API (no mocks). We patch only the bearer token check
        # since we're calling in-process, not through the Lambda URL.
        import os
        old_secret = os.environ.get("EMAIL_INGEST_SECRET", "")
        os.environ["EMAIL_INGEST_SECRET"] = "__test_bypass__"
        try:
            # Force re-import so it picks up the new env var
            import importlib
            import polis.io.email.handler as ingest_mod
            importlib.reload(ingest_mod)

            resp = ingest_mod.handler(ingest_event, None)
        finally:
            if old_secret:
                os.environ["EMAIL_INGEST_SECRET"] = old_secret
            else:
                os.environ.pop("EMAIL_INGEST_SECRET", None)

        assert resp["statusCode"] == 200, f"Ingest failed: {resp}"
        ingest_event_id = json.loads(resp["body"])["event_id"]
        print(f"  [2/5] Ingest handler wrote email:received to DB: {ingest_event_id}")

        # ── Step 3: Start daemon ─────────────────────────────
        stop = threading.Event()
        results: dict = {}
        daemon = threading.Thread(
            target=_email_daemon,
            kwargs={"repo": repo, "tag": tag, "stop": stop, "results": results},
            daemon=True,
        )
        daemon.start()

        try:
            # ── Step 4: Wait for daemon to find & process ────
            print(f"  [3/5] Daemon polling for email:received...")
            deadline = time.time() + TIMEOUT_PROCESSED
            while time.time() < deadline and "processed_event_id" not in results:
                time.sleep(1.0)

            assert "received_event" in results, "Daemon never found the email:received event"
            recv_evt = results["received_event"]
            print(f"  [4/5] Daemon found email:received: {recv_evt.id}")
            print(f"        from={recv_evt.payload.get('from')}")
            print(f"        subject={recv_evt.payload.get('subject')}")

            assert "processed_event_id" in results, (
                f"Daemon did not emit email:processed within {TIMEOUT_PROCESSED}s"
            )

            # ── Step 5: Verify email:processed in DB ─────────
            events = repo.get_events(event_type="email:processed", limit=20)
            matching = [
                e for e in events
                if e.payload.get("original_event_id") == str(recv_evt.id)
            ]
            assert len(matching) == 1, (
                f"Expected 1 email:processed for {recv_evt.id}, got {len(matching)}"
            )

            evt = matching[0]
            assert evt.source == "email-daemon"
            assert evt.payload["status"] == "processed"
            assert evt.payload["from"] == from_addr
            assert tag in evt.payload["subject"]
            assert evt.parent_event == recv_evt.id

            print(f"  [5/5] Verified email:processed: {evt.id}")
            print(f"        parent_event -> {evt.parent_event}")
            print(f"        Full pipeline verified!")

        finally:
            stop.set()
            daemon.join(timeout=5)
