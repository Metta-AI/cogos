from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from brain.db.models import RunStatus
from dashboard.db import get_repo
from dashboard.models import (
    Execution,
    ExecutionsResponse,
    Program,
    ProgramsResponse,
)

router = APIRouter()


def _try_parse_json(val: Any) -> Any:
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
    db_programs = repo.list_programs()
    all_runs = repo.query_runs(limit=10000)

    runs_by_prog: dict[str, list] = {}
    for r in all_runs:
        runs_by_prog.setdefault(r.program_name, []).append(r)

    programs: list[Program] = []
    seen: set[str] = set()

    for p in db_programs:
        seen.add(p.name)
        metadata = _try_parse_json(p.metadata) or {}
        prog_runs = runs_by_prog.get(p.name, [])
        ok = sum(1 for r in prog_runs if r.status == RunStatus.COMPLETED)
        fail = sum(1 for r in prog_runs if r.status == RunStatus.FAILED)
        total_cost = float(sum(r.cost_usd for r in prog_runs))
        last_run = max((str(r.started_at) for r in prog_runs if r.started_at), default=None)

        programs.append(
            Program(
                name=p.name,
                description=metadata.get("description", ""),
                trigger_count=0,
                runs=len(prog_runs),
                ok=ok,
                fail=fail,
                total_cost=total_cost,
                last_run=last_run,
            )
        )

    for pname, prog_runs in runs_by_prog.items():
        if pname not in seen:
            ok = sum(1 for r in prog_runs if r.status == RunStatus.COMPLETED)
            fail = sum(1 for r in prog_runs if r.status == RunStatus.FAILED)
            total_cost = float(sum(r.cost_usd for r in prog_runs))
            last_run = max((str(r.started_at) for r in prog_runs if r.started_at), default=None)
            programs.append(
                Program(
                    name=pname,
                    runs=len(prog_runs),
                    ok=ok,
                    fail=fail,
                    total_cost=total_cost,
                    last_run=last_run,
                )
            )

    return ProgramsResponse(cogent_name=name, count=len(programs), programs=programs)


@router.get("/programs/{program_name}/executions", response_model=ExecutionsResponse)
def get_program_executions(name: str, program_name: str):
    repo = get_repo()
    db_runs = repo.query_runs(program_name=program_name)
    executions = [
        Execution(
            id=str(r.id),
            program_name=r.program_name,
            conversation_id=str(r.conversation_id) if r.conversation_id else None,
            status=r.status.value if r.status else None,
            started_at=str(r.started_at) if r.started_at else None,
            completed_at=str(r.completed_at) if r.completed_at else None,
            duration_ms=r.duration_ms,
            tokens_input=r.tokens_input,
            tokens_output=r.tokens_output,
            cost_usd=float(r.cost_usd) if r.cost_usd else 0,
            error=r.error,
        )
        for r in db_runs
    ]
    return ExecutionsResponse(cogent_name=name, count=len(executions), executions=executions)
