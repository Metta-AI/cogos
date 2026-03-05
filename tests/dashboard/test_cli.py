from click.testing import CliRunner

from cli.dashboard import dashboard


def test_login_creates_key(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.dashboard._COGENT_DIR", tmp_path)
    runner = CliRunner()
    result = runner.invoke(dashboard, ["login", "test-cogent"])
    assert result.exit_code == 0
    assert "API key saved" in result.output
    key_file = tmp_path / "test-cogent" / "dashboard-key"
    assert key_file.exists()


def test_logout_removes_key(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.dashboard._COGENT_DIR", tmp_path)
    key_dir = tmp_path / "test-cogent"
    key_dir.mkdir(parents=True)
    (key_dir / "dashboard-key").write_text("test-key")
    runner = CliRunner()
    result = runner.invoke(dashboard, ["logout", "test-cogent"])
    assert result.exit_code == 0
    assert not (key_dir / "dashboard-key").exists()


def test_keys_shows_key(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.dashboard._COGENT_DIR", tmp_path)
    key_dir = tmp_path / "test-cogent"
    key_dir.mkdir(parents=True)
    (key_dir / "dashboard-key").write_text("my-secret-key")
    runner = CliRunner()
    result = runner.invoke(dashboard, ["keys", "test-cogent"])
    assert "my-secret-key" in result.output
