from click.testing import CliRunner

from cli.dashboard import dashboard


def test_login_creates_key(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.dashboard._COGENT_DIR", tmp_path)
    runner = CliRunner()
    result = runner.invoke(dashboard, ["login"], obj={"cogent_id": "test-cogent"})
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
    result = runner.invoke(dashboard, ["logout"], obj={"cogent_id": "test-cogent"})
    assert result.exit_code == 0
    assert not (key_dir / "dashboard-key").exists()


def test_keys_shows_key(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.dashboard._COGENT_DIR", tmp_path)
    key_dir = tmp_path / "test-cogent"
    key_dir.mkdir(parents=True)
    (key_dir / "dashboard-key").write_text("my-secret-key")
    runner = CliRunner()
    result = runner.invoke(dashboard, ["keys"], obj={"cogent_id": "test-cogent"})
    assert "my-secret-key" in result.output


class _DummyProc:
    def __init__(self, args, env=None, cwd=None):
        self.args = args
        self.env = env or {}
        self.cwd = cwd

    def terminate(self):
        return None

    def wait(self):
        return 0


def test_serve_db_prod_uses_polis_lookup(tmp_path, monkeypatch):
    calls: dict[str, object] = {}

    def fake_ensure(name: str, env: dict, *, assume_polis: bool = False, profile: str | None = None):
        calls["name"] = name
        calls["assume_polis"] = assume_polis
        calls["profile"] = profile
        env["DB_RESOURCE_ARN"] = "cluster-arn"
        env["DB_SECRET_ARN"] = "secret-arn"
        env["DB_NAME"] = "cogent"
        return env

    procs: list[_DummyProc] = []

    def fake_popen(args, env=None, cwd=None):
        proc = _DummyProc(args, env=env, cwd=cwd)
        procs.append(proc)
        return proc

    monkeypatch.setattr("cli.dashboard._ensure_db_env", fake_ensure)
    monkeypatch.setattr("cli.dashboard._FRONTEND_DIR", tmp_path / "missing")
    monkeypatch.setattr("cli.dashboard.subprocess.Popen", fake_popen)

    runner = CliRunner()
    result = runner.invoke(
        dashboard,
        ["serve", "--db", "prod", "--no-browser"],
        obj={"cogent_id": "dr.gamma"},
    )

    assert result.exit_code == 0
    assert calls == {"name": "dr.gamma", "assume_polis": True, "profile": None}
    assert len(procs) == 1
    assert procs[0].env["DASHBOARD_COGENT_NAME"] == "dr.gamma"


def test_serve_db_local_sets_use_local_db(tmp_path, monkeypatch):
    procs: list[_DummyProc] = []

    def fake_popen(args, env=None, cwd=None):
        proc = _DummyProc(args, env=env, cwd=cwd)
        procs.append(proc)
        return proc

    monkeypatch.setattr("cli.dashboard._FRONTEND_DIR", tmp_path / "missing")
    monkeypatch.setattr("cli.dashboard.subprocess.Popen", fake_popen)

    runner = CliRunner()
    result = runner.invoke(
        dashboard,
        ["serve", "--db", "local", "--no-browser"],
        obj={"cogent_id": "dr.gamma"},
    )

    assert result.exit_code == 0
    assert len(procs) == 1
    assert procs[0].env["USE_LOCAL_DB"] == "1"


def test_serve_db_prod_passes_profile(tmp_path, monkeypatch):
    calls: dict[str, object] = {}

    def fake_ensure(name: str, env: dict, *, assume_polis: bool = False, profile: str | None = None):
        calls["name"] = name
        calls["assume_polis"] = assume_polis
        calls["profile"] = profile
        env["DB_RESOURCE_ARN"] = "cluster-arn"
        env["DB_SECRET_ARN"] = "secret-arn"
        env["DB_NAME"] = "cogent"
        return env

    procs: list[_DummyProc] = []

    def fake_popen(args, env=None, cwd=None):
        proc = _DummyProc(args, env=env, cwd=cwd)
        procs.append(proc)
        return proc

    monkeypatch.setattr("cli.dashboard._ensure_db_env", fake_ensure)
    monkeypatch.setattr("cli.dashboard._FRONTEND_DIR", tmp_path / "missing")
    monkeypatch.setattr("cli.dashboard.subprocess.Popen", fake_popen)

    runner = CliRunner()
    result = runner.invoke(
        dashboard,
        ["serve", "--db", "prod", "--profile", "softmax-org", "--no-browser"],
        obj={"cogent_id": "dr.gamma"},
    )

    assert result.exit_code == 0
    assert calls == {"name": "dr.gamma", "assume_polis": True, "profile": "softmax-org"}
    assert len(procs) == 1


def test_serve_db_prod_fails_fast_when_credentials_are_missing(tmp_path, monkeypatch):
    procs: list[_DummyProc] = []

    def fake_popen(args, env=None, cwd=None):
        proc = _DummyProc(args, env=env, cwd=cwd)
        procs.append(proc)
        return proc

    def fake_ensure(name: str, env: dict, *, assume_polis: bool = False, profile: str | None = None):
        return env

    monkeypatch.setattr("cli.dashboard._ensure_db_env", fake_ensure)
    monkeypatch.setattr("cli.dashboard._FRONTEND_DIR", tmp_path / "missing")
    monkeypatch.setattr("cli.dashboard.subprocess.Popen", fake_popen)

    runner = CliRunner()
    result = runner.invoke(
        dashboard,
        ["serve", "--db", "prod", "--no-browser"],
        obj={"cogent_id": "dr.gamma"},
    )

    assert result.exit_code != 0
    assert not procs
    assert "did not resolve them" in result.output
    assert "aws sso login --profile softmax-org" in result.output


def test_serve_auto_fails_fast_when_live_db_env_is_missing(tmp_path, monkeypatch):
    procs: list[_DummyProc] = []

    def fake_popen(args, env=None, cwd=None):
        proc = _DummyProc(args, env=env, cwd=cwd)
        procs.append(proc)
        return proc

    def fake_ensure(name: str, env: dict, *, assume_polis: bool = False, profile: str | None = None):
        return env

    monkeypatch.setattr("cli.dashboard._ensure_db_env", fake_ensure)
    monkeypatch.setattr("cli.dashboard._FRONTEND_DIR", tmp_path / "missing")
    monkeypatch.setattr("cli.dashboard.subprocess.Popen", fake_popen)

    runner = CliRunner()
    result = runner.invoke(
        dashboard,
        ["serve", "--db", "auto", "--no-browser"],
        obj={"cogent_id": "dr.gamma"},
    )

    assert result.exit_code != 0
    assert not procs
    assert "Dashboard requires DB credentials for live data." in result.output
    assert "use `--db local`" in result.output


def test_serve_rejects_local_and_db_together(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(
        dashboard,
        ["serve", "--db", "prod", "--local", "--no-browser"],
        obj={"cogent_id": "dr.gamma"},
    )

    assert result.exit_code != 0
    assert "Use either --local or --db, not both." in result.output
