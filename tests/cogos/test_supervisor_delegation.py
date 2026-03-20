"""Tests that the supervisor can delegate capabilities to helper processes.

The escalation chain is:
  init → supervisor → helper

For the supervisor to spawn a helper with e.g. asana capability,
the supervisor must hold asana, and init must hold asana (to delegate to supervisor).
"""

from pathlib import Path

from cogos.capabilities.base import Capability
from cogos.capabilities.procs import ProcessError, ProcsCapability
from cogos.db.local_repository import LocalRepository
from cogos.image.apply import apply_image
from cogos.image.spec import load_image

DELEGATABLE_CAPS = [
    "asana",
    "email",
    "github",
    "web_search",
    "web_fetch",
    "web",
    "blob",
    "image",
]


def _boot_cogent_v1(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    image_dir = repo_root / "images" / "cogos"
    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(image_dir)
    apply_image(spec, repo)
    return repo


def test_init_holds_delegatable_capabilities(tmp_path):
    """The init process must hold all capabilities it needs to delegate to supervisor."""
    repo = _boot_cogent_v1(tmp_path)
    init_proc = repo.get_process_by_name("init")
    assert init_proc is not None
    init_caps = repo.list_process_capabilities(init_proc.id)
    assert init_caps is not None
    init_cap_names = {pc.name for pc in init_caps}

    for cap_name in DELEGATABLE_CAPS:
        assert cap_name in init_cap_names, f"init missing '{cap_name}' — supervisor cannot receive it"


def test_init_can_spawn_supervisor_with_delegatable_caps(tmp_path):
    """Simulates init spawning supervisor with all delegatable capabilities."""
    repo = _boot_cogent_v1(tmp_path)
    init_proc = repo.get_process_by_name("init")
    assert init_proc is not None

    procs_cap = ProcsCapability(repo, init_proc.id)

    caps: dict[str, Capability | None] = {
        "me": None,
        "procs": None,
        "fs_dir": None,
        "discord": None,
        "channels": None,
        "secrets": None,
        "stdlib": None,
        "alerts": None,
        "asana": None,
        "email": None,
        "github": None,
        "web_search": None,
        "web_fetch": None,
        "web": None,
        "blob": None,
        "image": None,
    }

    result = procs_cap.spawn(
        name="test-supervisor",
        content="supervisor prompt",
        mode="daemon",
        capabilities=caps,
    )

    assert not isinstance(result, ProcessError), f"spawn failed: {result.error}"
    assert result.name == "test-supervisor"


def test_supervisor_can_delegate_asana_to_helper(tmp_path):
    """Simulates supervisor spawning a helper with asana capability."""
    repo = _boot_cogent_v1(tmp_path)
    init_proc = repo.get_process_by_name("init")
    assert init_proc is not None

    # Step 1: init spawns supervisor (with asana)
    init_procs = ProcsCapability(repo, init_proc.id)
    supervisor = init_procs.spawn(
        name="test-supervisor",
        content="supervisor",
        mode="daemon",
        capabilities={
            "procs": None,
            "discord": None,
            "channels": None,
            "asana": None,
        },
    )
    assert not isinstance(supervisor, ProcessError), f"supervisor spawn failed: {supervisor.error}"

    # Step 2: supervisor spawns helper (with asana + discord)
    from uuid import UUID

    sup_procs = ProcsCapability(repo, UUID(supervisor.id))
    helper = sup_procs.spawn(
        name="asana-helper",
        content="create an asana task",
        capabilities={"asana": None, "discord": None, "channels": None},
    )
    assert not isinstance(helper, ProcessError), f"helper spawn failed: {helper.error}"
    assert helper.name == "asana-helper"
