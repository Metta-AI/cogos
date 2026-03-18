import time

checks = []

# Check 1: list guilds
t0 = time.time()
try:
    guilds = discord.list_guilds()
    ms = int((time.time() - t0) * 1000)
    if guilds is None:
        checks.append({"name": "list_guilds", "status": "fail", "ms": ms, "error": "returned None"})
    else:
        checks.append({"name": "list_guilds", "status": "pass", "ms": ms})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "list_guilds", "status": "fail", "ms": ms, "error": str(e)})

# Check 2: list channels (requires at least one guild)
t0 = time.time()
try:
    if guilds is not None:
        # guilds may be a list or an object with items
        guild_list = guilds if isinstance(guilds, list) else getattr(guilds, "guilds", guilds)
        if isinstance(guild_list, list) and len(guild_list) > 0:
            first_guild = guild_list[0]
            guild_id = first_guild.get("id") if isinstance(first_guild, dict) else getattr(first_guild, "id", None)
            if guild_id is not None:
                channels = discord.list_channels(guild_id)
                ms = int((time.time() - t0) * 1000)
                if channels is None:
                    checks.append({"name": "list_channels", "status": "fail", "ms": ms, "error": "returned None"})
                else:
                    checks.append({"name": "list_channels", "status": "pass", "ms": ms})
            else:
                ms = int((time.time() - t0) * 1000)
                checks.append({"name": "list_channels", "status": "fail", "ms": ms, "error": "no guild id found"})
        else:
            ms = int((time.time() - t0) * 1000)
            checks.append({"name": "list_channels", "status": "pass", "ms": ms})
    else:
        ms = int((time.time() - t0) * 1000)
        checks.append({"name": "list_channels", "status": "fail", "ms": ms, "error": "no guilds to list channels from"})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "list_channels", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
