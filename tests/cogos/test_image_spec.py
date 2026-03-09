import tempfile
from pathlib import Path

from cogos.image.spec import ImageSpec, load_image


def _write_image(tmp: Path) -> Path:
    """Create a minimal test image directory."""
    init = tmp / "init"
    init.mkdir(parents=True)

    (init / "capabilities.py").write_text(
        'add_capability("files", handler="cogos.capabilities.files.FilesCapability", description="File store")\n'
    )
    (init / "resources.py").write_text(
        'add_resource("lambda_slots", type="pool", capacity=5)\n'
    )
    (init / "processes.py").write_text(
        'add_process("scheduler", mode="daemon", priority=100.0, capabilities=["files"], handlers=["scheduler:tick"])\n'
    )
    (init / "cron.py").write_text(
        'add_cron("* * * * *", event_type="scheduler:tick")\n'
    )

    files = tmp / "files" / "cogos"
    files.mkdir(parents=True)
    (files / "scheduler.md").write_text("You are the scheduler.")

    return tmp


def test_load_image_parses_all_sections():
    with tempfile.TemporaryDirectory() as td:
        img_dir = _write_image(Path(td))
        spec = load_image(img_dir)

    assert len(spec.capabilities) == 1
    assert spec.capabilities[0]["name"] == "files"
    assert spec.capabilities[0]["handler"] == "cogos.capabilities.files.FilesCapability"

    assert len(spec.resources) == 1
    assert spec.resources[0]["name"] == "lambda_slots"
    assert spec.resources[0]["capacity"] == 5

    assert len(spec.processes) == 1
    assert spec.processes[0]["name"] == "scheduler"
    assert spec.processes[0]["capabilities"] == ["files"]
    assert spec.processes[0]["handlers"] == ["scheduler:tick"]

    assert len(spec.cron_rules) == 1
    assert spec.cron_rules[0]["event_type"] == "scheduler:tick"

    assert spec.files["cogos/scheduler.md"] == "You are the scheduler."


def test_load_image_no_init_dir():
    with tempfile.TemporaryDirectory() as td:
        spec = load_image(Path(td))
    assert spec.capabilities == []
    assert spec.files == {}


def test_load_image_no_files_dir():
    with tempfile.TemporaryDirectory() as td:
        init = Path(td) / "init"
        init.mkdir()
        (init / "capabilities.py").write_text(
            'add_capability("test", handler="mod.Test")\n'
        )
        spec = load_image(Path(td))
    assert len(spec.capabilities) == 1
    assert spec.files == {}
