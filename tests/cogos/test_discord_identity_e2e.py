"""E2E test: Discord identity in whoami/profile.md.

Verifies:
1. Boot produces a profile with identity fields from init.py
2. Handler prompt expands profile and can filter by identity
3. Handler prompt has filtering instructions
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Capability,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
)
from cogos.files.context_engine import ContextEngine
from cogos.files.store import FileStore
from cogos.image.apply import apply_image
from cogos.image.spec import load_image


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path):
    return LocalRepository(str(tmp_path))


@pytest.fixture
def file_store(repo):
    return FileStore(repo)


def _grant_read_all(repo, process):
    """Grant a process read access to all files."""
    dir_cap = Capability(name="dir")
    repo.upsert_capability(dir_cap)
    repo.create_process_capability(
        ProcessCapability(
            process=process.id,
            capability=dir_cap.id,
            name="read_all",
            config={"ops": ["read"]},
        ),
    )


# ── Test 1: Handler prompt includes identity ──────────────


def test_handler_prompt_expands_profile_identity(repo, file_store):
    """Handler prompt expands @{whoami/index.md} → @{whoami/profile.md} with identity."""
    # Write identity files
    file_store.upsert(
        "whoami/profile.md",
        "# Profile\n\n"
        "- **Name:** dr.alpha\n"
        "- **Discord User ID:** 111222333\n",
        source="system",
    )
    file_store.upsert(
        "whoami/index.md",
        "# Identity\n\n@{whoami/profile.md}\n\nYou are a cogent.\n",
        source="system",
    )

    # Create handler process with @{whoami/index.md}
    handler = Process(
        name="discord/handler",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        content="@{whoami/index.md}\n\nYou are the Discord handler.",
    )
    repo.upsert_process(handler)
    _grant_read_all(repo, handler)

    # Expand the prompt
    engine = ContextEngine(file_store)
    prompt = engine.generate_full_prompt(handler)

    # Verify identity is in the expanded prompt
    assert "dr.alpha" in prompt
    assert "111222333" in prompt
    assert "Discord handler" in prompt


# ── Test 2: Boot produces init.py with secrets reads ──────


def test_boot_image_init_uses_capability_profiles(tmp_path):
    """Booting cogent-v1 image creates init.py that uses cogent/discord/email profiles."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogos"
    assert image_dir.is_dir()

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    apply_image(spec, repo)

    fs = FileStore(repo)
    init_content = fs.get_content("mnt/boot/cogos/init.py")
    assert init_content is not None
    assert ".profile()" in init_content
    assert "mnt/boot/whoami/profile.md" in init_content


# ── Test 3: Handler has filtering instructions ────────────


def test_handler_prompt_has_identity_filtering_instructions(tmp_path):
    """The discord handler prompt includes whoami for identity context."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogos"

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    apply_image(spec, repo)

    fs = FileStore(repo)
    handler_content = fs.get_content("mnt/boot/discord/handler/main.md")
    assert handler_content is not None

    # Verify the handler includes whoami for identity
    assert "mnt/boot/whoami/index.md" in handler_content or "mnt/boot/whoami/profile.md" in handler_content
    # Handler should NOT reference cogent capability (not bound)
    assert "cogent.name" not in handler_content
    assert "cogent.profile" not in handler_content


# ── Test 4: Full prompt expansion with identity ───────────


def test_handler_prompt_expansion_includes_full_identity(tmp_path):
    """Full boot + profile write + prompt expansion = identity in handler prompt."""
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogos"

    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    apply_image(spec, repo)

    fs = FileStore(repo)

    # Simulate secrets-populated profile (as init.py would write after reading secrets)
    fs.upsert(
        "mnt/boot/whoami/profile.md",
        "# Profile\n\n"
        "- **Name:** dr.beta\n"
        "- **Discord User ID:** 555666777\n",
        source="system",
    )

    handler_content = fs.get_content("mnt/boot/discord/handler/main.md")
    assert handler_content is not None

    handler = Process(
        name="test-handler",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        content=handler_content,
    )
    repo.upsert_process(handler)
    _grant_read_all(repo, handler)

    engine = ContextEngine(fs)
    prompt = engine.generate_full_prompt(handler)

    assert "dr.beta" in prompt
    assert "555666777" in prompt
    # Handler should not reference cogent capability (not bound)
    assert "cogent.name" not in prompt
    assert "cogent.profile" not in prompt
