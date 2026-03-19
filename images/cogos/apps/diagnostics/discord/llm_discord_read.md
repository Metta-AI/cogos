# Discord Read-Only Diagnostic

You have access to the `discord` capability. Perform the following read-only checks:

1. Call `discord.list_guilds()` and report the result.
2. If guilds are returned, pick the first guild and call `discord.list_channels(guild_id)`.
3. Do NOT send any messages or modify anything.

Report what you found. If any call fails, describe the error.

```python verify
import time

checks = []

t0 = time.time()
try:
    result = discord.list_guilds()
    ms = int((time.time() - t0) * 1000)
    if result is None:
        checks.append({"name": "llm_discord_read_verify", "status": "fail", "ms": ms, "error": "list_guilds returned None"})
    else:
        checks.append({"name": "llm_discord_read_verify", "status": "pass", "ms": ms})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "llm_discord_read_verify", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
```
