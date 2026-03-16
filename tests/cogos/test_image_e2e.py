from pathlib import Path

from cogos.db.local_repository import LocalRepository
from cogos.image.spec import load_image
from cogos.image.apply import apply_image
from cogos.image.snapshot import snapshot_image


def test_boot_cogent_v1(tmp_path):
    """Boot from the real cogent-v1 image using LocalRepository."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"
    assert image_dir.is_dir(), f"cogent-v1 image not found at {image_dir}"

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)

    assert len(spec.capabilities) >= 7
    assert len(spec.resources) >= 2
    assert len(spec.processes) >= 1
    assert len(spec.cron_rules) >= 0
    assert len(spec.files) >= 1

    counts = apply_image(spec, repo)
    assert counts["capabilities"] >= 7
    assert counts["processes"] >= 1
    assert counts["files"] >= 1

    # Verify scheduler process exists with bindings
    procs = repo.list_processes()
    scheduler = [p for p in procs if p.name == "scheduler"]
    assert len(scheduler) == 1

    handlers = repo.list_handlers(process_id=scheduler[0].id)
    assert len(handlers) == 0  # scheduler has no handlers; dispatcher runs it directly


def test_boot_then_snapshot_round_trip(tmp_path):
    """Boot cogent-v1, snapshot, boot snapshot — should produce same state."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"

    # Boot original
    repo1 = LocalRepository(str(tmp_path / "db1"))
    spec1 = load_image(image_dir)
    apply_image(spec1, repo1)

    # Snapshot
    snap_dir = tmp_path / "snapshot"
    snapshot_image(repo1, snap_dir, cogent_name="test")

    # Boot from snapshot
    repo2 = LocalRepository(str(tmp_path / "db2"))
    spec2 = load_image(snap_dir)
    apply_image(spec2, repo2)

    # Compare
    assert len(repo1.list_capabilities()) == len(repo2.list_capabilities())
    assert len(repo1.list_processes()) == len(repo2.list_processes())

    for c1 in repo1.list_capabilities():
        c2 = repo2.get_capability_by_name(c1.name)
        assert c2 is not None, f"Missing capability: {c1.name}"
        assert c2.handler == c1.handler
