from pathlib import Path

from cogos.db.local_repository import LocalRepository
from cogos.image.apply import apply_image
from cogos.image.snapshot import snapshot_image
from cogos.image.spec import load_image


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

    # Verify at least one process exists after boot
    procs = repo.list_processes()
    assert len(procs) >= 1


def test_boot_cogs_e2e(tmp_path):
    """Boot cogent-v1, verify cog metadata + boot manifest are written correctly."""
    import json
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    counts = apply_image(spec, repo)

    assert counts["cogs"] == 4  # recruiter + newsfromthefront + discord + website

    # -- Cog processes are NOT created by apply_image (deferred to init.py) --
    procs = repo.list_processes()
    proc_names = {p.name for p in procs}
    assert "recruiter" not in proc_names
    assert "newsfromthefront" not in proc_names

    # -- Verify boot manifest has all cog process specs --
    from cogos.files.store import FileStore
    fs = FileStore(repo)
    raw = fs.get_content("_boot/cog_processes.json")
    assert raw is not None
    manifest = json.loads(raw)
    manifest_map = {e["name"]: e for e in manifest}

    assert "recruiter" in manifest_map
    assert "newsfromthefront" in manifest_map
    assert "discord" in manifest_map
    assert "website" in manifest_map

    # -- Recruiter manifest entry: daemon, has cog + coglet_runtime --
    rec = manifest_map["recruiter"]
    assert rec["mode"] == "daemon"
    rec_cap_names = [c if isinstance(c, str) else c["name"] for c in rec["capabilities"]]
    assert "cog" in rec_cap_names
    assert "coglet_runtime" in rec_cap_names
    assert "procs" in rec_cap_names
    assert "discord" in rec_cap_names
    assert "recruiter:feedback" in rec["handlers"]

    # -- Newsfromthefront manifest entry: daemon, has cog + coglet_runtime --
    nff = manifest_map["newsfromthefront"]
    assert nff["mode"] == "daemon"
    nff_cap_names = [c if isinstance(c, str) else c["name"] for c in nff["capabilities"]]
    assert "cog" in nff_cap_names
    assert "coglet_runtime" in nff_cap_names
    assert "web_search" in nff_cap_names
    expected_nff_handlers = {
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    }
    assert expected_nff_handlers.issubset(set(nff["handlers"]))

    # -- Verify cog storage has default coglets --
    from cogos.cog import load_cog_meta, load_coglet_meta

    for cog_name in ["recruiter", "newsfromthefront"]:
        cog_meta = load_cog_meta(fs, cog_name)
        assert cog_meta is not None, f"cog meta missing for {cog_name}"
        coglet_meta = load_coglet_meta(fs, cog_name, cog_name)
        assert coglet_meta is not None, f"default coglet missing for {cog_name}"
        assert coglet_meta.entrypoint in ("main.md", "recruiter.py", "newsfromthefront.py")
        assert coglet_meta.mode == "daemon"

    # -- Verify runtime cog.make_coglet works --
    from uuid import uuid4

    from cogos.capabilities.cog import CogCapability

    cog_cap = CogCapability(repo, uuid4())
    scoped = cog_cap.scope(cog_name="recruiter")
    child = scoped.make_coglet("discover", entrypoint="main.md",
                                files={"main.md": "# Discover\n\n## Steps\nDo things."})
    assert child.cog_name == "recruiter"
    assert child.name == "discover"
    assert child.read_file("main.md") == "# Discover\n\n## Steps\nDo things."

    child_meta = load_coglet_meta(fs, "recruiter", "discover")
    assert child_meta is not None
    assert child_meta.entrypoint == "main.md"

    # -- Verify CogletRuntime can run a child coglet --
    from cogos.capabilities.coglet_runtime import CogletRun, CogletRuntimeCapability
    from cogos.capabilities.procs import ProcsCapability
    from cogos.db.models import Process, ProcessCapability, ProcessMode, ProcessStatus

    parent = Process(name="test-parent", mode=ProcessMode.ONE_SHOT,
                     content="test", status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    procs_cap_db = repo.get_capability_by_name("procs")
    pc = ProcessCapability(process=parent_id, capability=procs_cap_db.id, name="procs")
    repo.create_process_capability(pc)
    procs_cap = ProcsCapability(repo, parent_id)

    runtime = CogletRuntimeCapability(repo, parent_id)
    run = runtime.run(child, procs_cap)
    assert isinstance(run, CogletRun), f"Expected CogletRun, got {type(run)}: {run}"
    handle = run.process()
    assert handle._process.name == "recruiter/discover"
    assert handle._process.mode.value == "one_shot"


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
