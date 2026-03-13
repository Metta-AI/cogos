from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Process, ProcessCapability
from cogos.files.context_engine import ContextEngine
from cogos.files.store import FileStore


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _upsert_capability(repo: LocalRepository, name: str) -> Capability:
    cap = repo.get_capability_by_name(name)
    if cap is not None:
        return cap
    cap = Capability(name=name, handler="cogos.capabilities.files.FilesCapability")
    repo.upsert_capability(cap)
    return repo.get_capability_by_name(name)


def _grant(repo: LocalRepository, process: Process, cap_name: str, *, config: dict | None = None) -> None:
    cap = _upsert_capability(repo, cap_name)
    repo.create_process_capability(
        ProcessCapability(
            process=process.id,
            capability=cap.id,
            name=f"{cap_name}-{uuid4()}",
            config=config,
        )
    )


def _put_file(repo: LocalRepository, key: str, content: str, *, includes: list[str] | None = None) -> None:
    FileStore(repo).create(key, content, includes=includes)


def test_inline_includes_render_markers_and_deduped_bundle(tmp_path):
    repo = _repo(tmp_path)
    _put_file(repo, "whoami/index", "You are Acme support. Be brief, direct, and accurate.")
    _put_file(
        repo,
        "playbooks/refunds",
        "Refunds under $100 can be approved immediately.\nFor larger refunds:\n@{playbooks/escalation}",
    )
    _put_file(
        repo,
        "playbooks/escalation",
        "Ask for the order ID and explain that a human reviewer will follow up.",
    )

    process = Process(
        name="support",
        content="Handle inbound support messages.\n\n@{whoami/index}\n\nWhen the message is about billing:\n@{playbooks/refunds}",
    )
    repo.upsert_process(process)
    _grant(repo, process, "file", config={"key": "whoami/index", "ops": ["read"]})
    _grant(repo, process, "dir", config={"prefix": "playbooks/", "ops": ["read"]})

    prompt = ContextEngine(repo).generate_full_prompt(process)

    assert prompt == (
        "Handle inbound support messages.\n\n"
        "<!-- uses: whoami/index -->\n\n"
        "When the message is about billing:\n"
        "<!-- uses: playbooks/refunds -->\n\n"
        "<!-- included: whoami/index -->\n"
        "You are Acme support. Be brief, direct, and accurate.\n\n"
        "<!-- included: playbooks/escalation -->\n"
        "Ask for the order ID and explain that a human reviewer will follow up.\n\n"
        "<!-- included: playbooks/refunds -->\n"
        "Refunds under $100 can be approved immediately.\n"
        "For larger refunds:\n"
        "<!-- uses: playbooks/escalation -->"
    )


def test_access_denied_inline_include_renders_in_place_error(tmp_path):
    repo = _repo(tmp_path)
    _put_file(repo, "whoami/index", "secret")

    process = Process(name="limited", content="Top secret? @{whoami/index}")
    repo.upsert_process(process)
    _grant(repo, process, "dir", config={"prefix": "workspace/", "ops": ["read"]})

    prompt = ContextEngine(repo).generate_full_prompt(process)

    assert prompt == "Top secret? <!-- include error: access denied whoami/index -->"


def test_legacy_file_metadata_includes_use_same_bundle_resolution(tmp_path):
    repo = _repo(tmp_path)
    _put_file(repo, "playbooks/refunds", "Refund flow")
    store = FileStore(repo)
    main = store.create("prompts/main", "Use the latest refund playbook.", includes=["playbooks/refunds"])

    process = Process(name="legacy", files=[main.id])
    repo.upsert_process(process)
    _grant(repo, process, "dir", config={"prefix": "playbooks/", "ops": ["read"]})

    prompt = ContextEngine(repo).generate_full_prompt(process)

    assert prompt == (
        "<!-- uses: playbooks/refunds -->\n\n"
        "Use the latest refund playbook.\n\n"
        "<!-- included: playbooks/refunds -->\n"
        "Refund flow"
    )


def test_global_include_files_only_apply_when_process_can_read_them(tmp_path):
    repo = _repo(tmp_path)
    _put_file(repo, "cogos/includes/code_mode", "You may write Python when needed.")

    process = Process(name="worker", content="Handle the job.")
    repo.upsert_process(process)

    prompt_without_grant = ContextEngine(repo).generate_full_prompt(process)
    assert prompt_without_grant == "Handle the job."

    _grant(repo, process, "dir", config={"prefix": "cogos/includes/", "ops": ["read"]})
    prompt_with_grant = ContextEngine(repo).generate_full_prompt(process)
    assert prompt_with_grant == "You may write Python when needed.\n\nHandle the job."
