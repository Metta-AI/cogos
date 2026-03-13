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
You received a Discord message. Read the channel message payload to understand who sent it and what they said.

Use the discord capability to respond:
- For DMs: use discord.dm(user_id=author_id, content=your_reply)
- For mentions: use discord.send(channel=channel_id, content=your_reply, reply_to=message_id)

Be helpful, concise, and friendly. Always use your capabilities to answer — never guess or make up information. Before responding, use search() to find relevant tools for the question (e.g. search("time") for time questions).
""",
    runner="lambda",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    priority=10.0,
    capabilities=["discord", "channels", "dir", "stdlib"],
    handlers=["io:discord:dm", "io:discord:mention"],
)
