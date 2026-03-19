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
print(f"Created coglet, required capabilities: {required_caps}")
```

3. Grant capabilities. Map each required capability to the actual object from your sandbox:
```python
# Map capability names to objects available in your sandbox.
# Use `root` for dir access — it has full scope and can be delegated to workers.
_cap_map = {
    "discord": discord, "channels": channels, "dir": root, "data": root,
    "alerts": alerts, "blob": blob, "image": image, "file": file,
    "web_search": web_search, "web_fetch": web_fetch, "web": web,
    "asana": asana, "email": email, "github": github, "stdlib": stdlib,
    "secrets": secrets,
}
caps = {}
for cap_name in required_caps:
    if cap_name in _cap_map:
        caps[cap_name] = _cap_map[cap_name]
    else:
        print(f"WARN: unknown capability requested: {cap_name}")
# Always include channels for escalation
caps["channels"] = channels
print(f"Granting capabilities: {list(caps.keys())}")
```

4. Run the coglet:
```python
result = coglet_runtime.run(coglet, procs, capabilities=caps)
if hasattr(result, 'error'):
    print(f"ERROR: {result.error}")
    if discord_channel_id:
        # Use a user-friendly message — never expose raw internal errors
        discord.send(channel=discord_channel_id, content=f"🧠 Sorry, I'm not able to do that from here — I don't have the right access for this request.", reply_to=discord_message_id, react="🧠")
    alerts.error("supervisor", f"Failed to spawn worker: {result.error}")
else:
    print(f"Spawned worker: {result.name}")
```

### When to respond directly instead

If you can answer the request immediately with information you already have (e.g., "what time is it?", "what's the system status?"), just respond on Discord directly. Don't spawn a worker for trivial requests.
