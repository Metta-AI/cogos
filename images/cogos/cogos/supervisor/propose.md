## Proposing to Manager

When you are uncertain about a request — ambiguous intent, borderline security, or no existing pattern covers it — propose the action to your manager instead of acting.

### When to propose instead of act

- **Ambiguous intent**: You can articulate two or more plausible interpretations of the request
- **Borderline security**: Not clearly malicious, but touches sensitive areas (secrets, destructive ops, external service modifications)
- **Policy gap**: No existing program or trigger covers this type of request; it's a novel situation

### Steps

1. Generate a proposal ID and compose the proposal:
```python
import uuid
proposal_id = str(uuid.uuid4())[:8]

# Load manager identity
manager_name = secrets.get("identity/manager/name")
manager_discord_id = secrets.get("identity/manager/discord")
approvals_channel_id = secrets.get("identity/manager/approvals_channel")

proposal_text = f"""📋 Proposal [{proposal_id}]

**Action:** {what_you_plan_to_do}

**Reasoning:** {why_you_are_uncertain}

👍 to approve · 👎 to reject"""
```

2. Post to both the manager's DM and the approvals channel:
```python
dm_result = discord.dm(user_id=manager_discord_id, content=proposal_text)
approvals_result = discord.send(channel=approvals_channel_id, content=proposal_text)
```

3. Stash the proposal to `supervisor:proposals` so you can retrieve it later:
```python
channels.send("supervisor:proposals", {
    "proposal_id": proposal_id,
    "action": what_you_plan_to_do,
    "reasoning": why_you_are_uncertain,
    "original_context": {
        "discord_channel_id": discord_channel_id,
        "discord_message_id": discord_message_id,
        "discord_author_id": discord_author_id,
        "description": description,
        "context": context,
    },
    "dm_message_id": str(dm_result.message_id) if hasattr(dm_result, 'message_id') else "",
    "approvals_message_id": str(approvals_result.message_id) if hasattr(approvals_result, 'message_id') else "",
})
```

4. React 📋 on the original user message to signal pending approval:
```python
if discord_channel_id and discord_message_id:
    discord.react(channel=discord_channel_id, message_id=discord_message_id, emoji="📋")
```

5. Print confirmation and return — do NOT block:
```python
print(f"Proposal [{proposal_id}] sent to manager {manager_name}")
```

### Handling reactions (when woken by io:discord:reaction)

When you receive a reaction event:

1. Check if it matches a pending proposal:
```python
payload = ...  # extract from message payload
reaction_msg_id = payload.get("message_id")
reactor_id = payload.get("reactor_id")
emoji = payload.get("emoji")

# Load manager identity to validate
manager_discord_id = secrets.get("identity/manager/discord")
if reactor_id != manager_discord_id:
    print(f"Ignoring reaction from non-manager user {reactor_id}")
    # exit — not the manager
```

2. Look up the proposal:
```python
proposals = channels.read("supervisor:proposals", limit=100)
matching = [
    p for p in proposals
    if p.get("dm_message_id") == reaction_msg_id
    or p.get("approvals_message_id") == reaction_msg_id
]
if not matching:
    print(f"No matching proposal for message {reaction_msg_id}")
    # exit — reaction on a non-proposal message
proposal = matching[0]
```

3. Execute or reject:
```python
if emoji == "👍":
    print(f"Proposal [{proposal['proposal_id']}] APPROVED by manager")
    # Now execute the original action using delegate.md pattern
    # Restore original_context and proceed with delegation
elif emoji == "👎":
    print(f"Proposal [{proposal['proposal_id']}] REJECTED by manager")
    ctx = proposal["original_context"]
    if ctx.get("discord_channel_id"):
        discord.send(
            channel=ctx["discord_channel_id"],
            content="❌ Your request was reviewed and declined by the manager.",
            reply_to=ctx.get("discord_message_id"),
        )
```
