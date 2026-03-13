add_process(
    "scheduler",
    mode="daemon",
    content="@{cogos/lib/scheduler.md}",
    runner="lambda",
    priority=100.0,
    capabilities=[
        "scheduler/match_channel_messages",
        "scheduler/select_processes",
        "scheduler/dispatch_process",
        "scheduler/unblock_processes",
        "scheduler/kill_process",
    ],
    handlers=[],
)

add_process(
    "discord-handle-message",
    mode="daemon",
    content="""\
@{cogos/includes/code_mode}

You received a Discord message. Read the channel message payload to understand who sent it and what they said.

## Per-channel routing

Before responding, check if a sub-handler already exists for this source:
- For DMs: check `procs.get(name=f"discord-dm:{payload['author_id']}")`
- For channel messages: check `procs.get(name=f"discord-ch:{payload['channel_id']}")`
- For mentions: respond directly (no sub-handler needed)

If the sub-handler exists and its status is not "completed" or "disabled", do nothing — the sub-handler already received this message on its own channel. Just return.

If no sub-handler exists, spawn one:

```python
# For DMs:
child = procs.spawn(
    name=f"discord-dm:{author_id}",
    content="@{{cogos/includes/code_mode}}\\n\\n" + f"You are a Discord DM handler for user {author_id} ({author_name}). Respond using discord.dm(user_id='{author_id}', content=your_reply).\\n\\nBe helpful, concise, and friendly. Always use your capabilities — never guess. Use search() to find relevant tools before answering.",
    mode="daemon",
    idle_timeout_ms=600000,
    subscribe=f"io:discord:dm:{author_id}",
    capabilities={"discord": discord, "channels": channels, "dir": dir, "procs": procs, "stdlib": stdlib},
)

# For channel messages:
child = procs.spawn(
    name=f"discord-ch:{channel_id}",
    content="@{{cogos/includes/code_mode}}\\n\\n" + f"You are a Discord channel handler for channel {channel_id}. Respond using discord.send(channel='{channel_id}', content=your_reply, reply_to=message_id).\\n\\nOn first activation, use search() to discover your capabilities. Use discord.receive() to learn recent channel context if needed.\\n\\nBe helpful, concise, and friendly. Always use your capabilities — never guess. Use search() to find relevant tools before answering.",
    mode="daemon",
    idle_timeout_ms=600000,
    subscribe=f"io:discord:message:{channel_id}",
    capabilities={"discord": discord, "channels": channels, "dir": dir, "procs": procs, "stdlib": stdlib},
)
```

Then return — the child will pick up this message from its fine-grained channel.

## Direct response (mentions only)

For mentions, respond directly:
- discord.send(channel=channel_id, content=your_reply, reply_to=message_id)

Be helpful, concise, and friendly. Always use your capabilities to answer — never guess or make up information. Use search() to find relevant capabilities before answering.
""",
    runner="lambda",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    priority=10.0,
    capabilities=["discord", "channels", "dir", "stdlib", "procs"],
    handlers=["io:discord:dm", "io:discord:mention", "io:discord:message"],
)
