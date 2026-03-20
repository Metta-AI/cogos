---
name: boot-local
description: Use when the user wants to start the local CogOS environment - boots the local executor and dashboard from a clean state.
---

# Boot Local

Start the local CogOS executor and dashboard. Follows the README.md Local Quick Start.

## Steps

1. Install dependencies:
   ```bash
   uv sync --all-extras
   cd dashboard/frontend && npm ci && cd ../..
   ```

2. Load the default image (wipes and reloads):
   ```bash
   uv run cogent local cogos reload -i cogent-v1 -y
   ```

3. Start the local executor in the background (use `run_in_background`):
   ```bash
   uv run cogent local cogos run-local
   ```

4. Start the dashboard:
   ```bash
   uv run cogent local cogos dashboard start
   ```

5. Report the frontend URL printed by the dashboard start command (usually `http://localhost:29489`).
