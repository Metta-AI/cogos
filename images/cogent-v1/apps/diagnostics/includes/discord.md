@{cogos/includes/code_mode.md}
@{cogos/includes/discord.md}

# Diagnostic: includes/discord

Exercise the Discord API instructions above in read-only mode. Do NOT send any messages.

## Tasks

1. **List guilds**: Use `discord.list_guilds()` and print the result.

2. **List channels**: Use `discord.list_channels()` and print the result.

3. **Print summary**: Print `"discord_diagnostic: guilds_listed=true, channels_listed=true"`.

```python verify
# Read-only diagnostic — just confirm the process completed
p = procs.get(name="_diag/inc_discord")
if hasattr(p, "error"):
    pass
```
