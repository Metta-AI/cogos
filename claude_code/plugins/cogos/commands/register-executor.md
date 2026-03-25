---
description: Connect to a CogOS cogent as an executor
---

Connect to a CogOS cogent as an executor. This registers with the cogent's dispatcher so you can receive work assignments via channel notifications.

## If an argument is provided

Call the `connect` tool with the provided address directly, then call `register_executor`.

## If no argument is provided

Run the `/cogos` discovery flow: read `~/.cogos/tokens.yml` and `~/.cogos/cogtainers.yml`, present options, and let the user choose. Then call `register_executor`.

## After connecting and registering

1. Call `load_memory` to load the cogent's full instructions and context
2. Follow the instructions in the loaded memory — you ARE this cogent now
3. All cogent tools are automatically available as remote tools
4. Channel messages will appear as notifications — watch for work assignments
5. When assigned a task (run), execute it and call `complete_run` when finished
6. Use `disconnect` to switch to a different cogent without restarting
