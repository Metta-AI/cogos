"""Executor-owned session artifacts stored in the CogOS file store."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from cogos.db.models import Process
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)

DEFAULT_CHECKPOINT_MAX_MESSAGES = 120
DEFAULT_CHECKPOINT_MAX_BYTES = 200_000


@dataclass(frozen=True)
class ResolvedSession:
    process_id: UUID
    run_id: UUID
    scope: str
    logical_key: str
    key_field: str | None
    session_path: str
    base_key: str
    manifest_key: str
    checkpoint_key: str
    run_base_key: str
    trigger_key: str
    steps_key: str
    final_key: str
    resume_requested: bool
    resume_enabled: bool
    default_skip_reason: str | None


@dataclass(frozen=True)
class LoadedCheckpoint:
    messages: list[dict[str, Any]]
    resumed: bool
    resumed_from_run_id: str | None
    resume_skipped_reason: str | None
    last_completed_step: int


@dataclass(frozen=True)
class CheckpointWriteResult:
    checkpoint_key: str | None
    resume_disabled_reason: str | None


def build_prompt_fingerprint(system_prompt: str, model_id: str, tool_config: dict[str, Any]) -> str:
    payload = {
        "model_id": model_id,
        "system_prompt": system_prompt,
        "tool_config": tool_config,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SessionStore:
    """Persist resumable checkpoints and immutable per-run artifacts."""

    def __init__(
        self,
        repo,
        *,
        max_checkpoint_messages: int | None = None,
        max_checkpoint_bytes: int | None = None,
    ) -> None:
        self._store = FileStore(repo)
        self._max_checkpoint_messages = (
            max_checkpoint_messages
            if max_checkpoint_messages is not None
            else _int_env("COGOS_SESSION_MAX_MESSAGES", DEFAULT_CHECKPOINT_MAX_MESSAGES)
        )
        self._max_checkpoint_bytes = (
            max_checkpoint_bytes
            if max_checkpoint_bytes is not None
            else _int_env("COGOS_SESSION_MAX_BYTES", DEFAULT_CHECKPOINT_MAX_BYTES)
        )

    def resolve_session(self, process: Process, event_data: dict[str, Any], run_id: UUID) -> ResolvedSession:
        session_meta = process.metadata.get("session", {}) if isinstance(process.metadata, dict) else {}
        resume_requested, scope, key_field, default_skip_reason = self._parse_session_meta(session_meta)

        logical_key = "default"
        if scope == "keyed":
            logical_key = self._resolve_keyed_key(event_data, key_field)
            if resume_requested:
                default_skip_reason = "unsupported_session_scope:keyed"

        session_hash = hashlib.sha256(logical_key.encode("utf-8")).hexdigest()[:16]
        session_namespace = self._session_namespace_label(scope=scope, resume_requested=resume_requested)
        session_path = f"{session_namespace}-{session_hash}"
        base_key = f"/proc/{process.id}/_sessions/{session_path}"

        resume_enabled = resume_requested and scope == "process"
        if not resume_enabled and resume_requested and default_skip_reason is None:
            default_skip_reason = f"resume_disabled_for_scope:{scope}"

        return ResolvedSession(
            process_id=process.id,
            run_id=run_id,
            scope=scope,
            logical_key=logical_key,
            key_field=key_field,
            session_path=session_path,
            base_key=base_key,
            manifest_key=f"{base_key}/manifest.json",
            checkpoint_key=f"{base_key}/checkpoint.json",
            run_base_key=f"{base_key}/runs/{run_id}",
            trigger_key=f"{base_key}/runs/{run_id}/trigger.json",
            steps_key=f"{base_key}/runs/{run_id}/steps",
            final_key=f"{base_key}/runs/{run_id}/final.json",
            resume_requested=resume_requested,
            resume_enabled=resume_enabled,
            default_skip_reason=default_skip_reason,
        )

    def load_checkpoint(
        self,
        session: ResolvedSession,
        *,
        prompt_fingerprint: str,
        model_id: str,
    ) -> LoadedCheckpoint:
        if not session.resume_requested:
            return LoadedCheckpoint(
                messages=[],
                resumed=False,
                resumed_from_run_id=None,
                resume_skipped_reason=None,
                last_completed_step=0,
            )

        if not session.resume_enabled:
            return LoadedCheckpoint(
                messages=[],
                resumed=False,
                resumed_from_run_id=None,
                resume_skipped_reason=session.default_skip_reason,
                last_completed_step=0,
            )

        checkpoint = self._read_json(session.checkpoint_key)
        if not isinstance(checkpoint, dict):
            return LoadedCheckpoint(
                messages=[],
                resumed=False,
                resumed_from_run_id=None,
                resume_skipped_reason="missing_checkpoint",
                last_completed_step=0,
            )

        if checkpoint.get("resumable") is False:
            return LoadedCheckpoint(
                messages=[],
                resumed=False,
                resumed_from_run_id=_string_or_none(checkpoint.get("source_run_id")),
                resume_skipped_reason=_string_or_none(checkpoint.get("resume_disabled_reason")) or "checkpoint_not_resumable",
                last_completed_step=_int_or_zero(checkpoint.get("last_completed_step")),
            )

        checkpoint_model = checkpoint.get("model_id")
        if isinstance(checkpoint_model, str) and checkpoint_model != model_id:
            return LoadedCheckpoint(
                messages=[],
                resumed=False,
                resumed_from_run_id=_string_or_none(checkpoint.get("source_run_id")),
                resume_skipped_reason="model_changed",
                last_completed_step=_int_or_zero(checkpoint.get("last_completed_step")),
            )

        checkpoint_fingerprint = checkpoint.get("prompt_fingerprint")
        if checkpoint_fingerprint != prompt_fingerprint:
            return LoadedCheckpoint(
                messages=[],
                resumed=False,
                resumed_from_run_id=_string_or_none(checkpoint.get("source_run_id")),
                resume_skipped_reason="prompt_fingerprint_changed",
                last_completed_step=_int_or_zero(checkpoint.get("last_completed_step")),
            )

        messages = checkpoint.get("messages")
        if not isinstance(messages, list):
            return LoadedCheckpoint(
                messages=[],
                resumed=False,
                resumed_from_run_id=_string_or_none(checkpoint.get("source_run_id")),
                resume_skipped_reason="invalid_checkpoint_messages",
                last_completed_step=_int_or_zero(checkpoint.get("last_completed_step")),
            )

        normalized_messages = _json_clone(messages)
        bounds_reason = self._checkpoint_bounds_reason(normalized_messages)
        if bounds_reason is not None:
            return LoadedCheckpoint(
                messages=[],
                resumed=False,
                resumed_from_run_id=_string_or_none(checkpoint.get("source_run_id")),
                resume_skipped_reason=bounds_reason,
                last_completed_step=_int_or_zero(checkpoint.get("last_completed_step")),
            )

        return LoadedCheckpoint(
            messages=normalized_messages,
            resumed=True,
            resumed_from_run_id=_string_or_none(checkpoint.get("source_run_id")),
            resume_skipped_reason=None,
            last_completed_step=_int_or_zero(checkpoint.get("last_completed_step")),
        )

    def write_manifest(
        self,
        session: ResolvedSession,
        *,
        latest_run_id: UUID,
        final_key: str | None = None,
        checkpoint_key: str | None = None,
    ) -> None:
        existing = self._read_json(session.manifest_key)
        now = _utc_now()
        payload = {
            "process_id": str(session.process_id),
            "session_scope": session.scope,
            "session_key": session.logical_key,
            "session_path": session.session_path,
            "resume_requested": session.resume_requested,
            "resume_enabled": session.resume_enabled,
            "checkpoint_key": checkpoint_key,
            "latest_run_id": str(latest_run_id),
            "latest_final_key": final_key,
            "updated_at": now,
            "created_at": (
                existing.get("created_at")
                if isinstance(existing, dict) and isinstance(existing.get("created_at"), str)
                else now
            ),
        }
        self._write_json(session.manifest_key, payload, mutable=True)

    def write_trigger(
        self,
        session: ResolvedSession,
        *,
        event_data: dict[str, Any],
        user_message: dict[str, Any],
    ) -> None:
        payload = {
            "process_id": str(session.process_id),
            "run_id": str(session.run_id),
            "created_at": _utc_now(),
            "event": _json_clone(event_data),
            "user_message": _json_clone(user_message),
        }
        self._write_json(session.trigger_key, payload, mutable=False)

    def write_step(
        self,
        session: ResolvedSession,
        *,
        seq: int,
        step_type: str,
        payload: dict[str, Any],
    ) -> str:
        step_key = f"{session.steps_key}/{seq:04d}.json"
        body = {
            "process_id": str(session.process_id),
            "run_id": str(session.run_id),
            "seq": seq,
            "type": step_type,
            "created_at": _utc_now(),
            **_json_clone(payload),
        }
        self._write_json(step_key, body, mutable=False)
        return step_key

    def update_checkpoint(
        self,
        session: ResolvedSession,
        *,
        messages: list[dict[str, Any]],
        model_id: str,
        prompt_fingerprint: str,
        last_completed_step: int,
        source_run_id: UUID,
    ) -> CheckpointWriteResult:
        if not session.resume_enabled:
            return CheckpointWriteResult(checkpoint_key=None, resume_disabled_reason=None)

        normalized_messages = _json_clone(messages)
        resume_disabled_reason = self._checkpoint_bounds_reason(normalized_messages)
        checkpoint = {
            "messages": normalized_messages if resume_disabled_reason is None else [],
            "model_id": model_id,
            "prompt_fingerprint": prompt_fingerprint,
            "last_completed_step": last_completed_step,
            "source_run_id": str(source_run_id),
            "updated_at": _utc_now(),
            "message_count": len(normalized_messages),
            "message_bytes": _json_size(normalized_messages),
            "resumable": resume_disabled_reason is None,
        }
        if resume_disabled_reason is not None:
            checkpoint["resume_disabled_reason"] = resume_disabled_reason

        self._write_json(session.checkpoint_key, checkpoint, mutable=True)
        return CheckpointWriteResult(
            checkpoint_key=session.checkpoint_key,
            resume_disabled_reason=resume_disabled_reason,
        )

    def finalize_run(
        self,
        session: ResolvedSession,
        *,
        status: str,
        resumed: bool,
        resumed_from_run_id: str | None,
        resume_skipped_reason: str | None,
        final_stop_reason: str,
        error: str | None,
        last_completed_step: int,
        message_count: int,
        checkpoint_key: str | None,
    ) -> dict[str, Any]:
        final_payload = {
            "process_id": str(session.process_id),
            "run_id": str(session.run_id),
            "session_scope": session.scope,
            "session_key": session.logical_key,
            "session_path": session.session_path,
            "status": status,
            "resumed": resumed,
            "resumed_from_run_id": resumed_from_run_id,
            "resume_requested": session.resume_requested,
            "resume_enabled": session.resume_enabled,
            "resume_skipped_reason": resume_skipped_reason,
            "final_stop_reason": final_stop_reason,
            "error": error,
            "last_completed_step": last_completed_step,
            "message_count": message_count,
            "manifest_key": session.manifest_key,
            "checkpoint_key": checkpoint_key,
            "trigger_key": session.trigger_key,
            "steps_key": session.steps_key,
            "finalized_at": _utc_now(),
        }
        self._write_json(session.final_key, final_payload, mutable=False)
        self.write_manifest(
            session,
            latest_run_id=session.run_id,
            final_key=session.final_key,
            checkpoint_key=checkpoint_key,
        )
        return {
            "session_scope": session.scope,
            "session_key": session.logical_key,
            "session_path": session.session_path,
            "manifest_key": session.manifest_key,
            "checkpoint_key": checkpoint_key,
            "final_key": session.final_key,
            "resumed": resumed,
            "resumed_from_run_id": resumed_from_run_id,
            "resume_skipped_reason": resume_skipped_reason,
        }

    def _resolve_keyed_key(self, event_data: dict[str, Any], key_field: str | None) -> str:
        if not key_field:
            return "missing"
        payload = event_data.get("payload", {})
        if isinstance(payload, dict):
            value = payload.get(key_field)
            if value is not None:
                return str(value)
        return f"missing:{key_field}"

    def _parse_session_meta(
        self,
        session_meta: Any,
    ) -> tuple[bool, str, str | None, str | None]:
        resume_requested = False
        scope = "process"
        key_field: str | None = "session_key"
        default_skip_reason = None

        if not isinstance(session_meta, dict):
            return resume_requested, scope, key_field, default_skip_reason

        raw_key_field = session_meta.get("key_field")
        if isinstance(raw_key_field, str) and raw_key_field.strip():
            key_field = raw_key_field.strip()

        has_new_shape = "resume" in session_meta or "scope" in session_meta
        if has_new_shape:
            raw_resume = session_meta.get("resume")
            if isinstance(raw_resume, bool):
                resume_requested = raw_resume
            elif raw_resume is not None:
                default_skip_reason = f"invalid_session_resume:{raw_resume}"

            raw_scope = session_meta.get("scope")
            if raw_scope in {"process", "keyed"}:
                scope = raw_scope
            elif isinstance(raw_scope, str) and raw_scope:
                if default_skip_reason is None:
                    default_skip_reason = f"invalid_session_scope:{raw_scope}"
            return resume_requested, scope, key_field, default_skip_reason

        raw_mode = session_meta.get("mode")
        if raw_mode == "off":
            return False, "process", key_field, default_skip_reason
        if raw_mode == "process":
            return True, "process", key_field, default_skip_reason
        if raw_mode == "keyed":
            return True, "keyed", key_field, default_skip_reason
        if isinstance(raw_mode, str) and raw_mode:
            default_skip_reason = f"invalid_session_mode:{raw_mode}"
        return resume_requested, scope, key_field, default_skip_reason

    def _session_namespace_label(self, *, scope: str, resume_requested: bool) -> str:
        if resume_requested:
            return scope
        if scope == "process":
            return "log-only"
        return f"{scope}-log-only"

    def _checkpoint_bounds_reason(self, messages: list[dict[str, Any]]) -> str | None:
        if len(messages) > self._max_checkpoint_messages:
            return (
                f"checkpoint_message_limit_exceeded:"
                f"{len(messages)}>{self._max_checkpoint_messages}"
            )
        size = _json_size(messages)
        if size > self._max_checkpoint_bytes:
            return (
                f"checkpoint_byte_limit_exceeded:"
                f"{size}>{self._max_checkpoint_bytes}"
            )
        return None

    def _read_json(self, key: str) -> dict[str, Any] | None:
        raw = self._store.get_content(key)
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Ignoring invalid JSON session artifact %s", key)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _write_json(self, key: str, payload: dict[str, Any], *, mutable: bool) -> None:
        content = json.dumps(payload, indent=2, sort_keys=True)
        if mutable:
            self._store.upsert(key, content, source="executor")
            return

        existing = self._store.get_content(key)
        if existing is None:
            self._store.create(key, content, source="executor", read_only=True)
            return
        if existing == content:
            return
        logger.warning("Session artifact %s already exists with different content; storing a new version", key)
        self._store.new_version(key, content, source="executor", read_only=True)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default
    return max(value, 1)


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _json_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
