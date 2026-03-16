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
    default = cog["default_coglet"]
    assert default is not None
    assert default["mode"] == "daemon"
    assert default["entrypoint"] == "main.md"
    cap_names = [c if isinstance(c, str) else c["name"] for c in default["capabilities"]]
    assert "procs" in cap_names
    assert "discord" in cap_names
    assert "cog" in cap_names
    assert "coglet_runtime" in cap_names


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
    assert len(sourcer_files) == 4

    prompt_files = {k for k in recruiter_files if k.endswith((".md", ".json")) and "sourcer/" not in k and "init/" not in k}
    # recruiter.md, discover.md, evolve.md, present.md, profile.md,
    # criteria.md, diagnosis.md, evolution.md, strategy.md, design.md
    assert "apps/recruiter/recruiter.md" in prompt_files
    assert "apps/recruiter/discover.md" in prompt_files


def test_cogent_v1_recruiter_prompt_refs_are_explicit():
    """Recruiter prompt references config files via file.read() at runtime."""
    spec = load_image(Path("images/cogent-v1"))

    prompt = spec.files["apps/recruiter/recruiter.md"]
    # The orchestrator uses file.read() to load config into coglets at runtime
    assert 'file.read("apps/recruiter/criteria.md")' in prompt
    assert 'file.read("apps/recruiter/strategy.md")' in prompt
    # Child prompt files are still referenced via file.read()
    assert 'file.read("apps/recruiter/discover.md")' in prompt


def test_cogent_v1_recruiter_channel():
    """The feedback channel should be defined."""
    spec = load_image(Path("images/cogent-v1"))
    channel_names = {c["name"] for c in spec.channels}
    assert "recruiter:feedback" in channel_names
