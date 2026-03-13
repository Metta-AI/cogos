import json

from click.testing import CliRunner

from cogos.cli.__main__ import cogos
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability


def test_process_load_preserves_multiple_capability_grants(tmp_path, monkeypatch):
    monkeypatch.setenv("COGENT_LOCAL_DATA", str(tmp_path / "db"))

    repo = LocalRepository(str(tmp_path / "db"))
    for cap_name in ("dir", "me"):
        repo.upsert_capability(
            Capability(name=cap_name, handler="cogos.capabilities.files.FilesCapability")
            if cap_name == "dir"
            else Capability(name=cap_name, handler="cogos.capabilities.me.MeCapability")
        )

    proc_path = tmp_path / "processes.json"
    proc_path.write_text(json.dumps([
        {
            "name": "test-proc",
            "mode": "daemon",
            "code_key": "missing.md",
            "capabilities": ["dir", "me"],
            "handlers": ["test:channel"],
        }
    ]))

    runner = CliRunner()
    result = runner.invoke(cogos, ["--cogent", "local", "process", "load", str(proc_path)])
    assert result.exit_code == 0, result.output

    repo = LocalRepository(str(tmp_path / "db"))
    process = repo.get_process_by_name("test-proc")
    grants = repo.list_process_capabilities(process.id)
    assert {grant.name for grant in grants} == {"dir", "me"}

