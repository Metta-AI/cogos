from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelMessage, ChannelType, Delivery, DeliveryStatus, Handler, Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor import handler as executor_handler


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


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

    monkeypatch.setattr(executor_handler, "_load_includes", lambda repo: "")

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
