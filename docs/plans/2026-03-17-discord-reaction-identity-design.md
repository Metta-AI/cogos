# Discord Reaction Identity Design

## Overview

When a cog responds to a user via Discord, add a reaction to the bot's reply message to identify which cog produced the response. Serves both debugging/observability and user-facing transparency.

## Design

### 1. CogConfig emoji field

Add an `emoji` field to `CogConfig`. Each cog declares its own Unicode emoji:

```python
emoji: str = ""  # Unicode emoji identifying this cog's Discord responses
```

Examples:
- `cogos/supervisor` → `emoji = "🧠"`
- `cogos/worker` → `emoji = "🔧"`
- `apps/discord/handler` → `emoji = "💬"`

Cogs without an emoji get no reaction.

### 2. `discord.send()` react parameter

Add an optional `react` param to `discord.send()`:

```python
discord.send(
    channel=channel_id,
    content=reply,
    reply_to=message_id,
    react="🔧"
)
```

The caller passes its emoji explicitly. The SQS message payload gets a new `react` field.

### 3. Worker wiring

The worker cog reads its own `emoji` from its cog config and passes it to `discord.send(react=...)`. No magic wrapping — the worker explicitly includes the react parameter. For LLM-based cogs, the prompt instructs them to include it.

### 4. Bridge reaction handling

In the bridge's reply processing loop, after successfully sending a message to Discord:

1. Get the `message_id` from the Discord API send response
2. If `react` is present in the SQS payload, call `message.add_reaction(react)`
3. On failure, log a warning and move on — don't fail message delivery

## Touch points

1. **`CogConfig`** — add `emoji: str` field
2. **`discord.send()` capability** — add optional `react` param, include in SQS payload
3. **Worker cog** — pass its emoji when calling `discord.send()`
4. **Bridge** — add reaction after sending message

## Non-goals

- Custom server emoji (use Unicode only)
- Reaction chains showing escalation path (just the final responder)
- Reacting to the user's incoming message
