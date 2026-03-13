from cogos.db.local_repository import LocalRepository
from cogos.image.spec import ImageSpec, load_image
from cogos.image.apply import apply_image
from cogos.image.snapshot import snapshot_image


def test_snapshot_round_trips(tmp_path):
    """Apply an image, snapshot it, load the snapshot — should match."""
    repo = LocalRepository(str(tmp_path / "db"))

    original = ImageSpec(
        capabilities=[
            {"name": "dir", "handler": "cogos.capabilities.files.FilesCapability",
             "description": "Directory access", "instructions": "", "schema": None, "iam_role_arn": None, "metadata": None},
        ],
        resources=[],
        processes=[
            {"name": "scheduler", "mode": "daemon", "content": "@{cogos/scheduler}",
             "runner": "lambda", "model": None,
             "priority": 100.0, "capabilities": ["dir"],
             "handlers": [], "metadata": {}},
        ],
        cron_rules=[],
        files={"cogos/scheduler": "You are the scheduler."},
    )
    apply_image(original, repo)

    snapshot_dir = tmp_path / "snapshot"
    snapshot_image(repo, snapshot_dir)

    # Verify files were generated
    assert (snapshot_dir / "init" / "capabilities.py").exists()
    assert (snapshot_dir / "init" / "processes.py").exists()
    assert (snapshot_dir / "files" / "cogos" / "scheduler").exists()
    assert (snapshot_dir / "README.md").exists()

    # Round-trip: load the snapshot and verify
    restored = load_image(snapshot_dir)
    assert len(restored.capabilities) == 1
    assert restored.capabilities[0]["name"] == "dir"
    assert len(restored.processes) == 1
    assert restored.processes[0]["name"] == "scheduler"
    assert restored.processes[0]["content"] == "@{cogos/scheduler}"
    assert "dir" in restored.processes[0]["capabilities"]
    assert restored.processes[0]["handlers"] == []
    assert restored.files["cogos/scheduler"] == "You are the scheduler."
