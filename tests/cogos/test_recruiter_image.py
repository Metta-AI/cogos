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

    # Top-level files
    files = tmp / "files" / "cogos"
    files.mkdir(parents=True)
    (files / "scheduler.md").write_text("You are the scheduler.")

    # App init
    app_init = tmp / "apps" / "myapp" / "init"
    app_init.mkdir(parents=True)
    (app_init / "processes.py").write_text(
        'add_file("myapp/prompt.md", content="", includes=["myapp/config.md"])\n'
        'add_channel("myapp:events", channel_type="named")\n'
        'add_process("myapp/worker", mode="daemon", code_key="myapp/prompt.md", '
        'capabilities=["dir"], handlers=["myapp:events"])\n'
    )

    # App files
    app_files = tmp / "apps" / "myapp" / "files" / "myapp"
    app_files.mkdir(parents=True)
    (app_files / "prompt.md").write_text("You are a worker.")
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

    assert "myapp/prompt.md" in spec.files
    assert spec.files["myapp/prompt.md"] == "You are a worker."
    assert "myapp/config.md" in spec.files


def test_apps_load_channels():
    """App init scripts should add channels to the spec."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    names = {c["name"] for c in spec.channels}
    assert "myapp:events" in names


def test_add_file_includes():
    """add_file should set up file_includes metadata."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    assert "myapp/prompt.md" in spec.file_includes
    assert spec.file_includes["myapp/prompt.md"] == ["myapp/config.md"]


def test_app_files_overwrite_add_file_content():
    """Files from files/ dir should overwrite empty add_file content."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    # add_file set content="" but files/ dir loaded "You are a worker."
    assert spec.files["myapp/prompt.md"] == "You are a worker."
    # includes should still be set
    assert spec.file_includes["myapp/prompt.md"] == ["myapp/config.md"]


def test_apps_dont_affect_top_level():
    """Loading apps should not remove or modify top-level processes/files."""
    with tempfile.TemporaryDirectory() as td:
        _write_app_image(Path(td))
        spec = load_image(Path(td))

    assert "cogos/scheduler.md" in spec.files
    names = {p["name"] for p in spec.processes}
    assert "scheduler" in names


def test_cogent_v1_recruiter_loads():
    """The actual recruiter app should load from the cogent-v1 image."""
    spec = load_image(Path("images/cogent-v1"))

    proc_names = {p["name"] for p in spec.processes}
    assert "recruiter" in proc_names
    assert "recruiter/present" in proc_names

    recruiter = next(p for p in spec.processes if p["name"] == "recruiter")
    assert recruiter["mode"] == "daemon"
    assert recruiter["code_key"] == "apps/recruiter/prompts/recruiter.md"
    assert "procs" in recruiter["capabilities"]
    assert "discord" in recruiter["capabilities"]

    present = next(p for p in spec.processes if p["name"] == "recruiter/present")
    assert present["mode"] == "daemon"
    assert present["code_key"] == "apps/recruiter/prompts/present.md"


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

    prompt_files = {k for k in recruiter_files if "prompts/" in k}
    assert len(prompt_files) == 5


def test_cogent_v1_recruiter_includes():
    """Recruiter prompt files should have correct includes."""
    spec = load_image(Path("images/cogent-v1"))

    assert spec.file_includes["apps/recruiter/prompts/recruiter.md"] == [
        "apps/recruiter/criteria.md", "apps/recruiter/strategy.md",
    ]
    assert "apps/recruiter/rubric.json" in spec.file_includes["apps/recruiter/prompts/discover.md"]
    assert "apps/recruiter/diagnosis.md" in spec.file_includes["apps/recruiter/prompts/evolve.md"]


def test_cogent_v1_recruiter_channel():
    """The feedback channel should be defined."""
    spec = load_image(Path("images/cogent-v1"))
    channel_names = {c["name"] for c in spec.channels}
    assert "recruiter:feedback" in channel_names
