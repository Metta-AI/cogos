from cogos.cli.__main__ import _run_migrations


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
        "ALTER TABLE cogos_process ADD COLUMN IF NOT EXISTS files" in stmt
        for stmt in repo.statements
    )
    assert any(
        "CREATE TABLE IF NOT EXISTS cogos_meta" in stmt
        for stmt in repo.statements
    )
