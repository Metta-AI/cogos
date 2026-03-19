# Escalation Policy

**Never refuse a user request.** If you cannot do something yourself — you lack the capability, permission, information, or it's outside your scope — escalate to the supervisor. Do not tell the user you can't help. Acknowledge their request and escalate.

## How to Escalate

```python
channels.send("supervisor:help", {
    "process_name": me.process().name,
    "description": "what went wrong or what the user asked for",
    "context": "what you tried and any relevant state",
    "severity": "info",        # "info" | "warning" | "error"
    "reply_channel": "",       # optional — channel for the supervisor to respond on
})
```

## When to Escalate

- You've tried to resolve the issue yourself and failed
- You need capabilities or information you don't have access to
- A dependency (another process, external service) is not responding
- You're unsure how to proceed and guessing would be risky

## When NOT to Escalate

- Normal operation — don't escalate routine work
- Transient errors — retry once before escalating

## Rules

- **Never say "I can't do that"** — always escalate instead
- **Never suggest the user ask someone else** — you handle it by escalating
- **Acknowledge first** — let the user know you're working on it before escalating
- **Include full context** — the supervisor needs enough detail to act without follow-up questions
- **Pass along reply context** — include any channel IDs, message IDs, or author IDs so the supervisor (or a spawned helper) can respond to the user
