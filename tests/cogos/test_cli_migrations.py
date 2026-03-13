from cogos.cli.__main__ import _run_migrations
from cogos.db.migrations import apply_cogos_sql_migrations


class _RecordingRepo:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> int:
        self.statements.append(sql.strip())
        return 0


def test_run_migrations_executes_comment_prefixed_sql_blocks(monkeypatch):
    monkeypatch.setenv("USE_LOCAL_DB", "1")
    repo = _RecordingRepo()

    _run_migrations(repo)

    assert any(
        "CREATE TABLE IF NOT EXISTS cogos_capability" in stmt
        for stmt in repo.statements
    )
    assert any(
        "CREATE TABLE IF NOT EXISTS cogos_meta" in stmt
        for stmt in repo.statements
    )
    assert any(
        "CREATE TABLE IF NOT EXISTS cogos_channel" in stmt
        for stmt in repo.statements
    )


def test_apply_cogos_sql_migrations_raises_unexpected_errors():
    class _BrokenRepo(_RecordingRepo):
        def execute(self, sql: str) -> int:
            if "CREATE TABLE IF NOT EXISTS cogos_channel" in sql:
                raise RuntimeError("boom")
            return super().execute(sql)

    repo = _BrokenRepo()

    try:
        apply_cogos_sql_migrations(repo)
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected apply_cogos_sql_migrations() to raise")
