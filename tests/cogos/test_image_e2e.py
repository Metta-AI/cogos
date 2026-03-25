from pathlib import Path

from cogos.db.sqlite_repository import SqliteRepository
from cogos.image.apply import apply_image
from cogos.image.snapshot import snapshot_image
from cogos.image.spec import load_image


def test_boot_cogent_v1(tmp_path):
    """Boot from the real cogent-v1 image using SqliteRepository."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogos"
    assert image_dir.is_dir(), f"cogent-v1 image not found at {image_dir}"

    repo = SqliteRepository(str(tmp_path / "db"))
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

    # Verify at least one process exists after boot
    procs = repo.list_processes()
    assert len(procs) >= 1


def test_boot_cogs_e2e(tmp_path):
    """Boot cogent-v1, verify cog manifests are written correctly."""
    import json
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogos"

    repo = SqliteRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    counts = apply_image(spec, repo)

    # app cogs + cogos cogs (supervisor, worker)
    assert counts["cogs"] >= 7

    # -- Cog processes are NOT created by apply_image (deferred to init.py) --
    procs = repo.list_processes()
    proc_names = {p.name for p in procs}
    assert "recruiter" not in proc_names
    assert "newsfromthefront" not in proc_names

    # -- Verify cog manifests are written --
    from cogos.files.store import FileStore
    fs = FileStore(repo)
    raw = fs.get_content("mnt/boot/_boot/cog_manifests.json")
    assert raw is not None
    manifests = json.loads(raw)
    manifest_map = {e["name"]: e for e in manifests}

    assert "recruiter" in manifest_map
    assert "newsfromthefront" in manifest_map
    assert "discord" in manifest_map
    assert "website" in manifest_map
    assert "supervisor" in manifest_map

    # -- Recruiter manifest: daemon, has capabilities --
    rec = manifest_map["recruiter"]
    rec_config = rec["config"]
    assert rec_config["mode"] == "daemon"
    rec_cap_names = [c if isinstance(c, str) else c["name"] for c in rec_config["capabilities"]]
    assert "procs" in rec_cap_names
    assert "discord" in rec_cap_names
    assert "recruiter:feedback" in rec_config["handlers"]

    # -- Newsfromthefront manifest: daemon --
    nff = manifest_map["newsfromthefront"]
    nff_config = nff["config"]
    assert nff_config["mode"] == "daemon"
    nff_cap_names = [c if isinstance(c, str) else c["name"] for c in nff_config["capabilities"]]
    assert "web_search" in nff_cap_names
    expected_nff_handlers = {
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    }
    assert expected_nff_handlers.issubset(set(nff_config["handlers"]))

    # -- Verify CogManifest round-trip works --

    for m_dict in manifests:
        prefix = m_dict.get("content_prefix", "mnt/boot")
        name = m_dict["name"]
        entrypoint = m_dict["entrypoint"]
        content_key = f"{prefix}/{name}/{entrypoint}"
        content = fs.get_content(content_key)
        assert content is not None, f"Content missing for {name} at {content_key}"

    # -- Verify CogManifest round-trip for all cogs --
    for m_dict in manifests:
        assert "name" in m_dict
        assert "entrypoint" in m_dict


def test_boot_then_snapshot_round_trip(tmp_path):
    """Boot cogent-v1, snapshot, boot snapshot — should produce same state."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogos"

    # Boot original
    repo1 = SqliteRepository(str(tmp_path / "db1"))
    spec1 = load_image(image_dir)
    apply_image(spec1, repo1)

    # Snapshot
    snap_dir = tmp_path / "snapshot"
    snapshot_image(repo1, snap_dir, cogent_name="test")

    # Boot from snapshot
    repo2 = SqliteRepository(str(tmp_path / "db2"))
    spec2 = load_image(snap_dir)
    apply_image(spec2, repo2)

    # Compare
    assert len(repo1.list_capabilities()) == len(repo2.list_capabilities())
    assert len(repo1.list_processes()) == len(repo2.list_processes())

    for c1 in repo1.list_capabilities():
        c2 = repo2.get_capability_by_name(c1.name)
        assert c2 is not None, f"Missing capability: {c1.name}"
        assert c2.handler == c1.handler
