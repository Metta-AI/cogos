from __future__ import annotations

from pathlib import Path

from cogos.db.models import Capability, Process, ProcessCapability
from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.context_engine import ContextEngine
from cogos.files.references import extract_file_references
from cogos.files.store import FileStore


def test_extract_file_references_preserves_order_and_uniqueness() -> None:
    content = """
    intro
    @{alpha/one}
    middle @{beta/two} again @{alpha/one}
    @{ gamma/three }
    """

    assert extract_file_references(content) == [
        "alpha/one",
        "beta/two",
        "gamma/three",
    ]


def test_extract_file_references_filters_self_reference() -> None:
    content = "keep @{shared/base} ignore @{self/file}"

    assert extract_file_references(content, exclude_key="self/file") == ["shared/base"]


def test_new_version_updates_includes(tmp_path: Path) -> None:
    repo = SqliteRepository(data_dir=str(tmp_path))
    store = FileStore(repo)
    created = store.create(
        "prompts/root",
        "hello @{shared/base}",
    )

    result = store.new_version(
        "prompts/root",
        "hello @{shared/updated}",
    )

    assert result is not None
    updated = repo.get_file_by_id(created.id)
    assert updated is not None
    assert updated.includes == ["shared/updated"]


def test_unchanged_write_resyncs_derived_includes(tmp_path: Path) -> None:
    repo = SqliteRepository(data_dir=str(tmp_path))
    store = FileStore(repo)
    created = store.create("prompts/root", "hello @{shared/base}")

    assert repo.update_file_includes(created.id, ["stale/include"]) is True

    result = store.new_version("prompts/root", "hello @{shared/base}")

    assert result is None
    updated = repo.get_file_by_id(created.id)
    assert updated is not None
    assert updated.includes == ["shared/base"]


def test_process_prompt_references_include_readable_files(tmp_path: Path) -> None:
    repo = SqliteRepository(data_dir=str(tmp_path))
    store = FileStore(repo)
    store.create("secrets/reference", "classified")
    store.create("private/blocked", "blocked")

    proc = Process(name="agent", content="tell me @{secrets/reference} and @{private/blocked}")
    repo.upsert_process(proc)

    dir_cap = Capability(name="dir")
    repo.upsert_capability(dir_cap)
    repo.create_process_capability(
        ProcessCapability(
            process=proc.id,
            capability=dir_cap.id,
            name="read_secrets",
            config={"prefix": "secrets/", "ops": ["read"]},
        ),
    )

    engine = ContextEngine(store)
    prompt = engine.generate_full_prompt(proc)
    tree = engine.resolve_prompt_tree(proc)

    assert "--- secrets/reference ---\nclassified" in prompt
    assert "--- private/blocked ---" not in prompt
    assert [entry["key"] for entry in tree] == ["secrets/reference", "<content>"]


def test_process_prompt_references_ignore_non_readable_grants(tmp_path: Path) -> None:
    repo = SqliteRepository(data_dir=str(tmp_path))
    store = FileStore(repo)
    store.create("secrets/reference", "classified")

    proc = Process(name="agent", content="tell me @{secrets/reference}")
    repo.upsert_process(proc)

    dir_cap = Capability(name="dir")
    repo.upsert_capability(dir_cap)
    repo.create_process_capability(
        ProcessCapability(
            process=proc.id,
            capability=dir_cap.id,
            name="write_only_secrets",
            config={"prefix": "secrets/", "ops": ["write"]},
        ),
    )

    engine = ContextEngine(store)
    prompt = engine.generate_full_prompt(proc)
    tree = engine.resolve_prompt_tree(proc)

    assert "--- secrets/reference ---" not in prompt
    assert [entry["key"] for entry in tree] == ["<content>"]
