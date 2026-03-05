# Channels Design

Channels are pure IO for the agent brain — eyes, ears, hands. Each channel knows how to receive events and (optionally) send messages in its native protocol. No classification, sanitization, or backpressure — that's brain-side.

## Channel Modes

- **Live** — persistent connection, pushes events via callback (Discord)
- **Poll** — periodic check, returns new events (Gmail, Asana, Calendar)
- **On-demand** — receives external pushes via HTTP endpoint (GitHub)

## Package Structure

```
src/channels/
    __init__.py
    base.py              # Channel ABC, InboundEvent, ChannelMode
    access.py            # Token management (AWS Secrets Manager + env fallback)
    cli.py               # channels list/create/destroy/status/logs/send
    discord/
        __init__.py
        listener.py      # Live: Gateway via discord.py
        sender.py        # Post to channel/DM
        guide.md
    github/
        __init__.py
        webhook.py       # On-demand: HMAC-verified webhook receiver
        sender.py        # Comment on issues/PRs
        guide.md
    gmail/
        __init__.py
        poller.py        # Poll: is:inbox is:unread via service account
        sender.py        # Send email
        guide.md
    asana/
        __init__.py
        poller.py        # Poll: task assignments + comments
        sender.py        # Create tasks/comments
        guide.md
    calendar/
        __init__.py
        poller.py        # Poll: upcoming events in lookahead window
        guide.md         # Shares Google service account with Gmail
```

## Base Abstractions

```python
class ChannelMode(Enum):
    LIVE = "live"
    POLL = "poll"
    ON_DEMAND = "on_demand"

@dataclass
class InboundEvent:
    channel: str            # "discord", "github", "gmail", etc.
    event_type: str         # Raw event type from source
    payload: dict           # Raw payload, no interpretation
    raw_content: str        # Human-readable content if any
    author: str | None
    timestamp: datetime
    external_id: str | None
    external_url: str | None

class Channel(ABC):
    mode: ChannelMode
    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def poll(self) -> list[InboundEvent]: ...
    async def send(self, message: str, target: str, **kwargs) -> None: ...
```

Live channels receive an `on_event` callback at construction and push events through it. Poll and on-demand channels return events from `poll()`.

## Channels

| Channel  | Mode      | Inbound                                  | Outbound               |
|----------|-----------|------------------------------------------|------------------------|
| Discord  | live      | Gateway: DMs, mentions, channel messages | Post to channel/DM     |
| GitHub   | on-demand | Webhooks with HMAC-SHA256 verification   | Comment on issues/PRs  |
| Gmail    | poll      | `is:inbox is:unread` via service account | Send email             |
| Asana    | poll      | Task assignments + new comments          | Create tasks/comments  |
| Calendar | poll      | Upcoming events in lookahead window      | None                   |

## Token Management

`access.py` provides `get_channel_token()` and `get_channel_secret()` — fetches from AWS Secrets Manager, falls back to environment variables. Calendar shares the Gmail service account credential (same Google service account, extended with calendar API scopes).

## CLI

`channels` command with subcommands:

- `list` — list provisioned channels from Secrets Manager
- `create <channel>` — interactive provisioning with guide display
- `destroy <channel>` — remove channel from Secrets Manager
- `status` — token health and rotation status
- `logs` — tail CloudWatch logs (listener or proxy mode)
- `send <channel>` — send a test message

Channel credential types:
- `static` — Discord (bot token), Asana (PAT)
- `github_app` — GitHub App with JWT auto-rotation
- `service_account` — Gmail + Calendar (Google service account with domain-wide delegation)

## Deployment

- **Discord** — long-running ECS task (persistent Gateway connection)
- **Gmail, Asana, Calendar** — Lambda pollers triggered by EventBridge schedule
- **GitHub** — Lambda behind API Gateway receiving webhooks

Lambda handlers are thin wrappers: instantiate channel, call `poll()`, publish `InboundEvent`s to EventBridge.

## Boundary

Channels are pure IO. The brain handles:
- Event classification and priority
- Input sanitization and prompt injection detection
- Secret redaction on outbound messages
- Backpressure and deduplication
