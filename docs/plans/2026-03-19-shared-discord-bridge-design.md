# Shared Discord Bridge Design

## Problem

Each cogent currently runs its own Discord bot (separate app, token, bridge Fargate service, SQS queue). This doesn't scale — N cogents = N Discord apps to manage.

## Solution

A single Discord app and bridge service at the polis level, serving all cogents. Each cogent appears as a distinct persona via Discord webhooks (custom name/avatar) and is @-mentionable via auto-created Discord roles.

## Architecture

### Shared Bridge (polis-level service)

One bridge process runs on the `cogent-polis` cluster:

- **Single gateway connection** using one bot token (stored at `polis/discord` in Secrets Manager)
- **On startup and periodically (~60s):** queries cogent registry for Discord-enabled cogents, then for each guild:
  - Creates/updates a **mentionable role** per cogent (e.g. `@dr.alpha`)
  - Creates/updates **webhooks** per cogent per channel (named `cogent-{name}`, cached in memory)
  - Deletes roles/webhooks for removed cogents
- **Single SQS queue:** `cogent-polis-discord-replies` replaces per-cogent queues

### Inbound Routing

When a message arrives on the gateway:

1. **Role mention** (e.g. `@dr.alpha`) → route to that cogent. Update `(user_id, channel_id) → cogent` last-interaction map.
2. **No mention, in a thread** → route to the cogent active in that thread (first responder).
3. **No mention, channel has default cogent** → route to default.
4. **No match** → drop.
5. **Multiple mentions** → route to all mentioned cogents independently.

### DM Routing

1. Check `user_id → cogent` last-interaction map.
2. If exists, route to that cogent.
3. If user types a cogent name or `@name`, update mapping and route.
4. If no prior interaction, bot replies with available cogent list.

### Outbound

- Bridge polls single `cogent-polis-discord-replies` queue.
- Each reply message includes `cogent_name` in payload.
- Bridge sends via that cogent's webhook:
  ```
  webhook.send(
      content=reply_text,
      username="Dr. Alpha",
      avatar_url="https://...",
      thread_id=thread_id
  )
  ```
- Cogent appears with its own name and avatar in the channel.

### Scoped CogOS Channels

Capability channels are scoped by cogent name to prevent message bleed:

- `io:discord:{cogent_name}:dm`
- `io:discord:{cogent_name}:mention`
- `io:discord:{cogent_name}:message`
- `io:discord:{cogent_name}:message:{channel_id}`
- `io:discord:{cogent_name}:dm:{author_id}`
- `io:discord:{cogent_name}:reaction`

## Changes

### Bridge (`src/cogos/io/discord/bridge.py`)

- Multi-tenant: routes inbound by role mention, thread, channel default
- Role and webhook lifecycle management on startup + periodic sync
- Polls single `cogent-polis-discord-replies` queue
- Sends outbound via per-cogent webhooks
- Tracks `(user_id) → cogent` for DM routing
- DM switch detection

### Capability (`src/cogos/io/discord/capability.py`)

- Channels scoped: `io:discord:{cogent_name}:*`
- Replies sent to `cogent-polis-discord-replies` with `cogent_name` in payload

### CDK (`src/cogtainer/cdk/stack.py`)

**Remove from per-cogent stack:**
- Discord bridge Fargate service
- Bot token secret injection
- Per-cogent SQS reply queue

**Add to polis stack:**
- Shared bridge Fargate service
- Shared bot token secret (`polis/discord`)
- Single SQS queue `cogent-polis-discord-replies`
- IAM permissions to access cogent registry

### Discord App Setup

One app with bot permissions:
- Send Messages, Read Message History, Message Content Intent
- Manage Roles (create/delete cogent roles)
- Manage Webhooks (create per-channel webhooks)
- Add Reactions

### Cogent Config

Each cogent optionally specifies:
- Display name
- Avatar URL
- Color (for role)
- Default channels (channels where this cogent responds without @mention)

## Migration

Big bang cutover:
1. Create new shared Discord app, invite to servers
2. Deploy shared bridge to polis
3. Update all cogent capabilities to use polis queue and scoped channels
4. Tear down all per-cogent bridge services and old bot tokens

## Constraints

- Discord allows up to 15 webhooks per channel. If exceeded, bridge logs warning and falls back to sending as the bot user.
- Webhook messages don't have "real" bot user identity, but role mentions provide @-autocomplete.
- One gateway connection = one point of failure. Standard Fargate health checks + restart handle this.
