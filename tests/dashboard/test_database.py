import os
import pytest
import asyncpg

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://cogent:cogent_dev@localhost:5432/cogent_test")


@pytest.fixture
async def db_pool():
    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") and not os.environ.get("CI"),
    reason="No TEST_DATABASE_URL set and not in CI; skipping database test",
)
async def test_pool_connects(db_pool):
    row = await db_pool.fetchrow("SELECT 1 AS val")
    assert row["val"] == 1
