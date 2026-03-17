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

    # Verify at least one process exists after boot
    procs = repo.list_processes()
    assert len(procs) >= 1


def test_boot_cogs_e2e(tmp_path):
    """Boot cogent-v1, verify both cogs create processes with correct wiring."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogent-v1"

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    counts = apply_image(spec, repo)

    assert counts["cogs"] == 4  # recruiter + newsfromthefront + discord + website

    # -- Verify both cog processes exist --
    procs = repo.list_processes()
    proc_map = {p.name: p for p in procs}
    assert "recruiter" in proc_map, f"recruiter not in {list(proc_map)}"
    assert "newsfromthefront" in proc_map, f"newsfromthefront not in {list(proc_map)}"

    # -- Recruiter process: daemon, has cog + coglet_runtime capabilities --
    rec = proc_map["recruiter"]
    assert rec.mode.value == "daemon"
    rec_caps = repo.list_process_capabilities(rec.id)
    rec_cap_names = {pc.name for pc in rec_caps}
    assert "cog" in rec_cap_names, f"recruiter missing cog cap; has {rec_cap_names}"
    assert "coglet_runtime" in rec_cap_names
    assert "procs" in rec_cap_names
    assert "discord" in rec_cap_names

    # cog capability should be scoped to "recruiter"
    cog_pc = next(pc for pc in rec_caps if pc.name == "cog")
    assert cog_pc.config == {"cog_name": "recruiter"}, f"cog config: {cog_pc.config}"

    # recruiter should have handler for recruiter:feedback
    rec_handlers = repo.list_handlers(process_id=rec.id)
    rec_handler_channels = set()
    for h in rec_handlers:
        ch = repo.get_channel(h.channel)
        if ch:
            rec_handler_channels.add(ch.name)
    assert "recruiter:feedback" in rec_handler_channels, f"handlers: {rec_handler_channels}"

    # -- Newsfromthefront process: daemon, has cog + coglet_runtime --
    nff = proc_map["newsfromthefront"]
    assert nff.mode.value == "daemon"
    nff_caps = repo.list_process_capabilities(nff.id)
    nff_cap_names = {pc.name for pc in nff_caps}
    assert "cog" in nff_cap_names
    assert "coglet_runtime" in nff_cap_names
    assert "web_search" in nff_cap_names

    # cog capability should be scoped to "newsfromthefront"
    nff_cog_pc = next(pc for pc in nff_caps if pc.name == "cog")
    assert nff_cog_pc.config == {"cog_name": "newsfromthefront"}

    # newsfromthefront should have handlers for all 4 channels
    nff_handlers = repo.list_handlers(process_id=nff.id)
    nff_handler_channels = set()
    for h in nff_handlers:
        ch = repo.get_channel(h.channel)
        if ch:
            nff_handler_channels.add(ch.name)
    expected_nff_channels = {
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    }
    assert expected_nff_channels.issubset(nff_handler_channels), \
        f"Missing: {expected_nff_channels - nff_handler_channels}"

    # -- Verify cog storage has default coglets --
    from cogos.cog import load_cog_meta, load_coglet_meta
    from cogos.files.store import FileStore
    fs = FileStore(repo)

    for cog_name in ["recruiter", "newsfromthefront"]:
        cog_meta = load_cog_meta(fs, cog_name)
        assert cog_meta is not None, f"cog meta missing for {cog_name}"
        coglet_meta = load_coglet_meta(fs, cog_name, cog_name)
        assert coglet_meta is not None, f"default coglet missing for {cog_name}"
        assert coglet_meta.entrypoint in ("main.md", "recruiter.py", "newsfromthefront.py")
        assert coglet_meta.mode == "daemon"

    # -- Verify runtime cog.make_coglet works --
    from cogos.capabilities.cog import CogCapability
    from uuid import uuid4

    # Simulate the recruiter orchestrator creating a child coglet
    cog_cap = CogCapability(repo, uuid4())
    scoped = cog_cap.scope(cog_name="recruiter")
    child = scoped.make_coglet("discover", entrypoint="main.md",
                                files={"main.md": "# Discover\n\n## Steps\nDo things."})
    assert child.cog_name == "recruiter"
    assert child.name == "discover"
    assert child.read_file("main.md") == "# Discover\n\n## Steps\nDo things."

    # Verify the child coglet is in storage
    child_meta = load_coglet_meta(fs, "recruiter", "discover")
    assert child_meta is not None
    assert child_meta.entrypoint == "main.md"

    # -- Verify CogletRuntime can run a child coglet --
    from cogos.capabilities.coglet_runtime import CogletRuntimeCapability, CogletRun
    from cogos.capabilities.procs import ProcsCapability
    from cogos.db.models import Process, ProcessMode, ProcessStatus, ProcessCapability

    # Create a parent process to hold procs capability
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
