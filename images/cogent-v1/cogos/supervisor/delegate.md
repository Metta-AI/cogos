## Delegating to Workers

When a request is legitimate and you cannot answer it directly, create a worker coglet.

### Steps

1. Load the worker cog:
```python
worker_cog = cog_registry.get_or_make_cog("cogos/worker")
```

2. Create a coglet with full context:
```python
task = f"""{description}

Context: {context}

Discord reply info:
- discord_channel_id: {discord_channel_id}
- discord_message_id: {discord_message_id}
- discord_author_id: {discord_author_id}
"""
coglet, required_caps = worker_cog.make_coglet(task)
```

3. Inspect the required capabilities. Decide which to grant and scope them:
```python
# Build scoped capabilities from what the worker requested
caps = {}
for cap_name in required_caps:
    cap_obj = __capabilities__.get(cap_name)
    if cap_obj is not None:
        caps[cap_name] = cap_obj
# Always include channels for escalation
caps["channels"] = channels
```

4. Run the coglet:
```python
result = coglet_runtime.run(coglet, procs, capabilities=caps)
if hasattr(result, 'error'):
    print(f"ERROR: {result.error}")
    if discord_channel_id:
        discord.send(channel=discord_channel_id, content=f"Sorry, I couldn't start a worker: {result.error}", reply_to=discord_message_id)
    alerts.error("supervisor", f"Failed to spawn worker: {result.error}")
else:
    print(f"Spawned worker: {result.name}")
    alerts.info("supervisor", f"Delegated to worker: {description}")
```

### When to respond directly instead

If you can answer the request immediately with information you already have (e.g., "what time is it?", "what's the system status?"), just respond on Discord directly. Don't spawn a worker for trivial requests.
