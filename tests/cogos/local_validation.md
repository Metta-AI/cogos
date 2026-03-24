# Local Cogent Validation Tests

Manual test checklist to validate CogOS runs correctly on a local cogent.

## Prerequisites

```bash
cogent select <name>
```

This writes COGTAINER and COGENT to `.env` so all `cogos` commands target the local cogent.

## Setup

```bash
cogos start cogos --clean
```

- [ ] Prints boot summary with capabilities, resources, files, processes
- [ ] No errors or warnings

```bash
cogos status
```

- [ ] Shows all 4 processes (discord-handle-message, recruiter, recruiter/present, scheduler)
- [ ] All processes in `waiting` state
- [ ] Shows file and capability counts

## Capabilities

```bash
cogos capability list
```

- [ ] Lists all capabilities (channels, dir, discord, email, file, github, me, procs, resources, scheduler, schemas, secrets, web_fetch, web_search, asana)
- [ ] All show `enabled: True`

```bash
cogos capability get discord
```

- [ ] Shows full capability details including handler path and schema

## Files

```bash
cogos file list --prefix cogos/
```

- [ ] Lists files under cogos/ prefix (docs, includes, lib)

```bash
cogos file get cogos/docs/capabilities.md
```

- [ ] Prints file content

```bash
cogos file create test/hello.md "hello world"
cogos file get test/hello.md
```

- [ ] File created and readable

## Handlers

```bash
cogos handler list
```

- [ ] discord-handle-message subscribed to `io:discord:dm` and `io:discord:mention`
- [ ] recruiter subscribed to `system:tick:hour` and `recruiter:feedback`
- [ ] recruiter/present subscribed to `system:tick:hour`


## Channel Delivery (Discord DM)

```bash
cogos channel send io:discord:dm --payload '{"content": "hello", "author": "tester", "author_id": "1", "channel_id": "2", "message_type": "discord:dm", "is_dm": true, "is_mention": false, "attachments": [], "embeds": []}'
```

- [ ] Message sent confirmation with ID

```bash
cogos status
```

- [ ] discord-handle-message is now `runnable`

```bash
cogos process run discord-handle-message --local
```

- [ ] Executor runs (no crash)

```bash
cogos run list --limit 1
```

- [ ] Latest run shows `status: completed`
- [ ] Has non-zero `tokens_in` and `tokens_out`

```bash
cogos status
```

- [ ] discord-handle-message back to `waiting`

## Channel Delivery (Discord Mention)

```bash
cogos channel send io:discord:mention --payload '{"content": "@bot hi", "author": "tester", "author_id": "1", "channel_id": "3", "guild_id": "4", "message_id": "5", "message_type": "discord:mention", "is_dm": false, "is_mention": true, "attachments": [], "embeds": []}'
cogos process run discord-handle-message --local
cogos run list --limit 1
```

- [ ] Run completed successfully
- [ ] discord-handle-message back to `waiting`

## Direct Process Run

```bash
cogos process run discord-handle-message --local
```

- [ ] Runs and completes (no event payload, just executes the process prompt)
- [ ] Prints token counts and duration

## Process Lifecycle

```bash
cogos process disable discord-handle-message
cogos status
```

- [ ] discord-handle-message shows `disabled`

```bash
cogos channel send io:discord:dm --payload '{"content": "should not trigger", "author": "tester", "author_id": "1", "channel_id": "2", "message_type": "discord:dm", "is_dm": true, "is_mention": false, "attachments": [], "embeds": []}'
cogos process run discord-handle-message --local
cogos run list --limit 1
```

- [ ] No new run created (disabled process should not be dispatched)

## Channels

```bash
cogos channel send test:channel --payload '{"msg": "test message"}'
cogos channel send test:channel --payload '{"msg": "second message"}'
```

- [ ] Both messages sent successfully

## Run History

```bash
cogos run list
```

- [ ] Shows all runs with process IDs, status, token counts, durations

```bash
cogos run show <run-id>
```

- [ ] Shows full run details including model_version and error (if any)

## Wipe and Reload

```bash
cogos wipe -y
cogos status
```

- [ ] All counts are 0

```bash
cogos reload -i cogos -y
cogos status
```

- [ ] All processes, capabilities, files restored

## Discord IO Bridge

```bash
cogos io discord --help
```

- [ ] Shows subcommands: start, stop, restart, status, run-local
