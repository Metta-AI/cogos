from cogos.io.base import IOMode, InboundEvent
from cogos.io.asana import AsanaIO


class TestAsanaIO:
    def test_mode_is_poll(self):
        ch = AsanaIO(name="asana")
        assert ch.mode == IOMode.POLL

    async def test_poll_returns_queued_events(self):
        ch = AsanaIO(name="asana")
        event = InboundEvent(
            channel="asana", event_type="task.assigned",
            payload={"gid": "12345"}, raw_content="Build the thing",
            author="human", external_id="asana:task:12345",
        )
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].author == "human"

    async def test_poll_without_client_returns_empty(self):
        ch = AsanaIO(name="asana")
        events = await ch.poll()
        assert len(events) == 0
