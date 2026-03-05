from __future__ import annotations

import asyncio
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


async def start_listener(cogent_name: str) -> None:
    """Listen for PostgreSQL NOTIFY and broadcast to WebSocket clients."""
    from dashboard.ws import manager

    pool = await get_pool()
    conn = await pool.acquire()
    channel = f"cogent_{cogent_name.replace('.', '_').replace('-', '_')}_events"
    try:
        await conn.add_listener(channel, lambda conn, pid, channel, payload:
            asyncio.get_event_loop().create_task(
                manager.broadcast(cogent_name, json.loads(payload))
            )
        )
        while True:
            await asyncio.sleep(60)
    finally:
        await pool.release(conn)
