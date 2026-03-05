from channels.base import ChannelMode, InboundEvent
from channels.discord import DiscordChannel


class TestDiscordChannel:
    def test_mode_is_live(self):
        ch = DiscordChannel(name="discord")
        assert ch.mode == ChannelMode.LIVE

    async def test_poll_returns_queued_events(self):
        ch = DiscordChannel(name="discord")
        event = InboundEvent(channel="discord", event_type="dm", payload={}, raw_content="hi")
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].event_type == "dm"

    async def test_poll_drains_queue(self):
        ch = DiscordChannel(name="discord")
        for i in range(3):
            ch.add_event(InboundEvent(channel="discord", event_type=f"event.{i}", payload={}))
        events = await ch.poll()
        assert len(events) == 3
        events = await ch.poll()
        assert len(events) == 0

    async def test_start_without_token_is_noop(self):
        ch = DiscordChannel(name="discord")
        await ch.start()
