checks = []

try:
    guilds = discord.list_guilds()
    if guilds is None:
        checks.append({"name": "list_guilds", "status": "fail", "ms": 0, "error": "returned None"})
    else:
        checks.append({"name": "list_guilds", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "list_guilds", "status": "fail", "ms": 0, "error": str(e)[:300]})

try:
    if guilds is not None:
        guild_list = guilds if isinstance(guilds, list) else getattr(guilds, "guilds", guilds)
        if isinstance(guild_list, list) and len(guild_list) > 0:
            first_guild = guild_list[0]
            guild_id = first_guild.get("id") if isinstance(first_guild, dict) else getattr(first_guild, "id", None)
            if guild_id is not None:
                ch = discord.list_channels(guild_id)
                if ch is None:
                    checks.append({"name": "list_channels", "status": "fail", "ms": 0, "error": "returned None"})
                else:
                    checks.append({"name": "list_channels", "status": "pass", "ms": 0})
            else:
                checks.append({"name": "list_channels", "status": "fail", "ms": 0, "error": "no guild id found"})
        else:
            checks.append({"name": "list_channels", "status": "pass", "ms": 0})
    else:
        checks.append({"name": "list_channels", "status": "fail", "ms": 0, "error": "no guilds to list channels from"})
except Exception as e:
    checks.append({"name": "list_channels", "status": "fail", "ms": 0, "error": str(e)[:300]})

print(json.dumps(checks))
