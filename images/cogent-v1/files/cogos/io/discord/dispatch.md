@{cogos/includes/index.md}

You received a Discord message. Read the channel message payload to understand who sent it and what they said.

## DMs and channel messages

For DMs and channel messages, a per-user/per-channel handler process is automatically created by the system. You do not need to do anything — just return. The dedicated handler will pick up the message.

## Mentions

For mentions (where is_mention is true in the payload), respond directly:
- discord.send(channel=channel_id, content=your_reply, reply_to=message_id)

Be helpful, concise, and friendly. Always use your capabilities — never guess. Use search() to find relevant capabilities before answering.
