from fastapi.testclient import TestClient

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Process, ProcessCapability
from cogos.files.store import FileStore
from dashboard.app import create_app


def test_process_detail_uses_scoped_prompt_resolution(tmp_path, monkeypatch):
    repo = LocalRepository(str(tmp_path))
    files = FileStore(repo)
    files.create("playbooks/refunds", "Refunds require context from @{playbooks/escalation}")
    files.create("playbooks/escalation", "Escalate to finance.")
    files.create("cogos/includes/code_mode", "Code mode guidance.")

    dir_cap = Capability(name="dir", handler="cogos.capabilities.files.FilesCapability")
    repo.upsert_capability(dir_cap)
    dir_cap = repo.get_capability_by_name("dir")

    process = Process(name="support", content="Use @{playbooks/refunds}")
    repo.upsert_process(process)
    repo.create_process_capability(
        ProcessCapability(
            process=process.id,
            capability=dir_cap.id,
            name="dir",
            config={"prefix": "playbooks/", "ops": ["read"]},
        )
    )

    monkeypatch.setattr("dashboard.routers.processes.get_repo", lambda: repo)
    client = TestClient(create_app())

    resp = client.get(f"/api/cogents/test/processes/{process.id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["resolved_prompt"] == (
        "Use <!-- uses: playbooks/refunds -->\n\n"
        "<!-- included: playbooks/escalation -->\n"
        "Escalate to finance.\n\n"
        "<!-- included: playbooks/refunds -->\n"
        "Refunds require context from <!-- uses: playbooks/escalation -->"
    )
    assert data["includes"] == []
    assert data["prompt_tree"][-1] == {
        "key": "playbooks/refunds",
        "content": "Refunds require context from <!-- uses: playbooks/escalation -->",
        "is_direct": False,
    }
