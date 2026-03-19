"""Tests for the recruiter app image loading and wiring."""

import tempfile
from pathlib import Path

from cogos.image.spec import load_image


def _write_app_image(tmp: Path) -> Path:
    """Create a minimal image with an app subdirectory."""
    # Top-level init
    init = tmp / "init"
    init.mkdir(parents=True)
    (init / "processes.py").write_text(
        'add_process("scheduler", mode="daemon", priority=100.0)\n'
    )

    # Top-level content
    cogos = tmp / "cogos"
    cogos.mkdir(parents=True)
    (cogos / "scheduler.md").write_text("You are the scheduler.")

    # App init
    app_init = tmp / "apps" / "myapp" / "init"
    app_init.mkdir(parents=True)
    (app_init / "processes.py").write_text(
        'add_channel("myapp:events", channel_type="named")\n'
        'add_process("myapp/worker", mode="daemon", content="@{apps/myapp/prompt.md}", '
        'capabilities=["dir"], handlers=["myapp:events"])\n'
    )

    # App files — on disk matches the key (apps/myapp/...)
    app_files = tmp / "apps" / "myapp"
    (app_files / "prompt.md").write_text("You are a worker.\n@{apps/myapp/config.md}")
    (app_files / "config.md").write_text("Config here.")

    return tmp


def test_apps_load_processes():
    """App init scripts should add processes to the spec."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    names = {p["name"] for p in spec.processes}
    assert "scheduler" in names
    assert "myapp/worker" in names


def test_apps_load_files():
    """App files/ dirs should be loaded into spec.files."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    assert "apps/myapp/prompt.md" in spec.files
    assert spec.files["apps/myapp/prompt.md"] == "You are a worker.\n@{apps/myapp/config.md}"
    assert "apps/myapp/config.md" in spec.files


def test_apps_load_channels():
    """App init scripts should add channels to the spec."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    names = {c["name"] for c in spec.channels}
    assert "myapp:events" in names


def test_app_prompt_refs_are_explicit_in_file_content():
    """App prompt dependencies should be declared inline in file content."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    assert "@{apps/myapp/config.md}" in spec.files["apps/myapp/prompt.md"]


def test_apps_dont_affect_top_level():
    """Loading apps should not remove or modify top-level processes/files."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    assert "cogos/scheduler.md" in spec.files
    names = {p["name"] for p in spec.processes}
    assert "scheduler" in names


def test_cogent_v1_recruiter_loads():
    """The actual recruiter app should load from the cogent-v1 image as a cog."""
    spec = load_image(Path("images/cogent-v1"))

    cog = next((c for c in spec.cogs if c["name"] == "recruiter"), None)
    assert cog is not None, "recruiter cog not found"
    config = cog["config"]
    assert config["mode"] == "daemon"
    assert cog["entrypoint"] == "main.py"
    cap_names = [c if isinstance(c, str) else c["name"] for c in config["capabilities"]]
    assert "procs" in cap_names
    assert "discord" in cap_names


def test_cogent_v1_recruiter_files():
    """All recruiter files should be loaded with correct keys."""
    spec = load_image(Path("images/cogent-v1"))
    recruiter_files = {k for k in spec.files if k.startswith("apps/recruiter/")}

    assert "apps/recruiter/criteria.md" in recruiter_files
    assert "apps/recruiter/rubric.json" in recruiter_files
    assert "apps/recruiter/diagnosis.md" in recruiter_files
    assert "apps/recruiter/strategy.md" in recruiter_files
    assert "apps/recruiter/evolution.md" in recruiter_files

    sourcer_files = {k for k in recruiter_files if "sourcer/" in k}
    assert len(sourcer_files) >= 1

    assert "apps/recruiter/main.py" in recruiter_files
    prompt_files = {k for k in recruiter_files if k.endswith((".md", ".json")) and "sourcer/" not in k and "init/" not in k}
    assert "apps/recruiter/discover.md" in prompt_files


def test_cogent_v1_recruiter_prompt_refs_are_explicit():
    """Recruiter orchestrator references config and worker files via source.get().read()."""
    spec = load_image(Path("images/cogent-v1"))

    orchestrator = spec.files["apps/recruiter/main.py"]
    # The orchestrator uses source.get().read() to load config into coglets at runtime
    assert 'source.get("criteria.md").read()' in orchestrator
    assert 'source.get("strategy.md").read()' in orchestrator
    # Child prompt files are still referenced via source.get().read()
    assert 'source.get("discover.md").read()' in orchestrator


def test_cogent_v1_recruiter_channel():
    """The feedback channel should be defined."""
    spec = load_image(Path("images/cogent-v1"))
    channel_names = {c["name"] for c in spec.channels}
    assert "recruiter:feedback" in channel_names
