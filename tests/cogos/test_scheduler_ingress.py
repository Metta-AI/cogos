from uuid import UUID

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelMessage, ChannelType, DeliveryStatus, Handler, Process, ProcessMode, ProcessStatus, RunStatus
from cogos.runtime.ingress import dispatch_ready_processes


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _daemon(name: str, *, status: ProcessStatus = ProcessStatus.WAITING) -> Process:
    return Process(
        name=name,
        mode=ProcessMode.DAEMON,
        status=status,
        runner="lambda",
    )


def _setup_channel_and_handler(repo, proc, channel_name="io:discord:dm"):
    """Create a channel + handler + message for the process."""
    ch = Channel(name=channel_name, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name(channel_name)
    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)
    msg = ChannelMessage(channel=ch.id, payload={"content": "hello"})
    repo.append_channel_message(msg)
    return ch, handler, msg


def test_match_messages_idempotent_per_handler(tmp_path):
    """append_channel_message creates inline deliveries; match_messages is a backstop
    that picks up handlers added after the message was written."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc1 = _daemon("discord-one")
    repo.upsert_process(proc1)

    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name("io:discord:dm")

    repo.create_handler(Handler(process=proc1.id, channel=ch.id))
    repo.append_channel_message(ChannelMessage(channel=ch.id, payload={"content": "hi"}))

    # Inline delivery already created by append_channel_message — backstop finds 0 new
    first = scheduler.match_messages()
    assert first.deliveries_created == 0

    # Add a second handler after the message — backstop should pick it up
    proc2 = _daemon("discord-two")
    repo.upsert_process(proc2)
    repo.create_handler(Handler(process=proc2.id, channel=ch.id))

    second = scheduler.match_messages()
    assert second.deliveries_created == 1
    assert second.deliveries[0].process_id == str(proc2.id)


def test_match_and_dispatch(tmp_path):
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = _daemon("discord-daemon")
    repo.upsert_process(proc)
    ch, handler, msg = _setup_channel_and_handler(repo, proc)

    # Inline delivery already created by append_channel_message
    assert repo.get_process(proc.id).status == ProcessStatus.RUNNABLE

    class _LambdaClient:
        def __init__(self) -> None:
            self.invocations: list[dict] = []

        def invoke(self, **kwargs):
            self.invocations.append(kwargs)
            return {"StatusCode": 202}

    lambda_client = _LambdaClient()
    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        lambda_client,
        "executor-fn",
        {proc.id},
    )

    assert dispatched == 1
    assert len(lambda_client.invocations) == 1
    assert len(repo.list_runs(process_id=proc.id)) == 1
    assert repo.get_process(proc.id).status == ProcessStatus.RUNNING
    delivery = next(iter(repo._deliveries.values()))
    assert delivery.status == DeliveryStatus.QUEUED


def test_dispatch_rolls_back_failed_invoke(tmp_path):
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = _daemon("discord-daemon")
    repo.upsert_process(proc)
    _setup_channel_and_handler(repo, proc)

    scheduler.match_messages()

    class _LambdaClient:
        def invoke(self, **_kwargs):
            raise RuntimeError("invoke failed")

    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        _LambdaClient(),
        "executor-fn",
        {proc.id},
    )

    assert dispatched == 0
    assert repo.get_process(proc.id).status == ProcessStatus.RUNNABLE
    assert len(repo.get_pending_deliveries(proc.id)) == 1
    runs = repo.list_runs(process_id=proc.id)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    delivery = next(iter(repo._deliveries.values()))
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.run is None
