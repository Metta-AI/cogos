# Claude Code Channel Integration

Bridge CogOS channels into a running Claude Code session using the
[Channels](https://code.claude.com/docs/en/channels) feature.

## How it works

A local MCP server polls the CogOS dashboard API for new messages on
subscribed channels and forwards them as `<channel>` events inside your
Claude Code session. Claude can reply back to CogOS channels using the
`reply` or `send` tools exposed by the server.

## Prerequisites

- Claude Code v2.1.80+ with channels support
- [Bun](https://bun.sh) runtime installed
- A running CogOS dashboard (local or deployed)

## Setup

1. Install dependencies:

       cd channels/claude-code && bun install

2. Set environment variables:

       export COGOS_API_URL=http://localhost:8100
       export COGOS_COGENT_NAME=<your-cogent>
       export COGOS_API_KEY=<optional-api-key>
       export COGOS_CHANNELS="io:claude-code:*"

3. Start Claude Code with the channel:

       claude --dangerously-load-development-channels server:cogos-channels

   Or, once published, use:

       claude --channels plugin:cogos-channels@cogos

## Channel patterns

By default the server subscribes to `io:claude-code:*` channels. Set
`COGOS_CHANNELS` to a comma-separated list of glob patterns to subscribe
to additional channels:

    COGOS_CHANNELS="io:claude-code:*,system:alerts,io:discord:*"

## Tools exposed

| Tool             | Description                                      |
|------------------|--------------------------------------------------|
| `reply`          | Send a message back to the originating channel   |
| `send`           | Write to any CogOS channel by name               |
| `list_channels`  | List available channels and message counts        |
