---
name: check-discord
program_name: hello
description: Monitor Discord channels and respond to new messages
tools:
  - memory get
  - event send
memory_keys:
  - identity
  - discord-channels
priority: 10.0
runner: lambda
resources:
  - discord-api
---
Check the configured Discord channels for any new messages since the last
check. For each new message, create an event so the appropriate program
can handle it.
