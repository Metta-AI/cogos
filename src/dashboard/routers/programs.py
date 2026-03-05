from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import (
    Execution,
    ExecutionsResponse,
    Program,
    ProgramsResponse,
)

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


@router.get("/programs", response_model=ProgramsResponse)
def get_programs(name: str):
    repo = get_repo()

    # Run stats per program
    stats_rows = repo.query(
        "SELECT program_name, "
        "count(*) AS runs, "
        "count(*) FILTER (WHERE status = 'completed') AS ok, "
        "count(*) FILTER (WHERE status = 'failed') AS fail, "
        "COALESCE(SUM(cost_usd), 0)::float AS total_cost, "
        "MAX(started_at)::text AS last_run "
        "FROM runs "
        "GROUP BY program_name",
    )
    stats_by_name: dict[str, dict] = {r["program_name"]: r for r in stats_rows}

    # Program definitions
    prog_rows = repo.query(
        "SELECT name, program_type, includes, tools, metadata FROM programs",
    )

    programs: list[Program] = []
    seen: set[str] = set()

    for row in prog_rows:
        pname = row["name"]
        seen.add(pname)
        metadata = _try_parse_json(row.get("metadata")) or {}
        stats = stats_by_name.get(pname, {})

        programs.append(
            Program(
                name=pname,
                type=row.get("program_type") or "prompt",
                description=metadata.get("description", ""),
                trigger_count=0,
                runs=stats.get("runs", 0),
                ok=stats.get("ok", 0),
                fail=stats.get("fail", 0),
                total_cost=stats.get("total_cost", 0),
                last_run=stats.get("last_run"),
            )
        )

    # Include programs that have runs but no definition row
    for pname, stats in stats_by_name.items():
        if pname not in seen:
            programs.append(
                Program(
                    name=pname,
                    runs=stats.get("runs", 0),
                    ok=stats.get("ok", 0),
                    fail=stats.get("fail", 0),
                    total_cost=stats.get("total_cost", 0),
                    last_run=stats.get("last_run"),
                )
            )

    return ProgramsResponse(cogent_name=name, count=len(programs), programs=programs)


@router.get("/programs/{program_name}/executions", response_model=ExecutionsResponse)
def get_program_executions(name: str, program_name: str):
    repo = get_repo()
    rows = repo.query(
        "SELECT id::text, program_name, conversation_id::text, status, "
        "started_at::text, completed_at::text, duration_ms, "
        "tokens_input, tokens_output, COALESCE(cost_usd, 0)::float AS cost_usd, error "
        "FROM runs WHERE program_name = :pname "
        "ORDER BY started_at DESC",
        {"pname": program_name},
    )
    executions = [Execution(**r) for r in rows]
    return ExecutionsResponse(cogent_name=name, count=len(executions), executions=executions)
