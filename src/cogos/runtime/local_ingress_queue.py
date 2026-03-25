"""In-memory SQS mock for local development.

In production, channel message delivery nudges the SQS ingress queue so
the ingress Lambda dispatches the target process immediately — no need to
wait for the next EventBridge tick.

Locally, there is no SQS.  This module provides a lightweight, thread-safe
in-memory queue that the local dispatcher can poll between ticks, giving
near-instant dispatch for event-driven workloads.

Usage:
    queue = LocalIngressQueue()

    repo = SqliteRepository(
        data_dir=...,
        ingress_queue_url="local://ingress",
        nudge_callback=queue.send,
    )

    # In the dispatcher loop, drain between ticks:
    for msg in queue.drain():
        dispatch(msg["process_id"])
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any

logger = logging.getLogger(__name__)


class LocalIngressQueue:
    """Thread-safe in-memory mock of the SQS ingress FIFO queue.

    Messages are simple dicts with at least a ``source`` key.  When a
    ``process_id`` is present the dispatcher should fast-path that process
    instead of relying on weighted random selection.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._event = threading.Event()

    # ── Producer (called by Repository._nudge_ingress) ────

    def send(self, queue_url: str, body: str) -> None:
        """Enqueue a nudge message.  Signature matches the prod nudge callback."""
        try:
            msg = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            msg = {"source": "unknown", "raw": body}
        try:
            self._queue.put_nowait(msg)
            self._event.set()
            logger.debug("local ingress: enqueued %s", msg)
        except queue.Full:
            logger.warning("local ingress queue full — dropping nudge %s", msg)

    # ── Consumer (called by local dispatcher) ─────────────

    def drain(self, max_messages: int = 50) -> list[dict[str, Any]]:
        """Return up to *max_messages* from the queue without blocking."""
        messages: list[dict[str, Any]] = []
        for _ in range(max_messages):
            try:
                messages.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def wait(self, timeout: float = 1.0) -> dict[str, Any] | None:
        """Block up to *timeout* seconds for a single message.

        Returns ``None`` on timeout — useful for interruptible sleep in
        the dispatcher loop.
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_for_nudge(self, timeout: float = 1.0) -> bool:
        """Block until a nudge arrives or *timeout* elapses.

        Returns True if a nudge arrived, False on timeout.  Use this
        instead of ``time.sleep()`` in the dispatcher loop so that
        processes are dispatched immediately when they become runnable.
        """
        triggered = self._event.wait(timeout=timeout)
        self._event.clear()
        return triggered

    @property
    def pending(self) -> int:
        return self._queue.qsize()
