from cogos.db.sqlite_repository import SqliteRepository


def test_creates_db_file(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    assert (tmp_path / "cogos.db").exists()


def test_tables_created(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    tables = repo.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    table_names = [t["name"] for t in tables]
    assert "cogos_process" in table_names
    assert "cogos_file" in table_names
    assert "cogos_run" in table_names
