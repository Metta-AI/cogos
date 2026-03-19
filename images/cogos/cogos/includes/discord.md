# Discord API

Send and receive Discord messages, reactions, threads, and DMs.

## send(channel, content, thread_id?, reply_to?, files?)

```python
discord.send("123456789", "Hello from CogOS!")

# Reply to a message
discord.send("123456789", "Thanks!", reply_to="987654321")

# Send in a thread
discord.send("123456789", "Thread reply", thread_id="111222333")
```

## react(channel, message_id, emoji)

```python
discord.react("123456789", "987654321", "thumbsup")
```

## create_thread(channel, thread_name, content?, message_id?)

```python
# New thread
discord.create_thread("123456789", "Bug Discussion", content="Let's track this here")

# Thread from existing message
discord.create_thread("123456789", "Follow-up", message_id="987654321")
```

## dm(user_id, content)

```python
discord.dm("user-id-here", "Private message from your cogent")
```

## receive(limit?, channel_name?)

```python
# All recent discord messages
messages = discord.receive(limit=10)
for m in messages:
    print(f"{m.author}: {m.content}")

# Only DMs (reads from io:discord:dm channel)
dms = discord.receive(channel_name="io:discord:dm")

# Only mentions (reads from io:discord:mention channel)
mentions = discord.receive(channel_name="io:discord:mention")
```

Returns `list[DiscordMessage]` — content, author, author_id, channel_id, message_id, is_dm, is_mention, thread_id.

## history(channel_id, limit?, before?, after?)

```python
# Fetch recent channel history from the Discord API
messages = discord.history("123456789", limit=50)
for m in messages:
    print(f"{m['author']}: {m['content']}")

# Paginate with before/after message IDs
older = discord.history("123456789", limit=50, before="last_message_id")
```

Returns `list[dict]` — content, author, author_id, channel_id, message_id, timestamp, is_dm, is_mention, attachments, thread_id.
Results ordered oldest-first. Fetches from the Discord API via the bridge (may take a few seconds).

## Scoping

```python
# Restrict to specific channels
support = discord.scope(channels=["123456789", "987654321"])

# Restrict operations
read_only = discord.scope(ops=["receive"])

# Both
scoped = discord.scope(channels=["123456789"], ops=["send", "receive"])
```

## list_guilds()

```python
guilds = discord.list_guilds()
for g in guilds:
    print(f"{g.name} ({g.guild_id}) — {g.member_count} members")
```

Returns `list[DiscordGuildInfo]` — guild_id, name, icon_url, member_count.

## list_channels(guild_id?)

```python
# All channels across all guilds
channels = discord.list_channels()

# Channels in a specific guild
channels = discord.list_channels(guild_id="123456")

for ch in channels:
    print(f"#{ch.name} ({ch.channel_id}) — {ch.channel_type}, topic: {ch.topic}")
```

Returns `list[DiscordChannelInfo]` — channel_id, guild_id, name, topic, category, channel_type, position.
