from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterator, Protocol, runtime_checkable
from uuid import UUID

from cogos.db.models import (
    Capability,
    Channel,
    ChannelMessage,
    CogosOperation,
    Cron,
    Delivery,
    Executor,
    ExecutorStatus,
    ExecutorToken,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessStatus,
    Resource,
    Run,
    RunStatus,
    Schema,
    Span,
    SpanEvent,
)
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild
from cogos.db.models.trace import RequestTrace, Trace
from cogos.db.models.wait_condition import WaitCondition


@runtime_checkable
class RepositoryProtocol(Protocol):

    # ── Epoch ────────────────────────────────────────────────

    @property
    def reboot_epoch(self) -> int: ...

    def increment_epoch(self) -> int: ...

    # ── Batch ────────────────────────────────────────────────

    @contextmanager
    def batch(self) -> Iterator[None]:
        yield

    # ── Raw SQL ──────────────────────────────────────────────

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]: ...

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int: ...

    # ── Bulk clear ───────────────────────────────────────────

    def clear_all(self) -> None: ...

    def clear_config(self) -> None: ...

    def delete_files_by_prefixes(self, prefixes: list[str]) -> int: ...

    # ── Operations ───────────────────────────────────────────

    def add_operation(self, op: CogosOperation) -> UUID: ...

    def list_operations(self, limit: int = 50) -> list[CogosOperation]: ...

    # ── Processes ────────────────────────────────────────────

    def upsert_process(self, p: Process) -> UUID: ...

    def get_process(self, process_id: UUID) -> Process | None: ...

    def get_process_by_name(self, name: str) -> Process | None: ...

    def list_processes(
        self, *, status: ProcessStatus | None = None, limit: int = 200, epoch: int | None = None,
    ) -> list[Process]: ...

    def try_transition_process(
        self, process_id: UUID, from_status: ProcessStatus, to_status: ProcessStatus,
    ) -> bool: ...

    def update_process_status(self, process_id: UUID, status: ProcessStatus) -> bool: ...

    def delete_process(self, process_id: UUID) -> bool: ...

    def get_runnable_processes(self, limit: int = 50) -> list[Process]: ...

    def increment_retry(self, process_id: UUID) -> bool: ...

    # ── Wait Conditions ──────────────────────────────────────

    def create_wait_condition(self, wc: WaitCondition) -> UUID: ...

    def get_pending_wait_condition_for_process(self, process_id: UUID) -> WaitCondition | None: ...

    def remove_from_pending(self, wc_id: UUID, child_pid: str) -> list[str]: ...

    def resolve_wait_condition(self, wc_id: UUID) -> None: ...

    def resolve_wait_conditions_for_process(self, process_id: UUID) -> None: ...

    # ── Process Capabilities ─────────────────────────────────

    def create_process_capability(self, pc: ProcessCapability) -> UUID: ...

    def list_process_capabilities(self, process_id: UUID) -> list[ProcessCapability]: ...

    def delete_process_capability(self, pc_id: UUID) -> bool: ...

    def list_processes_for_capability(self, capability_id: UUID) -> list[dict]: ...

    # ── Handlers ─────────────────────────────────────────────

    def create_handler(self, h: Handler) -> UUID: ...

    def list_handlers(
        self, *, process_id: UUID | None = None, enabled_only: bool = False, epoch: int | None = None,
    ) -> list[Handler]: ...

    def delete_handler(self, handler_id: UUID) -> bool: ...

    def match_handlers(self, event_type: str) -> list[Handler]: ...

    def match_handlers_by_channel(self, channel_id: UUID) -> list[Handler]: ...

    # ── Deliveries ───────────────────────────────────────────

    def create_delivery(self, ed: Delivery) -> tuple[UUID, bool]: ...

    def get_pending_deliveries(self, process_id: UUID) -> list[Delivery]: ...

    def list_deliveries(
        self,
        *,
        message_id: UUID | None = None,
        handler_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 500,
        epoch: int | None = None,
    ) -> list[Delivery]: ...

    def has_pending_deliveries(self, process_id: UUID) -> bool: ...

    def mark_delivered(self, delivery_id: UUID, run_id: UUID) -> bool: ...

    def mark_queued(self, delivery_id: UUID, run_id: UUID) -> bool: ...

    def requeue_delivery(self, delivery_id: UUID) -> bool: ...

    def mark_run_deliveries_delivered(self, run_id: UUID) -> int: ...

    def rollback_dispatch(
        self,
        process_id: UUID,
        run_id: UUID,
        delivery_id: UUID | None = None,
        *,
        error: str | None = None,
    ) -> None: ...

    def get_latest_delivery_time(self, handler_id: UUID) -> Any: ...

    # ── Cron Rules ───────────────────────────────────────────

    def upsert_cron(self, c: Cron) -> UUID: ...

    def list_cron_rules(self, *, enabled_only: bool = False) -> list[Cron]: ...

    def delete_cron(self, cron_id: UUID) -> bool: ...

    def update_cron_enabled(self, cron_id: UUID, enabled: bool) -> bool: ...

    # ── Files ────────────────────────────────────────────────

    def insert_file(self, f: File) -> UUID: ...

    def get_file_by_key(self, key: str) -> File | None: ...

    def get_file_by_id(self, file_id: UUID) -> File | None: ...

    def list_files(self, *, prefix: str | None = None, limit: int = 200) -> list[File]: ...

    def grep_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 100,
    ) -> list[tuple[str, str]]: ...

    def glob_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 200,
    ) -> list[str]: ...

    def update_file_includes(self, file_id: UUID, includes: list[str]) -> bool: ...

    def delete_file(self, file_id: UUID) -> bool: ...

    def bulk_upsert_files(
        self,
        files: list[tuple[str, str, str, list[str]]],
        *,
        batch_size: int = 100,
    ) -> int: ...

    # ── File Versions ────────────────────────────────────────

    def insert_file_version(self, fv: FileVersion) -> None: ...

    def get_active_file_version(self, file_id: UUID) -> FileVersion | None: ...

    def get_max_file_version(self, file_id: UUID) -> int: ...

    def list_file_versions(self, file_id: UUID) -> list[FileVersion]: ...

    def set_active_file_version(self, file_id: UUID, version: int) -> None: ...

    def update_file_version_content(self, file_id: UUID, version: int, content: str) -> bool: ...

    def delete_file_version(self, file_id: UUID, version: int) -> bool: ...

    # ── Capabilities ─────────────────────────────────────────

    def upsert_capability(self, cap: Capability) -> UUID: ...

    def get_capability(self, cap_id: UUID) -> Capability | None: ...

    def get_capability_by_name(self, name: str) -> Capability | None: ...

    def get_capability_by_handler(self, handler: str) -> Capability | None: ...

    def list_capabilities(self, *, enabled_only: bool = False) -> list[Capability]: ...

    def search_capabilities(self, query: str, *, process_id: UUID | None = None) -> list[Capability]: ...

    # ── Resources ────────────────────────────────────────────

    def upsert_resource(self, resource: Resource) -> str: ...

    def list_resources(self) -> list[Resource]: ...

    # ── Runs ─────────────────────────────────────────────────

    def create_run(self, run: Run) -> UUID: ...

    def complete_run(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: Decimal = Decimal("0"),
        duration_ms: int | None = None,
        error: str | None = None,
        model_version: str | None = None,
        result: dict | None = None,
        snapshot: dict | None = None,
        scope_log: list[dict] | None = None,
    ) -> bool: ...

    def timeout_stale_runs(self, max_age_ms: int = 900_000) -> int: ...

    def get_run(self, run_id: UUID) -> Run | None: ...

    def list_recent_failed_runs(self, max_age_ms: int = 120_000) -> list[Run]: ...

    def update_run_metadata(self, run_id: UUID, metadata: dict) -> None: ...

    def list_runs(
        self,
        *,
        process_id: UUID | None = None,
        process_ids: list[UUID] | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
        epoch: int | None = None,
        slim: bool = False,
    ) -> list[Run]: ...

    def list_file_mutations(self, run_id: UUID) -> list[dict]: ...

    def list_runs_by_process_glob(
        self,
        name_pattern: str,
        *,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[Run]: ...

    # ── Traces ───────────────────────────────────────────────

    def create_trace(self, trace: Trace) -> UUID: ...

    # ── Request Traces & Spans ───────────────────────────────

    def create_request_trace(self, trace: RequestTrace) -> UUID: ...

    def get_request_trace(self, trace_id: UUID) -> RequestTrace | None: ...

    def create_span(self, span: Span) -> UUID: ...

    def complete_span(self, span_id: UUID, *, status: str = "completed", metadata: dict | None = None) -> bool: ...

    def list_spans(self, trace_id: UUID) -> list[Span]: ...

    def create_span_event(self, event: SpanEvent) -> UUID: ...

    def list_span_events(self, span_id: UUID) -> list[SpanEvent]: ...

    def list_span_events_for_trace(self, trace_id: UUID) -> list[SpanEvent]: ...

    # ── Meta ─────────────────────────────────────────────────

    def set_meta(self, key: str, value: str = "") -> None: ...

    def get_meta(self, key: str) -> dict[str, str] | None: ...

    # ── Alerts ───────────────────────────────────────────────

    def create_alert(
        self,
        severity: str,
        alert_type: str,
        source: str,
        message: str,
        metadata: dict | None = None,
    ) -> None: ...

    def list_alerts(self, *, resolved: bool = False, limit: int = 50) -> list: ...

    def resolve_alert(self, alert_id: Any) -> None: ...

    # ── Schemas ──────────────────────────────────────────────

    def upsert_schema(self, s: Schema) -> UUID: ...

    def get_schema(self, schema_id: UUID) -> Schema | None: ...

    def get_schema_by_name(self, name: str) -> Schema | None: ...

    def list_schemas(self) -> list[Schema]: ...

    # ── Channels ─────────────────────────────────────────────

    def upsert_channel(self, ch: Channel) -> UUID: ...

    def get_channel(self, channel_id: UUID) -> Channel | None: ...

    def get_channel_by_name(self, name: str) -> Channel | None: ...

    def list_channels(self, *, owner_process: UUID | None = None) -> list[Channel]: ...

    def close_channel(self, channel_id: UUID) -> bool: ...

    # ── Channel Messages ─────────────────────────────────────

    def append_channel_message(self, msg: ChannelMessage) -> UUID: ...

    def get_channel_message(self, message_id: UUID) -> ChannelMessage | None: ...

    def list_channel_messages(
        self, channel_id: UUID | None = None, *, limit: int = 100, since: Any = None,
    ) -> list[ChannelMessage]: ...

    # ── Discord Metadata ─────────────────────────────────────

    def upsert_discord_guild(self, guild: DiscordGuild) -> None: ...

    def get_discord_guild(self, guild_id: str) -> DiscordGuild | None: ...

    def list_discord_guilds(self, cogent_name: str | None = None) -> list[DiscordGuild]: ...

    def delete_discord_guild(self, guild_id: str) -> None: ...

    def upsert_discord_channel(self, channel: DiscordChannel) -> None: ...

    def get_discord_channel(self, channel_id: str) -> DiscordChannel | None: ...

    def list_discord_channels(self, guild_id: str | None = None) -> list[DiscordChannel]: ...

    def delete_discord_channel(self, channel_id: str) -> None: ...

    # ── Executors ────────────────────────────────────────────

    def register_executor(self, executor: Executor) -> UUID: ...

    def get_executor(self, executor_id: str) -> Executor | None: ...

    def get_executor_by_id(self, id: UUID) -> Executor | None: ...

    def list_executors(self, status: ExecutorStatus | None = None) -> list[Executor]: ...

    def select_executor(
        self,
        required_tags: list[str] | None = None,
        preferred_tags: list[str] | None = None,
    ) -> Executor | None: ...

    def heartbeat_executor(
        self,
        executor_id: str,
        status: ExecutorStatus = ExecutorStatus.IDLE,
        current_run_id: UUID | None = None,
        resource_usage: dict | None = None,
    ) -> bool: ...

    def update_executor_status(
        self, executor_id: str, status: ExecutorStatus, current_run_id: UUID | None = None,
    ) -> None: ...

    def delete_executor(self, executor_id: str) -> None: ...

    def reap_stale_executors(self, heartbeat_interval_s: int = 30) -> int: ...

    # ── Executor Tokens ──────────────────────────────────────

    def create_executor_token(self, token: ExecutorToken) -> UUID: ...

    def get_executor_token_by_hash(self, token_hash: str) -> ExecutorToken | None: ...

    def list_executor_tokens(self) -> list[ExecutorToken]: ...

    def revoke_executor_token(self, name: str) -> bool: ...

    # ── Lifecycle ─────────────────────────────────────────────

    def reload(self) -> None: ...
