from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import Session, SessionsResponse

router = APIRouter()


def _try_parse_json(val: Any) -> Any:
    """Parse a JSONB field that might already be a dict/list or might be a JSON string."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


@router.get("/sessions", response_model=SessionsResponse)
def get_sessions(name: str):
    repo = get_repo()

    conv_rows = repo.query(
        "SELECT id::text, context_key, status, cli_session_id, "
        "started_at::text, last_active::text, metadata "
        "FROM conversations WHERE cogent_id = :cid "
        "ORDER BY last_active DESC",
        {"cid": name},
    )

    # Run stats per conversation
    stats_rows = repo.query(
        "SELECT conversation_id::text, "
        "count(*) AS runs, "
        "count(*) FILTER (WHERE status = 'completed') AS ok, "
        "count(*) FILTER (WHERE status = 'failed') AS fail, "
        "COALESCE(SUM(tokens_input), 0) AS tokens_in, "
        "COALESCE(SUM(tokens_output), 0) AS tokens_out, "
        "COALESCE(SUM(cost_usd), 0)::float AS total_cost "
        "FROM runs WHERE cogent_id = :cid "
        "GROUP BY conversation_id",
        {"cid": name},
    )
    stats_by_id: dict[str, dict] = {r["conversation_id"]: r for r in stats_rows}

    sessions: list[Session] = []
    for row in conv_rows:
        cid = row["id"]
        stats = stats_by_id.get(cid, {})
        sessions.append(
            Session(
                id=cid,
                context_key=row.get("context_key"),
                status=row.get("status"),
                cli_session_id=row.get("cli_session_id"),
                started_at=row.get("started_at"),
                last_active=row.get("last_active"),
                metadata=_try_parse_json(row.get("metadata")),
                runs=stats.get("runs", 0),
                ok=stats.get("ok", 0),
                fail=stats.get("fail", 0),
                tokens_in=stats.get("tokens_in", 0),
                tokens_out=stats.get("tokens_out", 0),
                total_cost=stats.get("total_cost", 0),
            )
        )

    return SessionsResponse(cogent_id=name, count=len(sessions), sessions=sessions)
