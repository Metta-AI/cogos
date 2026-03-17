# Discord cog orchestrator — Python executor (no LLM needed for health checks).
#
# The handler is created at boot by cog.py. This script just checks
# health and escalates if something is wrong.

h = procs.get(name="discord/handler")
has_handler = hasattr(h, 'status') and callable(h.status)

if not has_handler:
    print("Handler not found — it should have been created at boot. Skipping.")
    exit()

# Health check
status = h.status()
if status == "waiting" or status == "running":
    print(f"Handler is {status}. No action needed.")
    exit()

# Handler is unhealthy — escalate to supervisor for LLM-powered diagnosis
channels.send("supervisor:help", {
    "type": "discord:handler_unhealthy",
    "handler_status": status,
    "message": f"Discord handler is {status} — needs diagnosis and possible restart",
})
print(f"Handler is {status} — escalated to supervisor")
