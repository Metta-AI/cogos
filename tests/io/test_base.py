from cogos.io.base import Channel, ChannelMode, InboundEvent
from datetime import datetime, timezone
import pytest


class TestInboundEvent:
    def test_create_minimal(self):
        event = InboundEvent(channel="discord", event_type="dm", payload={}, raw_content="hello")
        assert event.channel == "discord"
        assert event.event_type == "dm"
        assert event.author is None

    def test_create_full(self):
        now = datetime.now(timezone.utc)
        event = InboundEvent(
            channel="github",
            event_type="push",
            payload={"ref": "main"},
            raw_content="pushed to main",
            author="daveey",
            timestamp=now,
            external_id="github:push:123",
            external_url="https://github.com/org/repo/commit/abc",
        )
        assert event.payload == {"ref": "main"}
        assert event.author == "daveey"
        assert event.timestamp == now
        assert event.external_id == "github:push:123"


class TestChannelMode:
    def test_modes_exist(self):
        assert ChannelMode.LIVE.value == "live"
        assert ChannelMode.POLL.value == "poll"
        assert ChannelMode.ON_DEMAND.value == "on_demand"


class TestChannelABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Channel(name="test")
