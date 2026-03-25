---
description: List available CogOS cogtainers and cogents
---

List available CogOS cogtainers and cogents, then help the user connect.

## Discovery

1. Read `~/.cogos/tokens.yml` for previously connected cogents (these have cached auth tokens)
2. Read `~/.cogos/cogtainers.yml` for configured cogtainers and their cogents
3. Present all discovered options to the user

## Format

Show options like:

**Previously connected:**
- `alpha.softmax-cogents.com` — cogent "alpha" (cached token)
- `beta.softmax-cogents.com` — cogent "beta" (cached token)

**Configured cogtainers:**
- cogtainer "prod" (AWS) — cogents: alpha, beta, gamma
- cogtainer "local" — cogents: dev

**Or enter a custom address** (e.g. `myagent.softmax-cogents.com`)

## After selection

Once the user picks a cogent, call the `connect` tool with the chosen address.
Then call `load_memory` to load the cogent's instructions.
