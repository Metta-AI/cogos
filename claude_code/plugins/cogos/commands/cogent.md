---
description: Connect to a CogOS cogent in chat mode
---

Connect to a CogOS cogent process. All cogent tools are automatically available via the remote MCP proxy.

Syntax: `/cogos:cogent [process@]address`
- `alpha.softmax-cogents.com` — connects to the **supervisor** process (default)
- `discord@alpha.softmax-cogents.com` — connects to the **discord** process
- `alpha` — connects to supervisor on localhost

## If an argument is provided

Call the `connect` tool with the provided address directly.

## If no argument is provided

Run the `/cogos` discovery flow: read `~/.cogos/tokens.yml` and `~/.cogos/cogtainers.yml`, present options, and let the user choose.

## After connecting

1. Call `load_memory` to load the process's full prompt and instructions
2. Follow the instructions in the loaded memory — you ARE this cogent process now
3. All cogent tools (capabilities, files, etc.) are automatically available as remote tools
4. Use `list_channels`, `send`, and `reply` for channel communication
5. Use `disconnect` to switch to a different cogent without restarting
