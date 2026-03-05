from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg

from dashboard.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def fetch_all(sql: str, *args: Any) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def fetch_one(sql: str, *args: Any) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(sql, *args)
    return dict(row) if row else None


async def execute(sql: str, *args: Any) -> str:
    pool = await get_pool()
    return await pool.execute(sql, *args)


async def apply_schema() -> None:
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    pool = await get_pool()
    await pool.execute(sql)
