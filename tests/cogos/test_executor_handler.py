import json
from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Channel, ChannelMessage, ChannelType, Delivery, DeliveryStatus, Handler, Process, ProcessCapability, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.files.store import FileStore
from cogos.executor import handler as executor_handler
from cogos.runtime.local import run_and_complete


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _make_run(repo: LocalRepository, process: Process) -> Run:
    run = Run(process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    return run


def _read_json(store: FileStore, key: str) -> dict:
    content = store.get_content(key)
    assert content is not None
    return json.loads(content)


class _FakeBedrock:
    def __init__(self, responses: list[dict]) -> None:
        self.calls: list[dict] = []
        self.responses = list(responses)

    def converse(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs)))
        return self.responses.pop(0)


def _text_response(text: str, *, input_tokens: int = 3, output_tokens: int = 2) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
        "stopReason": "end_turn",
    }


def test_executor_recreates_missing_dispatch_run(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="discord-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )
    repo.upsert_process(process)

    monkeypatch.setattr(executor_handler, "get_repo", lambda config=None: repo)
    monkeypatch.setattr(executor_handler.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        executor_handler,
        "execute_process",
        lambda process, event_data, run, config, repo, **kwargs: run,
    )
    missing_run_id = uuid4()

    result = executor_handler.handler(
        {"process_id": str(process.id), "run_id": str(missing_run_id)},
        None,
    )

    assert result["statusCode"] == 200
    runs = repo.list_runs(process_id=process.id)
    assert len(runs) == 1
    assert runs[0].id == missing_run_id
    assert runs[0].status == RunStatus.COMPLETED


def test_daemon_returns_to_runnable_when_more_deliveries_wait(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="discord-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )
    repo.upsert_process(process)

    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name("io:discord:dm")

    handler = Handler(process=process.id, channel=ch.id)
    repo.create_handler(handler)

    current_msg = ChannelMessage(channel=ch.id, payload={"content": "hello"})
    queued_msg = ChannelMessage(channel=ch.id, payload={"content": "next"})
    repo.append_channel_message(current_msg)
    repo.append_channel_message(queued_msg)

    current_delivery_id, _ = repo.create_delivery(Delivery(message=current_msg.id, handler=handler.id))
    repo.create_delivery(Delivery(message=queued_msg.id, handler=handler.id))

    run = Run(process=process.id, message=current_msg.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    repo.mark_queued(current_delivery_id, run.id)

    monkeypatch.setattr(executor_handler, "get_repo", lambda config=None: repo)
    monkeypatch.setattr(
        executor_handler,
        "execute_process",
        lambda process, event_data, run, config, repo, **kwargs: run,
    )

    result = executor_handler.handler(
        {"process_id": str(process.id), "message_id": str(current_msg.id), "run_id": str(run.id)},
        None,
    )

    assert result["statusCode"] == 200
    assert repo.get_process(process.id).status == ProcessStatus.RUNNABLE
    assert repo.get_run(run.id).status == RunStatus.COMPLETED
    assert repo._deliveries[current_delivery_id].status == DeliveryStatus.DELIVERED


def test_daemon_failure_returns_to_waiting_without_pending_deliveries(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="discord-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )
    repo.upsert_process(process)

    monkeypatch.setattr(executor_handler, "get_repo", lambda config=None: repo)

    def _fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(executor_handler, "execute_process", _fail)

    result = executor_handler.handler(
        {"process_id": str(process.id)},
        None,
    )

    assert result["statusCode"] == 500
    runs = repo.list_runs(process_id=process.id)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    assert repo.get_process(process.id).status == ProcessStatus.WAITING


def test_daemon_failure_returns_to_runnable_when_more_deliveries_wait(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="discord-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )
    repo.upsert_process(process)

    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name("io:discord:dm")

    handler = Handler(process=process.id, channel=ch.id)
    repo.create_handler(handler)

    current_msg = ChannelMessage(channel=ch.id, payload={"content": "hello"})
    queued_msg = ChannelMessage(channel=ch.id, payload={"content": "next"})
    repo.append_channel_message(current_msg)
    repo.append_channel_message(queued_msg)

    current_delivery_id, _ = repo.create_delivery(Delivery(message=current_msg.id, handler=handler.id))
    queued_delivery_id, _ = repo.create_delivery(Delivery(message=queued_msg.id, handler=handler.id))

    run = Run(process=process.id, message=current_msg.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    repo.mark_queued(current_delivery_id, run.id)

    monkeypatch.setattr(executor_handler, "get_repo", lambda config=None: repo)

    def _fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(executor_handler, "execute_process", _fail)

    result = executor_handler.handler(
        {"process_id": str(process.id), "message_id": str(current_msg.id), "run_id": str(run.id)},
        None,
    )

    assert result["statusCode"] == 500
    assert repo.get_process(process.id).status == ProcessStatus.RUNNABLE
    assert repo.get_run(run.id).status == RunStatus.FAILED
    assert repo._deliveries[current_delivery_id].status == DeliveryStatus.DELIVERED
    assert repo._deliveries[queued_delivery_id].status == DeliveryStatus.PENDING


def test_execute_process_rewrites_invalid_tool_names(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="discord-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Handle the incoming Discord message.",
    )
    run = Run(process=process.id, status=RunStatus.RUNNING)
    config = executor_handler.ExecutorConfig(max_turns=3)

    class FakeBedrock:
        def __init__(self):
            self.calls = []
            self.responses = [
                {
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [{
                                "toolUse": {
                                    "toolUseId": "tool-1",
                                    "name": "bad tool",
                                    "input": {},
                                }
                            }],
                        }
                    },
                    "usage": {"inputTokens": 11, "outputTokens": 7},
                    "stopReason": "tool_use",
                },
                {
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [{"text": "done"}],
                        }
                    },
                    "usage": {"inputTokens": 13, "outputTokens": 5},
                    "stopReason": "end_turn",
                },
            ]

        def converse(self, **kwargs):
            self.calls.append(kwargs)
            return self.responses.pop(0)

    fake_bedrock = FakeBedrock()

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")

    result = executor_handler.execute_process(
        process,
        {"payload": {"content": "hello"}},
        run,
        config,
        repo,
        bedrock_client=fake_bedrock,
    )

    assert result.tokens_in == 24
    assert result.tokens_out == 12
    assert len(fake_bedrock.calls) == 2
    second_messages = fake_bedrock.calls[1]["messages"]
    assert second_messages[1]["content"][0]["toolUse"]["name"] == "search"
    assert second_messages[2]["content"][0]["toolResult"]["toolUseId"] == "tool-1"
    assert "invalid tool name 'bad tool'" in second_messages[2]["content"][0]["toolResult"]["content"][0]["text"]


def test_execute_process_expands_prompt_refs_into_system_prompt(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    store = FileStore(repo)
    store.upsert("docs/shared.md", "Shared context", source="test")
    store.upsert("prompt.md", "Prompt body\n@{docs/shared.md}", source="test")

    process = Process(
        name="worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Intro\n@{prompt.md}",
    )
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
    run = Run(process=process.id, status=RunStatus.RUNNING)
    config = executor_handler.ExecutorConfig(max_turns=1)

    class FakeBedrock:
        def __init__(self):
            self.calls = []

        def converse(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "output": {"message": {"role": "assistant", "content": [{"text": "done"}]}},
                "usage": {"inputTokens": 3, "outputTokens": 2},
                "stopReason": "end_turn",
            }

    fake_bedrock = FakeBedrock()

    executor_handler.execute_process(
        process,
        {},
        run,
        config,
        repo,
        bedrock_client=fake_bedrock,
    )

    first_call = fake_bedrock.calls[0]
    assert first_call["messages"][0]["content"][0]["text"] == "Execute your task."
    assert first_call["system"][0]["text"] == (
        "Intro\n"
        "--- prompt.md ---\n"
        "Prompt body\n"
        "--- docs/shared.md ---\n"
        "Shared context"
    )


def test_stateless_process_writes_session_artifacts_and_snapshot(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="stateless-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="local",
        content="Handle a single event.",
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    fake_bedrock = _FakeBedrock([_text_response("done")])

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")

    run_and_complete(
        process,
        {"payload": {"content": "hello"}},
        run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=fake_bedrock,
    )

    stored_run = repo.get_run(run.id)
    assert stored_run.status == RunStatus.COMPLETED
    assert stored_run.snapshot is not None
    assert stored_run.snapshot["resumed"] is False
    assert stored_run.snapshot["checkpoint_key"] is None

    store = FileStore(repo)
    final_artifact = _read_json(store, stored_run.snapshot["final_key"])
    manifest = _read_json(store, stored_run.snapshot["manifest_key"])
    step_files = store.list_files(prefix=final_artifact["steps_key"])

    assert final_artifact["status"] == RunStatus.COMPLETED.value
    assert final_artifact["final_stop_reason"] == "end_turn"
    assert final_artifact["resume_skipped_reason"] is None
    assert final_artifact["session_scope"] == "process"
    assert final_artifact["session_path"].startswith("log-only-")
    assert manifest["latest_run_id"] == str(run.id)
    assert manifest["session_scope"] == "process"
    assert manifest["session_path"].startswith("log-only-")
    assert len(step_files) == 3


def test_process_session_loads_previous_checkpoint(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="reentrant-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="local",
        content="Continue the conversation.",
        metadata={"session": {"resume": True, "scope": "process"}},
    )
    repo.upsert_process(process)

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")

    first_run = _make_run(repo, process)
    run_and_complete(
        process,
        {"payload": {"content": "hello-1"}},
        first_run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=_FakeBedrock([_text_response("first-response")]),
    )

    second_run = _make_run(repo, process)
    fake_bedrock = _FakeBedrock([_text_response("second-response")])
    run_and_complete(
        process,
        {"payload": {"content": "hello-2"}},
        second_run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=fake_bedrock,
    )

    second_call_messages = fake_bedrock.calls[0]["messages"]
    assert len(second_call_messages) == 3
    assert second_call_messages[0]["role"] == "user"
    assert "hello-1" in second_call_messages[0]["content"][0]["text"]
    assert second_call_messages[1]["role"] == "assistant"
    assert second_call_messages[1]["content"][0]["text"] == "first-response"
    assert second_call_messages[2]["role"] == "user"
    assert "hello-2" in second_call_messages[2]["content"][0]["text"]

    stored_run = repo.get_run(second_run.id)
    assert stored_run.snapshot["resumed"] is True
    assert stored_run.snapshot["resumed_from_run_id"] == str(first_run.id)
    assert stored_run.snapshot["resume_skipped_reason"] is None


def test_legacy_session_mode_process_still_resumes(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="legacy-reentrant-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="local",
        content="Continue the conversation.",
        metadata={"session": {"mode": "process"}},
    )
    repo.upsert_process(process)

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")

    first_run = _make_run(repo, process)
    run_and_complete(
        process,
        {"payload": {"content": "hello-1"}},
        first_run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=_FakeBedrock([_text_response("first-response")]),
    )

    second_run = _make_run(repo, process)
    second_bedrock = _FakeBedrock([_text_response("second-response")])
    run_and_complete(
        process,
        {"payload": {"content": "hello-2"}},
        second_run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=second_bedrock,
    )

    second_call_messages = second_bedrock.calls[0]["messages"]
    assert len(second_call_messages) == 3
    assert second_call_messages[1]["content"][0]["text"] == "first-response"

    stored_run = repo.get_run(second_run.id)
    assert stored_run.snapshot["resumed"] is True


def test_checkpoint_survives_failure_after_assistant_step(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="tool-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="local",
        content="Use tools when needed.",
        max_retries=1,
        metadata={"session": {"resume": True, "scope": "process"}},
    )
    repo.upsert_process(process)

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")

    def _raise_on_execute(self, _code: str) -> str:
        raise RuntimeError("tool boom")

    monkeypatch.setattr(executor_handler.SandboxExecutor, "execute", _raise_on_execute)

    first_run = _make_run(repo, process)
    first_bedrock = _FakeBedrock([{
        "output": {
            "message": {
                "role": "assistant",
                "content": [{
                    "toolUse": {
                        "toolUseId": "tool-1",
                        "name": "run_code",
                        "input": {"code": "print('hello')"},
                    }
                }],
            }
        },
        "usage": {"inputTokens": 7, "outputTokens": 5},
        "stopReason": "tool_use",
    }])

    run_and_complete(
        process,
        {"payload": {"content": "first"}},
        first_run,
        executor_handler.ExecutorConfig(max_turns=2),
        repo,
        bedrock_client=first_bedrock,
    )

    failed_run = repo.get_run(first_run.id)
    assert failed_run.status == RunStatus.FAILED

    checkpoint = _read_json(FileStore(repo), failed_run.snapshot["checkpoint_key"])
    assert checkpoint["messages"][1]["content"][0]["toolUse"]["name"] == "run_code"

    monkeypatch.setattr(executor_handler.SandboxExecutor, "execute", lambda self, _code: "ok")

    second_run = _make_run(repo, process)
    second_bedrock = _FakeBedrock([_text_response("done")])
    run_and_complete(
        process,
        {"payload": {"content": "second"}},
        second_run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=second_bedrock,
    )

    resumed_messages = second_bedrock.calls[0]["messages"]
    assert len(resumed_messages) == 3
    assert resumed_messages[1]["content"][0]["toolUse"]["name"] == "run_code"
    assert "second" in resumed_messages[2]["content"][0]["text"]

    stored_run = repo.get_run(second_run.id)
    assert stored_run.snapshot["resumed"] is True
    assert stored_run.snapshot["resumed_from_run_id"] == str(first_run.id)


def test_prompt_change_skips_resume(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="drift-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="local",
        content="Original instructions.",
        metadata={"session": {"resume": True, "scope": "process"}},
    )
    repo.upsert_process(process)

    first_run = _make_run(repo, process)
    run_and_complete(
        process,
        {"payload": {"content": "first"}},
        first_run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=_FakeBedrock([_text_response("done")]),
    )

    process.content = "Changed instructions."
    repo.upsert_process(process)

    second_run = _make_run(repo, process)
    second_bedrock = _FakeBedrock([_text_response("done-again")])
    run_and_complete(
        process,
        {"payload": {"content": "second"}},
        second_run,
        executor_handler.ExecutorConfig(max_turns=1),
        repo,
        bedrock_client=second_bedrock,
    )

    second_call_messages = second_bedrock.calls[0]["messages"]
    assert len(second_call_messages) == 1
    assert "second" in second_call_messages[0]["content"][0]["text"]

    stored_run = repo.get_run(second_run.id)
    assert stored_run.snapshot["resumed"] is False
    assert stored_run.snapshot["resume_skipped_reason"] == "prompt_fingerprint_changed"


def test_python_executor_runs_code_directly(monkeypatch, tmp_path):
    """Python executor resolves content and runs it in sandbox — no Bedrock."""
    repo = _repo(tmp_path)

    process = Process(
        name="py-proc",
        mode=ProcessMode.ONE_SHOT,
        executor="python",
        content="print('hello from python')",
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)

    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    result_run = executor_handler.execute_process(
        process, {"process_id": str(process.id)}, run, config, repo,
    )

    assert result_run.result == {"output": "hello from python"}
    assert result_run.tokens_in == 0
    assert result_run.tokens_out == 0


def test_python_executor_receives_event_payload(monkeypatch, tmp_path):
    """Python executor can access the triggering event via `event` variable."""
    repo = _repo(tmp_path)
    process = Process(
        name="py-event",
        mode=ProcessMode.ONE_SHOT,
        executor="python",
        content="print(event.get('payload', {}).get('msg', 'none'))",
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    result_run = executor_handler.execute_process(
        process,
        {"process_id": str(process.id), "payload": {"msg": "hi"}},
        run, config, repo,
    )

    assert result_run.result == {"output": "hi"}


def test_python_executor_resolves_file_refs(monkeypatch, tmp_path):
    """Python executor resolves @{...} refs in content before executing."""
    repo = _repo(tmp_path)
    file_store = FileStore(repo)
    file_store.upsert("apps/greet/config.txt", "world", source="image")

    process = Process(
        name="py-ref",
        mode=ProcessMode.ONE_SHOT,
        executor="python",
        content='data = """\n@{apps/greet/config.txt}\n"""\nprint(data.splitlines()[-1])',
        status=ProcessStatus.RUNNING,
    )
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
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    result_run = executor_handler.execute_process(
        process,
        {"process_id": str(process.id)},
        run, config, repo,
    )

    assert result_run.result == {"output": "world"}


def test_python_executor_error_captured_in_run(monkeypatch, tmp_path):
    """Python executor errors are captured as traceback in run result."""
    repo = _repo(tmp_path)
    process = Process(
        name="py-err",
        mode=ProcessMode.ONE_SHOT,
        executor="python",
        content="raise ValueError('boom')",
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    result_run = executor_handler.execute_process(
        process,
        {"process_id": str(process.id)},
        run, config, repo,
    )

    assert "ValueError" in result_run.result["output"]
    assert "boom" in result_run.result["output"]


def _tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str = "tool-1",
                        text: str | None = None,
                        input_tokens: int = 5, output_tokens: int = 3) -> dict:
    content = []
    if text:
        content.append({"text": text})
    content.append({"toolUse": {"toolUseId": tool_use_id, "name": tool_name, "input": tool_input}})
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
        "stopReason": "tool_use",
    }


def test_per_process_io_channels_created_on_execute(monkeypatch, tmp_path):
    """Executing a process creates process:<name>:stdout/stderr/stdin channels."""
    repo = _repo(tmp_path)
    process = Process(
        name="io-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Do work.",
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig(max_turns=1)
    fake_bedrock = _FakeBedrock([_text_response("all done")])

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")

    executor_handler.execute_process(process, {}, run, config, repo, bedrock_client=fake_bedrock)

    for suffix in ("stdout", "stderr", "stdin"):
        ch = repo.get_channel_by_name(f"process:io-worker:{suffix}")
        assert ch is not None, f"Channel process:io-worker:{suffix} was not created"


def test_run_code_output_published_to_process_stdout(monkeypatch, tmp_path):
    """run_code output is written to the process:<name>:stdout channel."""
    repo = _repo(tmp_path)
    process = Process(
        name="code-runner",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Run code.",
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig(max_turns=3)

    responses = [
        _tool_use_response("run_code", {"code": "print('hello world')"}),
        _text_response("done"),
    ]
    fake_bedrock = _FakeBedrock(responses)

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")
    monkeypatch.setattr(executor_handler.SandboxExecutor, "execute", lambda self, code: "hello world")

    executor_handler.execute_process(process, {}, run, config, repo, bedrock_client=fake_bedrock)

    ch = repo.get_channel_by_name("process:code-runner:stdout")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=10)
    texts = [m.payload.get("text", "") for m in msgs]
    assert any("hello world" in t for t in texts)


def test_final_assistant_text_published_to_process_stderr(monkeypatch, tmp_path):
    """Final assistant commentary is written to process:<name>:stderr."""
    repo = _repo(tmp_path)
    process = Process(
        name="chat-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Chat.",
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig(max_turns=1)
    fake_bedrock = _FakeBedrock([_text_response("final words")])

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")

    executor_handler.execute_process(process, {}, run, config, repo, bedrock_client=fake_bedrock)

    ch = repo.get_channel_by_name("process:chat-worker:stderr")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=10)
    texts = [m.payload.get("text", "") for m in msgs]
    assert any("final words" in t for t in texts)


def test_intermediate_assistant_text_published_to_stdout(monkeypatch, tmp_path):
    """Assistant text blocks during tool_use turns are written to process:<name>:stdout."""
    repo = _repo(tmp_path)
    process = Process(
        name="think-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Think and act.",
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig(max_turns=3)

    responses = [
        _tool_use_response("run_code", {"code": "1+1"}, text="Let me think about this..."),
        _text_response("done"),
    ]
    fake_bedrock = _FakeBedrock(responses)

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")
    monkeypatch.setattr(executor_handler.SandboxExecutor, "execute", lambda self, code: "2")

    executor_handler.execute_process(process, {}, run, config, repo, bedrock_client=fake_bedrock)

    ch = repo.get_channel_by_name("process:think-worker:stdout")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=10)
    texts = [m.payload.get("text", "") for m in msgs]
    assert any("Let me think about this" in t for t in texts)


def test_tty_forwards_to_global_io_channels(monkeypatch, tmp_path):
    """When process.tty=True, output is also forwarded to io:stdout / io:stderr."""
    repo = _repo(tmp_path)

    # Create global io channels
    for name in ("io:stdout", "io:stderr"):
        repo.upsert_channel(Channel(name=name, channel_type=ChannelType.NAMED))

    process = Process(
        name="tty-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Run with tty.",
        tty=True,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig(max_turns=3)

    responses = [
        _tool_use_response("run_code", {"code": "print('tty output')"}),
        _text_response("tty final"),
    ]
    fake_bedrock = _FakeBedrock(responses)

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")
    monkeypatch.setattr(executor_handler.SandboxExecutor, "execute", lambda self, code: "tty output")

    executor_handler.execute_process(process, {}, run, config, repo, bedrock_client=fake_bedrock)

    # Check global io:stdout got the run_code output
    io_stdout = repo.get_channel_by_name("io:stdout")
    assert io_stdout is not None
    stdout_msgs = repo.list_channel_messages(io_stdout.id, limit=10)
    stdout_texts = [m.payload.get("text", "") for m in stdout_msgs]
    assert any("tty output" in t for t in stdout_texts)

    # Check global io:stderr got the final commentary
    io_stderr = repo.get_channel_by_name("io:stderr")
    assert io_stderr is not None
    stderr_msgs = repo.list_channel_messages(io_stderr.id, limit=10)
    stderr_texts = [m.payload.get("text", "") for m in stderr_msgs]
    assert any("tty final" in t for t in stderr_texts)


def test_no_tty_does_not_forward_to_global_io(monkeypatch, tmp_path):
    """When process.tty=False, output goes to per-process channels only, not io:stdout/stderr."""
    repo = _repo(tmp_path)

    # Create global io channels
    for name in ("io:stdout", "io:stderr"):
        repo.upsert_channel(Channel(name=name, channel_type=ChannelType.NAMED))

    process = Process(
        name="no-tty-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Run without tty.",
        tty=False,
    )
    repo.upsert_process(process)
    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig(max_turns=3)

    responses = [
        _tool_use_response("run_code", {"code": "print('quiet')"}),
        _text_response("quiet final"),
    ]
    fake_bedrock = _FakeBedrock(responses)

    monkeypatch.setattr("cogos.files.context_engine.ContextEngine.generate_full_prompt", lambda self, process: "")
    monkeypatch.setattr(executor_handler.SandboxExecutor, "execute", lambda self, code: "quiet")

    executor_handler.execute_process(process, {}, run, config, repo, bedrock_client=fake_bedrock)

    # Per-process channels should have messages
    ch = repo.get_channel_by_name("process:no-tty-worker:stdout")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) > 0

    # Global io channels should be empty
    io_stdout = repo.get_channel_by_name("io:stdout")
    io_stderr = repo.get_channel_by_name("io:stderr")
    assert len(repo.list_channel_messages(io_stdout.id, limit=10)) == 0
    assert len(repo.list_channel_messages(io_stderr.id, limit=10)) == 0


def test_python_executor_handles_web_request(monkeypatch, tmp_path):
    """Python executor process can handle web requests via web.respond()."""
    repo = _repo(tmp_path)

    # Register web capability
    web_cap_model = Capability(name="web", handler="cogos.io.web.capability.WebCapability")
    repo.upsert_capability(web_cap_model)

    process = Process(
        name="web-handler",
        mode=ProcessMode.DAEMON,
        executor="python",
        content='''
req = event.get("web_request", {})
request_id = event.get("web_request_id", "")
path = req.get("path", "/")
route = path.removeprefix("/api").strip("/")
if route == "status":
    web.respond(request_id, status=200, headers={"content-type": "application/json"}, body=json.dumps({"status": "ok"}))
else:
    web.respond(request_id, status=404, headers={"content-type": "application/json"}, body=json.dumps({"error": "not found"}))
''',
        status=ProcessStatus.RUNNING,
    )
    repo.upsert_process(process)

    # Bind web capability to process
    repo.create_process_capability(
        ProcessCapability(process=process.id, capability=web_cap_model.id, name="web")
    )

    run = _make_run(repo, process)
    config = executor_handler.ExecutorConfig()

    result_run = executor_handler.execute_process(
        process,
        {
            "process_id": str(process.id),
            "web_request_id": "req-123",
            "web_request": {
                "method": "GET",
                "path": "/api/status",
                "query": {},
                "headers": {},
                "body": None,
            },
        },
        run, config, repo,
    )

    # No LLM calls — Python executor runs code directly
    assert result_run.tokens_in == 0
    assert result_run.tokens_out == 0
