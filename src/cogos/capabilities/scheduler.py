"""Scheduler capabilities — message matching, process selection, dispatch."""

from __future__ import annotations

import logging
import math
import random
import time
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.db.models import Delivery, ProcessStatus, Run, RunStatus

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class DeliveryInfo(BaseModel):
    delivery_id: str
    message_id: str
    channel: str
    handler_id: str
    process_id: str


class MatchResult(BaseModel):
    deliveries_created: int = 0
    deliveries: list[DeliveryInfo] = []


class SelectedProcess(BaseModel):
    id: str
    name: str
    priority: float
    effective_priority: float


class SelectResult(BaseModel):
    selected: list[SelectedProcess] = []


class DispatchResult(BaseModel):
    run_id: str
    process_id: str
    process_name: str
    runner: str
    message_id: str | None = None
    delivery_id: str | None = None


class UnblockInfo(BaseModel):
    id: str
    name: str


class UnblockResult(BaseModel):
    unblocked_count: int = 0
    unblocked: list[UnblockInfo] = []


class KillResult(BaseModel):
    process_id: str
    name: str
    previous_status: str
    new_status: str


class SchedulerError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────


class SchedulerCapability(Capability):
    """Process scheduling and message dispatch.

    Usage:
        scheduler.match_messages()
        scheduler.select_processes(slots=2)
        scheduler.dispatch_process(process_id="...")
        scheduler.unblock_processes()
        scheduler.kill_process(process_id="...")
    """

    def match_messages(self) -> MatchResult:
        """Find undelivered channel messages and create deliveries."""
        all_handlers = self.repo.list_handlers(enabled_only=True)
        channel_handlers = [h for h in all_handlers if h.channel is not None]

        created = []
        for handler in channel_handlers:
            msgs = self.repo.list_channel_messages(handler.channel, limit=200)
            for msg in msgs:
                delivery = Delivery(message=msg.id, handler=handler.id)
                delivery_id, inserted = self.repo.create_delivery(delivery)
                if not inserted:
                    continue

                proc = self.repo.get_process(handler.process)
                if proc and proc.status == ProcessStatus.WAITING:
                    self.repo.update_process_status(handler.process, ProcessStatus.RUNNABLE)

                created.append(DeliveryInfo(
                    delivery_id=str(delivery_id),
                    message_id=str(msg.id),
                    channel=str(handler.channel),
                    handler_id=str(handler.id),
                    process_id=str(handler.process),
                ))

        return MatchResult(deliveries_created=len(created), deliveries=created)

    def select_processes(self, slots: int = 1) -> SelectResult:
        now_ts = time.time()

        runnable = self.repo.get_runnable_processes(limit=200)
        if not runnable:
            return SelectResult()

        priorities = [self._effective_priority(p, now_ts) for p in runnable]

        max_p = max(priorities) if priorities else 0
        exps = [math.exp(p - max_p) for p in priorities]
        total = sum(exps)
        weights = [e / total for e in exps]

        n_select = min(slots, len(runnable))
        selected_indices: list[int] = []
        remaining_indices = list(range(len(runnable)))
        remaining_weights = list(weights)

        for _ in range(n_select):
            if not remaining_indices:
                break
            total_w = sum(remaining_weights)
            if total_w <= 0:
                break
            normalised = [w / total_w for w in remaining_weights]
            chosen = random.choices(remaining_indices, weights=normalised, k=1)[0]
            selected_indices.append(chosen)
            idx_pos = remaining_indices.index(chosen)
            remaining_indices.pop(idx_pos)
            remaining_weights.pop(idx_pos)

        return SelectResult(selected=[
            SelectedProcess(
                id=str(runnable[idx].id),
                name=runnable[idx].name,
                priority=runnable[idx].priority,
                effective_priority=priorities[idx],
            )
            for idx in selected_indices
        ])

    def dispatch_process(self, process_id: str) -> DispatchResult | SchedulerError:
        if not process_id:
            return SchedulerError(error="process_id is required")

        target_id = UUID(process_id)
        proc = self.repo.get_process(target_id)
        if proc is None:
            return SchedulerError(error="process not found")

        if proc.status != ProcessStatus.RUNNABLE:
            return SchedulerError(error=f"process is {proc.status.value}, expected runnable")

        self.repo.update_process_status(target_id, ProcessStatus.RUNNING)

        deliveries = self.repo.get_pending_deliveries(target_id)
        message_id = deliveries[0].message if deliveries else None
        delivery_id = deliveries[0].id if deliveries else None

        run = Run(process=target_id, message=message_id)
        run_id = self.repo.create_run(run)

        if delivery_id:
            self.repo.mark_queued(delivery_id, run_id)
            self._log_delivery_to_run_latency(deliveries[0], run)

        return DispatchResult(
            run_id=str(run_id),
            process_id=str(target_id),
            process_name=proc.name,
            runner=proc.runner,
            message_id=str(message_id) if message_id else None,
            delivery_id=str(delivery_id) if delivery_id else None,
        )

    def unblock_processes(self) -> UnblockResult:
        blocked = self.repo.list_processes(status=ProcessStatus.BLOCKED)
        unblocked = []

        for proc in blocked:
            if not proc.resources:
                self.repo.update_process_status(proc.id, ProcessStatus.RUNNABLE)
                unblocked.append(UnblockInfo(id=str(proc.id), name=proc.name))
                continue

            all_available = True
            for resource_id in proc.resources:
                rows = self.repo.query(
                    """SELECT COALESCE(SUM(amount), 0) AS used
                       FROM cogos_resource_usage ru
                       JOIN cogos_run r ON r.id = ru.run
                       WHERE ru.resource = :resource_id AND r.status = 'running'""",
                    {"resource_id": resource_id},
                )
                used = float(rows[0]["used"]) if rows else 0.0

                res_rows = self.repo.query(
                    "SELECT capacity FROM cogos_resource WHERE id = :id",
                    {"id": resource_id},
                )
                capacity = float(res_rows[0]["capacity"]) if res_rows else 0.0

                if used >= capacity:
                    all_available = False
                    break

            if all_available:
                self.repo.update_process_status(proc.id, ProcessStatus.RUNNABLE)
                unblocked.append(UnblockInfo(id=str(proc.id), name=proc.name))

        return UnblockResult(unblocked_count=len(unblocked), unblocked=unblocked)

    def kill_process(self, process_id: str) -> KillResult | SchedulerError:
        if not process_id:
            return SchedulerError(error="process_id is required")

        target_id = UUID(process_id)
        proc = self.repo.get_process(target_id)
        if proc is None:
            return SchedulerError(error="process not found")

        previous_status = proc.status.value
        self.repo.update_process_status(target_id, ProcessStatus.DISABLED)

        runs = self.repo.list_runs(process_id=target_id, limit=1)
        if runs and runs[0].status == RunStatus.RUNNING:
            self.repo.complete_run(runs[0].id, status=RunStatus.FAILED, error="killed by scheduler")

        return KillResult(
            process_id=str(target_id),
            name=proc.name,
            previous_status=previous_status,
            new_status=ProcessStatus.DISABLED.value,
        )

    @staticmethod
    def _effective_priority(proc, now_ts: float) -> float:
        base = proc.priority
        if proc.runnable_since:
            wait_seconds = now_ts - proc.runnable_since.timestamp()
            base += 0.1 * (wait_seconds / 60.0)
        return base

    @staticmethod
    def _log_message_to_delivery_latency(message, delivery: Delivery) -> None:
        if message.created_at and delivery.created_at:
            latency_ms = int((delivery.created_at - message.created_at).total_seconds() * 1000)
            logger.info(
                "CogOS latency message->delivery=%sms message=%s handler=%s",
                latency_ms,
                message.id,
                delivery.handler,
            )

    @staticmethod
    def _log_delivery_to_run_latency(delivery: Delivery, run: Run) -> None:
        if delivery.created_at and run.created_at:
            latency_ms = int((run.created_at - delivery.created_at).total_seconds() * 1000)
            logger.info(
                "CogOS latency delivery->run=%sms delivery=%s run=%s message=%s",
                latency_ms,
                delivery.id,
                run.id,
                delivery.message,
            )

    def __repr__(self) -> str:
        return "<SchedulerCapability match_messages() select_processes() dispatch_process() unblock_processes() kill_process()>"
