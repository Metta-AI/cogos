from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import Capability, Process, ProcessCapability
from cogos.files.context_engine import ContextEngine
from cogos.files.store import FileStore


def _grant_read_all(repo: SqliteRepository, process: Process) -> None:
    repo.upsert_process(process)
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


def test_generate_full_prompt_expands_inline_refs_recursively(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    store = FileStore(repo)

    store.upsert("docs/shared.md", "Shared context", source="test")
    store.upsert("docs/nested.md", "Nested details", source="test")
    store.upsert("docs/inline.md", "Inline ref -> @{docs/nested.md}", source="test")
    store.upsert("prompts/root.md", "Root prompt\n@{docs/shared.md}", source="test")

    process = Process(
        name="worker",
        content="Header\n@{prompts/root.md}\nFooter\n@{docs/inline.md}",
    )
    _grant_read_all(repo, process)

    prompt = ContextEngine(store).generate_full_prompt(process)

    assert prompt.startswith("Header")
    assert "--- docs/shared.md ---\nShared context" in prompt
    assert "--- prompts/root.md ---\nRoot prompt" in prompt
    assert "--- docs/nested.md ---\nNested details" in prompt
    assert "--- docs/inline.md ---\nInline ref -> --- docs/nested.md ---\nNested details" in prompt
    assert "Footer" in prompt


def test_resolve_prompt_tree_marks_direct_refs_from_process_content(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    store = FileStore(repo)

    store.upsert("docs/shared.md", "Shared context", source="test")
    store.upsert("docs/nested.md", "Nested details", source="test")
    store.upsert("docs/inline.md", "Inline ref -> @{docs/nested.md}", source="test")
    store.upsert("prompts/root.md", "Root prompt\n@{docs/shared.md}", source="test")

    process = Process(
        name="worker",
        content="Use @{prompts/root.md} then @{docs/inline.md}",
    )
    _grant_read_all(repo, process)

    tree = ContextEngine(store).resolve_prompt_tree(process)
    assert [entry["key"] for entry in tree] == [
        "docs/shared.md",
        "prompts/root.md",
        "docs/nested.md",
        "docs/inline.md",
        "<content>",
    ]

    by_key = {entry["key"]: entry for entry in tree}
    assert by_key["prompts/root.md"]["is_direct"] is True
    assert by_key["docs/inline.md"]["is_direct"] is True
    assert by_key["docs/shared.md"]["is_direct"] is False
    assert by_key["docs/nested.md"]["is_direct"] is False
    assert by_key["<content>"]["is_direct"] is True
