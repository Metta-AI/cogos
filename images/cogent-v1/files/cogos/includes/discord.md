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

## receive(limit?, event_type?)

```python
# All recent discord messages
messages = discord.receive(limit=10)
for m in messages:
    print(f"{m.author}: {m.content}")

# Only DMs
dms = discord.receive(event_type="discord:dm")

# Only mentions
mentions = discord.receive(event_type="discord:mention")
```

Returns `list[DiscordMessage]` — content, author, author_id, channel_id, message_id, is_dm, is_mention, thread_id.

## Scoping

```python
# Restrict to specific channels
support = discord.scope(channels=["123456789", "987654321"])

# Restrict operations
read_only = discord.scope(ops=["receive"])

# Both
scoped = discord.scope(channels=["123456789"], ops=["send", "receive"])
```
