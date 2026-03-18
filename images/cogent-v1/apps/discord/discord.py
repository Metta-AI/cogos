# Discord cog orchestrator — Python executor (no LLM needed for health checks).
#
# Ensures the handler exists, checks health, and escalates if unhealthy.

h = procs.get(name="discord/handler")
has_handler = hasattr(h, 'status') and callable(h.status)

if not has_handler:
    handler_content = file.read("cogs/discord/coglets/handler/main/main.md")
    if hasattr(handler_content, 'error'):
        print("WARN: handler content not found: " + str(handler_content.error))
        exit()
    r = procs.spawn("discord/handler",
        mode="daemon",
        content=handler_content.content,
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        idle_timeout_ms=300000,
        capabilities={
            "discord": None, "channels": None, "stdlib": None,
            "procs": None, "file": None,
            "image": None, "blob": None, "secrets": None, "web": None,
            "data:dir": dir.scope(prefix="data/discord/"),
        },
        subscribe=["io:discord:dm", "io:discord:mention", "io:discord:message"],
    )
    if hasattr(r, 'error'):
        print("WARN: handler spawn failed: " + str(r.error))
    else:
        print("Handler spawned")
    exit()

# Health check
status = h.status()
if status == "waiting" or status == "running":
    print("Handler is " + status + ". No action needed.")
    exit()

# Handler is unhealthy — escalate to supervisor for LLM-powered diagnosis
channels.send("supervisor:help", {
    "type": "discord:handler_unhealthy",
    "handler_status": status,
    "message": "Discord handler is " + status + " — needs diagnosis and possible restart",
})
print("Handler is " + status + " — escalated to supervisor")
