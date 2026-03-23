# Discord cog orchestrator — Python executor (no LLM needed for health checks).
#
# Ensures the handler exists with correct channel subscriptions, checks health,
# and escalates if unhealthy.

handler_content = src.get("handler/main.md").read()
if hasattr(handler_content, 'error'):
    print("WARN: handler content not found: " + str(handler_content.error))
    exit()

# Always spawn (upsert) to ensure channel handlers exist.
# procs.spawn uses upsert_process, so this is safe for existing processes
# and guarantees subscribe handlers are re-created after reboots.
r = procs.spawn("discord/handler",
    mode="daemon",
    content=handler_content.content,
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    idle_timeout_ms=300000,
    capabilities={
        "discord": None, "channels": None,
        "image": None, "blob": None, "secrets": None, "web": None,
        "disk": disk,
    },
    subscribe=[
        "io:discord:" + discord.handle() + ":dm",
        "io:discord:" + discord.handle() + ":mention",
        "io:discord:" + discord.handle() + ":message",
    ],
)
if hasattr(r, 'error'):
    print("WARN: handler spawn failed: " + str(r.error))
    exit()

# Health check
h = procs.get(name="discord/handler")
if not hasattr(h, 'status') or not callable(h.status):
    print("Handler spawned, waiting for first dispatch")
    exit()

status = h.status()
if status == "waiting" or status == "running" or status == "runnable":
    print("Handler is " + status + ". OK.")
    exit()

# Handler is unhealthy — escalate to supervisor for LLM-powered diagnosis
channels.send("supervisor:help", {
    "type": "discord:handler_unhealthy",
    "handler_status": status,
    "message": "Discord handler is " + status + " — needs diagnosis and possible restart",
})
print("Handler is " + status + " — escalated to supervisor")
