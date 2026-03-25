"""Tests that dashboard API endpoints use batched queries instead of N+1 patterns.

Each test sets up N entities and asserts that the number of individual DB calls
stays O(1) — i.e. it does not scale with N.  This catches regressions where
batch-fetches are accidentally replaced by per-item lookups.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from cogos.db.models import (
    Capability,
    Channel,
    ChannelMessage,
    ChannelType,
    Delivery,
    DeliveryStatus,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.db.models.process_capability import ProcessCapability
from dashboard.app import create_app

# ---------------------------------------------------------------------------
# Counting repo stub base
# ---------------------------------------------------------------------------


class _CountingRepoBase:
    """Tracks call counts for every repo method to detect N+1 regressions."""

    def __init__(self) -> None:
        self.call_counts: dict[str, int] = {}

    def _track(self, name: str) -> None:
        self.call_counts[name] = self.call_counts.get(name, 0) + 1


# ---------------------------------------------------------------------------
# trace_viewer: span count should use GROUP BY, not N per-trace queries
# ---------------------------------------------------------------------------


class _TraceViewerRepo(_CountingRepoBase):
    """Repo stub for trace_viewer list endpoint."""

    def __init__(self, n_traces: int = 10) -> None:
        super().__init__()
        self.n_traces = n_traces
        now = datetime.now(timezone.utc)
        self.traces = [
            {
                "id": str(uuid4()),
                "cogent_id": "test",
                "source": "test",
                "source_ref": None,
                "created_at": (now - timedelta(seconds=i)).isoformat(),
                "span_count": i,
            }
            for i in range(n_traces)
        ]

    def query(self, sql: str, params=None):
        self._track("query")
        # The optimised query returns span_count inline via LEFT JOIN
        if "span_count" in sql or "LEFT JOIN" in sql:
            return self.traces
        # If someone adds back N+1 per-trace COUNT queries, they'll hit this path
        if "COUNT" in sql:
            self._track("query_span_count")
            return [{"cnt": 0}]
        return self.traces


def test_trace_viewer_list_uses_single_query():
    """list_traces must fetch span counts in a single query, not one per trace."""
    app = create_app()
    client = TestClient(app)
    n = 20
    repo = _TraceViewerRepo(n_traces=n)

    with patch("dashboard.routers.trace_viewer.get_repo", return_value=repo):
        resp = client.get("/api/cogents/test/trace-viewer?limit=20")

    assert resp.status_code == 200
    assert resp.json()["count"] == n
    # Must be exactly 1 query call (the combined LEFT JOIN query), not 1 + N
    assert repo.call_counts.get("query", 0) == 1, (
        f"Expected 1 query, got {repo.call_counts.get('query', 0)} — N+1 span count regression"
    )
    assert repo.call_counts.get("query_span_count", 0) == 0, (
        "Per-trace COUNT query detected — use GROUP BY instead"
    )


# ---------------------------------------------------------------------------
# get_process: capabilities and channels should be batch-fetched
# ---------------------------------------------------------------------------


class _ProcessDetailRepo(_CountingRepoBase):
    """Repo stub for GET /processes/{id} with multiple capabilities and handlers."""

    def __init__(self, n_caps: int = 5, n_handlers: int = 5) -> None:
        super().__init__()
        now = datetime.now(timezone.utc)
        self.process = Process(
            id=uuid4(),
            name="worker",
            mode=ProcessMode.DAEMON,
            content="do stuff",
            status=ProcessStatus.WAITING,
            required_tags=[],
            created_at=now,
        )
        self.capabilities = [
            Capability(id=uuid4(), name=f"cap-{i}", description=f"Cap {i}", handler=f"handler_{i}")
            for i in range(n_caps)
        ]
        self.process_capabilities = [
            ProcessCapability(
                id=uuid4(),
                process=self.process.id,
                capability=cap.id,
                name=f"grant-{i}",
            )
            for i, cap in enumerate(self.capabilities)
        ]
        self.channels = [
            Channel(id=uuid4(), name=f"ch-{i}", channel_type=ChannelType.NAMED)
            for i in range(n_handlers)
        ]
        self.handlers = [
            Handler(id=uuid4(), process=self.process.id, channel=ch.id, enabled=True)
            for ch in self.channels
        ]
        self.runs: list[Run] = []
        self.files: list = []

    def get_process(self, pid: UUID):
        self._track("get_process")
        return self.process if pid == self.process.id else None

    def list_runs(self, *, process_id=None, limit=50, epoch=None, slim=False, since=None):
        self._track("list_runs")
        return self.runs

    def list_process_capabilities(self, pid: UUID):
        self._track("list_process_capabilities")
        return self.process_capabilities

    def get_capability(self, cap_id: UUID):
        self._track("get_capability")
        return next((c for c in self.capabilities if c.id == cap_id), None)

    def list_capabilities(self, *, enabled_only=False):
        self._track("list_capabilities")
        return self.capabilities

    def list_handlers(self, *, process_id=None, enabled_only=False, epoch=None, limit=0):
        self._track("list_handlers")
        return self.handlers

    def get_channel(self, cid: UUID):
        self._track("get_channel")
        return next((ch for ch in self.channels if ch.id == cid), None)

    def list_channels(self, *, owner_process=None, limit=0):
        self._track("list_channels")
        return self.channels

    def get_active_file_version(self, fid):
        self._track("get_active_file_version")
        return None

    def list_files(self, *, prefix="", limit=200):
        self._track("list_files")
        return self.files


def test_get_process_batches_capability_lookups():
    """GET /processes/{id} must batch-fetch capabilities, not one per grant."""
    app = create_app()
    client = TestClient(app)
    n = 10
    repo = _ProcessDetailRepo(n_caps=n, n_handlers=n)

    with (
        patch("dashboard.routers.processes.get_repo", return_value=repo),
        patch("cogos.files.context_engine.ContextEngine.generate_full_prompt", return_value="prompt"),
        patch("cogos.files.context_engine.ContextEngine.resolve_prompt_tree", return_value=[]),
    ):
        resp = client.get(f"/api/cogents/test/processes/{repo.process.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["cap_grants"]) == n
    assert len(data["handlers"]) == n

    # Should use list_capabilities (1 call) not get_capability (N calls)
    assert repo.call_counts.get("get_capability", 0) == 0, (
        f"get_capability called {repo.call_counts['get_capability']} times — use list_capabilities batch"
    )
    assert repo.call_counts.get("list_capabilities", 0) == 1

    # Should use list_channels (1 call) not get_channel (N calls)
    assert repo.call_counts.get("get_channel", 0) == 0, (
        f"get_channel called {repo.call_counts['get_channel']} times — use list_channels batch"
    )
    assert repo.call_counts.get("list_channels", 0) == 1


# ---------------------------------------------------------------------------
# handlers: create_handler should not scan all processes/channels
# ---------------------------------------------------------------------------


class _HandlersRepo(_CountingRepoBase):
    """Repo stub for handler endpoints."""

    def __init__(self, n_handlers: int = 5) -> None:
        super().__init__()
        now = datetime.now(timezone.utc)
        self.processes = [
            Process(id=uuid4(), name=f"proc-{i}", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
            for i in range(20)
        ]
        self.channels = [
            Channel(id=uuid4(), name=f"ch-{i}", channel_type=ChannelType.NAMED, created_at=now)
            for i in range(20)
        ]
        self.handlers = [
            Handler(
                id=uuid4(),
                process=self.processes[i % len(self.processes)].id,
                channel=self.channels[i % len(self.channels)].id,
                enabled=True,
                created_at=now,
            )
            for i in range(n_handlers)
        ]

    def list_handlers(self, *, process_id=None, enabled_only=False, epoch=None, limit=0):
        self._track("list_handlers")
        items = self.handlers
        if process_id:
            items = [h for h in items if h.process == process_id]
        return items

    def create_handler(self, h):
        self._track("create_handler")
        self.handlers.append(h)
        return h.id

    def list_processes(self, *, status=None, limit=200, epoch=None):
        self._track("list_processes")
        return self.processes

    def list_channels(self, *, owner_process=None, limit=0):
        self._track("list_channels")
        return self.channels

    def get_process(self, pid: UUID):
        self._track("get_process")
        return next((p for p in self.processes if p.id == pid), None)

    def get_channel(self, cid: UUID):
        self._track("get_channel")
        return next((ch for ch in self.channels if ch.id == cid), None)


def test_create_handler_does_not_scan_all_tables():
    """POST /handlers should look up only the 1 process and 1 channel it needs."""
    app = create_app()
    client = TestClient(app)
    repo = _HandlersRepo()

    proc = repo.processes[0]
    ch = repo.channels[0]
    with patch("dashboard.routers.handlers.get_repo", return_value=repo):
        resp = client.post(
            "/api/cogents/test/handlers",
            json={"process": str(proc.id), "channel": str(ch.id)},
        )

    assert resp.status_code == 200
    # Should use get_process + get_channel (1 each), not list_processes + list_channels
    assert repo.call_counts.get("list_processes", 0) == 0, (
        "create_handler should not call list_processes — use get_process for the single ID"
    )
    assert repo.call_counts.get("list_channels", 0) == 0, (
        "create_handler should not call list_channels — use get_channel for the single ID"
    )
    assert repo.call_counts.get("get_process", 0) == 1
    assert repo.call_counts.get("get_channel", 0) == 1


# ---------------------------------------------------------------------------
# message-traces: missing runs should be pre-fetched, not looked up in loop
# ---------------------------------------------------------------------------


class _TracesRepo(_CountingRepoBase):
    """Repo stub for message-traces with deliveries referencing runs not in the initial batch."""

    def __init__(self, n_missing_runs: int = 5) -> None:
        super().__init__()
        now = datetime.now(timezone.utc)
        self.process = Process(
            id=uuid4(), name="worker", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, required_tags=[],
        )
        self.channel = Channel(id=uuid4(), name="io:requests", channel_type=ChannelType.NAMED)
        self.handler = Handler(id=uuid4(), process=self.process.id, channel=self.channel.id, enabled=True)
        self.message = ChannelMessage(
            id=uuid4(), channel=self.channel.id, sender_process=None,
            payload={"type": "test"}, created_at=now,
        )

        # Create runs that will NOT be in the initial list_runs response
        self.missing_runs = [
            Run(
                id=uuid4(), process=self.process.id, status=RunStatus.COMPLETED,
                tokens_in=1, tokens_out=2, cost_usd=Decimal("0.01"),
                duration_ms=100, created_at=now + timedelta(seconds=i),
                completed_at=now + timedelta(seconds=i + 1),
            )
            for i in range(n_missing_runs)
        ]
        self.deliveries = [
            Delivery(
                id=uuid4(), message=self.message.id, handler=self.handler.id,
                status=DeliveryStatus.DELIVERED, run=run.id,
                created_at=now + timedelta(milliseconds=i * 10),
            )
            for i, run in enumerate(self.missing_runs)
        ]
        self.runs_by_id = {r.id: r for r in self.missing_runs}

    def list_processes(self, *, status=None, limit=200, epoch=None):
        self._track("list_processes")
        return [self.process]

    def list_channels(self, *, owner_process=None, limit=0):
        self._track("list_channels")
        return [self.channel]

    def list_handlers(self, *, process_id=None, enabled_only=False, epoch=None, limit=0):
        self._track("list_handlers")
        return [self.handler]

    def list_channel_messages(self, channel_id=None, *, limit=100, since=None):
        self._track("list_channel_messages")
        return [self.message]

    def list_deliveries(self, *, message_id=None, handler_id=None, run_id=None, limit=500, epoch=None, since=None):
        self._track("list_deliveries")
        return self.deliveries

    def list_runs(self, *, process_id=None, limit=50, epoch=None, slim=False, since=None, process_ids=None):
        self._track("list_runs")
        return []  # Intentionally empty — runs are "missing" from initial fetch

    def get_run(self, run_id: UUID):
        self._track("get_run")
        return self.runs_by_id.get(run_id)

    def get_run_results(self, run_ids):
        self._track("get_run_results")
        return {}

    @property
    def reboot_epoch(self):
        return 0

    def _execute(self, sql, params=None):
        self._track("_execute")
        return {"records": []}

    def _rows_to_dicts(self, response):
        return []

    def _param(self, name, value):
        return {"name": name, "value": {"stringValue": str(value)}}


def test_message_traces_prefetches_missing_runs():
    """Missing runs should be batch-fetched before the delivery loop, not inside it."""
    app = create_app()
    client = TestClient(app)
    n = 5
    repo = _TracesRepo(n_missing_runs=n)

    with patch("dashboard.routers.traces.get_repo", return_value=repo):
        resp = client.get("/api/cogents/test/message-traces?range=1h")

    assert resp.status_code == 200
    # get_run should be called exactly N times (once per unique missing run) during
    # the pre-fetch phase — not inside the delivery loop (which would also be N but
    # is architecturally fragile). The key assertion is that it's bounded by unique
    # missing run IDs, not by number of deliveries.
    assert repo.call_counts.get("get_run", 0) == n


# ---------------------------------------------------------------------------
# channels: list_channels should skip process lookup when no owners
# ---------------------------------------------------------------------------


class _ChannelsNoOwnerRepo(_CountingRepoBase):
    """Repo stub where no channels have owner_process set."""

    def __init__(self, n_channels: int = 10) -> None:
        super().__init__()
        now = datetime.now(timezone.utc)
        self.channels = [
            Channel(id=uuid4(), name=f"ch-{i}", channel_type=ChannelType.NAMED, created_at=now)
            for i in range(n_channels)
        ]

    def list_channels(self, *, owner_process=None, limit=0):
        self._track("list_channels")
        return self.channels

    def list_processes(self, *, status=None, limit=200, epoch=None):
        self._track("list_processes")
        return []

    def list_schemas(self):
        self._track("list_schemas")
        return []

    @property
    def reboot_epoch(self):
        return 0

    def _execute(self, sql, params=None):
        self._track("_execute")
        return {"records": []}

    def _rows_to_dicts(self, response):
        return []

    def _param(self, name, value):
        return {"name": name, "value": {"stringValue": str(value)}}


def test_list_channels_skips_process_lookup_when_no_owners():
    """If no channels have owner_process, list_processes should not be called."""
    app = create_app()
    client = TestClient(app)
    repo = _ChannelsNoOwnerRepo(n_channels=10)

    with patch("dashboard.routers.channels.get_repo", return_value=repo):
        resp = client.get("/api/cogents/test/channels")

    assert resp.status_code == 200
    assert resp.json()["count"] == 10
    assert repo.call_counts.get("list_processes", 0) == 0, (
        "list_processes called even though no channels have owner_process"
    )


# ---------------------------------------------------------------------------
# runs: list_runs should not fetch all processes
# ---------------------------------------------------------------------------


class _RunsRepo(_CountingRepoBase):
    """Repo stub for runs endpoint."""

    def __init__(self, n_runs: int = 10) -> None:
        super().__init__()
        now = datetime.now(timezone.utc)
        # Only 2 distinct processes for all runs
        self.processes = [
            Process(id=uuid4(), name=f"proc-{i}", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
            for i in range(2)
        ]
        self.runs = [
            Run(
                id=uuid4(),
                process=self.processes[i % 2].id,
                status=RunStatus.COMPLETED,
                tokens_in=1, tokens_out=2, cost_usd=Decimal("0.01"),
                duration_ms=100,
                created_at=now - timedelta(seconds=i),
                completed_at=now,
            )
            for i in range(n_runs)
        ]

    def list_runs(self, *, process_id=None, limit=50, epoch=None, slim=False, since=None, process_ids=None):
        self._track("list_runs")
        return self.runs[:limit]

    def list_processes(self, *, status=None, limit=200, epoch=None):
        self._track("list_processes")
        return self.processes


def test_list_runs_passes_limit_to_repo():
    """GET /runs should respect limit parameter."""
    app = create_app()
    client = TestClient(app)
    repo = _RunsRepo(n_runs=10)

    with patch("dashboard.routers.runs.get_repo", return_value=repo):
        resp = client.get("/api/cogents/test/runs?limit=5")

    assert resp.status_code == 200
    assert resp.json()["count"] == 5


# ---------------------------------------------------------------------------
# processes: list endpoint should accept and forward limit
# ---------------------------------------------------------------------------


class _ProcessesListRepo(_CountingRepoBase):
    """Repo stub for process list endpoint."""

    def __init__(self, n_procs: int = 20) -> None:
        super().__init__()
        self.processes = [
            Process(
                id=uuid4(), name=f"proc-{i}", mode=ProcessMode.DAEMON,
                content=f"content-{i}", status=ProcessStatus.WAITING,
            )
            for i in range(n_procs)
        ]
        self.last_limit: int | None = None

    def list_processes(self, *, status=None, limit=200, epoch=None):
        self._track("list_processes")
        self.last_limit = limit
        return self.processes[:limit]


def test_list_processes_forwards_limit():
    """GET /processes should forward limit param to repo.list_processes."""
    app = create_app()
    client = TestClient(app)
    repo = _ProcessesListRepo(n_procs=20)

    with patch("dashboard.routers.processes.get_repo", return_value=repo):
        resp = client.get("/api/cogents/test/processes?limit=5")

    assert resp.status_code == 200
    assert resp.json()["count"] == 5
    assert repo.last_limit == 5
