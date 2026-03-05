# Discord Bridge Design

## Goal

Port the Discord bridge from metta-ai/cogent into cogents.2. The bridge is a standalone Fargate service that acts as a bidirectional relay between Discord and the cogent event system (EventBridge inbound, SQS outbound).

## Architecture

The bridge **replaces** the existing DiscordChannel and DiscordSender. There is no Channel ABC subclass for Discord — the bridge owns all Discord IO, and the brain communicates exclusively through EventBridge (receiving events) and SQS (sending replies via helper functions).

```
┌─────────────┐         ┌──────────────────┐         ┌──────────────┐
│ Discord API │◄───────►│  Discord Bridge   │────────►│ EventBridge  │
│ (Gateway)   │         │  (ECS Fargate)    │         │ Bus          │
└─────────────┘         └──────────────────┘         └──────────────┘
                                │ ▲                         │
                                │ │                         ▼
                        ┌───────┴─┴───────┐          ┌──────────────┐
                        │   SQS Queue     │◄─────────│ Brain /      │
                        │ discord-replies │          │ Executor     │
                        └─────────────────┘          └──────────────┘
```

## Package Structure

```
src/channels/discord/
├── __init__.py
├── bridge.py      # DiscordBridge: Gateway ↔ EventBridge/SQS relay
├── reply.py       # queue_reply, queue_reaction, queue_thread_create, queue_dm
├── guide.md       # Discord bot setup instructions
└── Dockerfile     # Fargate deployment image
```

## Bridge Service (`bridge.py`)

### Inbound: Discord → EventBridge

- Connects to Discord Gateway (message_content + dm_messages intents)
- Classifies messages into event types:
  - `discord:dm` — direct messages
  - `discord:mention` — @mentions of the bot
  - `discord:channel.message` — other guild messages
- Enriches payloads with:
  - Attachments: url, filename, content_type, size, is_image, width, height
  - Thread context: thread_id, parent_channel_id
  - Embeds: type, title, description, url, image_url
  - Reply reference: reference_message_id
- Publishes to EventBridge bus (`cogent-{name}-bus`)
- Starts typing indicator on DM/mention events

### Outbound: SQS → Discord

- Long-polls SQS queue (`cogent-{name}-discord-replies`) starting on `on_ready`
- Dispatches by message type:
  - `message` — text with optional file attachments, thread targeting, reply-to
  - `reaction` — add emoji reaction to a message
  - `thread_create` — create new thread on channel or message
  - `dm` — direct message to a user by user_id
- Chunks messages at Discord's 2000 char limit (splits on newline > space > hard cut)
- Downloads files from URLs, wraps as `discord.File` for upload
- Stops typing indicator before sending reply

### Token Management

Uses `channels.access.get_channel_token(cogent_name, "discord")` with `DISCORD_BOT_TOKEN` env var fallback.

### Entry Point

`main()` function for Fargate/Docker. Also exposed as `discord-bridge` console script via pyproject.toml.

## Reply Helpers (`reply.py`)

Clean API for the brain/executor to enqueue outbound messages without knowing SQS details:

- `queue_reply(channel, content, files, thread_id, reply_to)` — text + optional attachments
- `queue_reaction(channel, message_id, emoji)` — add emoji reaction
- `queue_thread_create(channel, thread_name, content, message_id)` — create thread
- `queue_dm(user_id, content)` — DM a user

SQS queue URL: constructed from cogent name (`cogent-{name}-discord-replies`), overridable via `DISCORD_REPLY_QUEUE_URL` env var.

## Changes to Existing Code

- **Delete** `src/channels/discord/listener.py` — bridge replaces it
- **Delete** `src/channels/discord/sender.py` — bridge replaces it
- **Delete** `tests/channels/test_discord.py` — rewrite for bridge
- **Update** `src/channels/__init__.py` — remove DiscordChannel export
- **Update** `tests/channels/test_integration.py` — remove Discord from Channel ABC tests
- **Update** `pyproject.toml` — add `discord-bridge` script entry point

## Deployment

- **Dockerfile**: Python 3.12 slim, installs cogent package, runs `discord-bridge`
- **Fargate**: 256 CPU / 512 MB, FARGATE_SPOT, desired count 1
- **Env vars**: COGENT_NAME, EVENT_BUS_NAME, DISCORD_REPLY_QUEUE_URL, AWS_REGION
- **Monitoring**: CloudWatch log group, alarm if 0 tasks running for 3+ minutes
