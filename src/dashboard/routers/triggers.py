from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import ToggleRequest, ToggleResponse, Trigger, TriggersResponse

router = APIRouter(tags=["triggers"])


@router.get("/triggers", response_model=TriggersResponse)
def list_triggers(name: str) -> TriggersResponse:
    repo = get_repo()
    rows = repo.query(
        """
        SELECT t.id::text, t.trigger_type, t.event_pattern, t.cron_expression,
          t.program_name, t.priority, t.enabled, t.created_at::text,
          (SELECT count(*) FROM runs r WHERE r.cogent_id = :cid
            AND r.program_name = t.program_name AND r.started_at > now() - interval '1 minute') AS fired_1m,
          (SELECT count(*) FROM runs r WHERE r.cogent_id = :cid
            AND r.program_name = t.program_name AND r.started_at > now() - interval '5 minutes') AS fired_5m,
          (SELECT count(*) FROM runs r WHERE r.cogent_id = :cid
            AND r.program_name = t.program_name AND r.started_at > now() - interval '1 hour') AS fired_1h,
          (SELECT count(*) FROM runs r WHERE r.cogent_id = :cid
            AND r.program_name = t.program_name AND r.started_at > now() - interval '24 hours') AS fired_24h
        FROM triggers t WHERE t.cogent_id = :cid ORDER BY t.priority
        """,
        {"cid": name},
    )

    triggers = []
    for r in rows:
        prog = r.get("program_name") or ""
        pattern = r.get("event_pattern") or r.get("cron_expression") or ""
        trigger_name = f"{prog}:{pattern}" if pattern else prog

        triggers.append(
            Trigger(
                id=r["id"],
                name=trigger_name,
                trigger_type=r.get("trigger_type"),
                event_pattern=r.get("event_pattern"),
                cron_expression=r.get("cron_expression"),
                program_name=r.get("program_name"),
                priority=r.get("priority"),
                enabled=r.get("enabled", True),
                created_at=r.get("created_at"),
                fired_1m=r.get("fired_1m", 0),
                fired_5m=r.get("fired_5m", 0),
                fired_1h=r.get("fired_1h", 0),
                fired_24h=r.get("fired_24h", 0),
            )
        )

    return TriggersResponse(cogent_id=name, count=len(triggers), triggers=triggers)


@router.post("/triggers/toggle", response_model=ToggleResponse)
def toggle_triggers(name: str, body: ToggleRequest) -> ToggleResponse:
    repo = get_repo()
    count = repo.execute(
        "UPDATE triggers SET enabled = :enabled"
        " WHERE id = ANY(string_to_array(:ids, ',')::uuid[]) AND cogent_id = :cid",
        {"enabled": body.enabled, "ids": ",".join(body.ids), "cid": name},
    )
    return ToggleResponse(updated=count, enabled=body.enabled)
