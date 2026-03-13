# Local Cogent Validation Tests

Manual test checklist to validate CogOS runs correctly with `cogent local`.

## Setup

```bash
cogent local cogos image boot cogent-v1 --clean
```

- [ ] Prints boot summary with capabilities, resources, files, processes
- [ ] No errors or warnings

```bash
cogent local cogos status
```

- [ ] Shows all 4 processes (discord-handle-message, recruiter, recruiter/present, scheduler)
- [ ] All processes in `waiting` state
- [ ] Shows file and capability counts

## Capabilities

```bash
cogent local cogos capability list
```

- [ ] Lists all capabilities (channels, dir, discord, email, file, github, me, procs, resources, scheduler, schemas, secrets, stdlib, web_fetch, web_search, asana)
- [ ] All show `enabled: True`

```bash
cogent local cogos capability get discord
```

- [ ] Shows full capability details including handler path and schema

## Files

```bash
cogent local cogos file list --prefix cogos/
```

- [ ] Lists files under cogos/ prefix (docs, includes, lib)

```bash
cogent local cogos file get cogos/docs/capabilities.md
```

- [ ] Prints file content

```bash
cogent local cogos file create test/hello.md "hello world"
cogent local cogos file get test/hello.md
```

- [ ] File created and readable

## Handlers

```bash
cogent local cogos handler list
```

- [ ] discord-handle-message subscribed to `io:discord:dm` and `io:discord:mention`
- [ ] recruiter subscribed to `system:tick:hour` and `recruiter:feedback`
- [ ] recruiter/present subscribed to `system:tick:hour`

## Event Delivery (Discord DM)

```bash
cogent local cogos event emit io:discord:dm --payload '{"content": "hello", "author": "tester", "author_id": "1", "channel_id": "2", "event_type": "discord:dm", "is_dm": true, "is_mention": false, "attachments": [], "embeds": []}'
```

- [ ] Message sent confirmation with ID

```bash
cogent local cogos status
```

- [ ] discord-handle-message is now `runnable`

```bash
cogent local cogos run-local --once
```

- [ ] Executor runs (no crash)

```bash
cogent local cogos run list --limit 1
```

- [ ] Latest run shows `status: completed`
- [ ] Has non-zero `tokens_in` and `tokens_out`

```bash
cogent local cogos status
```

- [ ] discord-handle-message back to `waiting`

## Event Delivery (Discord Mention)

```bash
cogent local cogos event emit io:discord:mention --payload '{"content": "@bot hi", "author": "tester", "author_id": "1", "channel_id": "3", "guild_id": "4", "message_id": "5", "event_type": "discord:mention", "is_dm": false, "is_mention": true, "attachments": [], "embeds": []}'
cogent local cogos run-local --once
cogent local cogos run list --limit 1
```

- [ ] Run completed successfully
- [ ] discord-handle-message back to `waiting`

## Direct Process Run

```bash
cogent local cogos process run discord-handle-message --local
```

- [ ] Runs and completes (no event payload, just executes the process prompt)
- [ ] Prints token counts and duration

## Process Lifecycle

```bash
cogent local cogos process disable discord-handle-message
cogent local cogos status
```

- [ ] discord-handle-message shows `disabled`

```bash
cogent local cogos event emit io:discord:dm --payload '{"content": "should not trigger", "author": "tester", "author_id": "1", "channel_id": "2", "event_type": "discord:dm", "is_dm": true, "is_mention": false, "attachments": [], "embeds": []}'
cogent local cogos run-local --once
cogent local cogos run list --limit 1
```

- [ ] No new run created (disabled process should not be dispatched)

## Channels

```bash
cogent local cogos event emit test:channel --payload '{"msg": "test message"}'
cogent local cogos event emit test:channel --payload '{"msg": "second message"}'
```

- [ ] Both messages sent successfully

## Run History

```bash
cogent local cogos run list
```

- [ ] Shows all runs with process IDs, status, token counts, durations

```bash
cogent local cogos run show <run-id>
```

- [ ] Shows full run details including model_version and error (if any)

## Wipe and Reload

```bash
cogent local cogos wipe -y
cogent local cogos status
```

- [ ] All counts are 0

```bash
cogent local cogos reload -i cogent-v1 -y
cogent local cogos status
```

- [ ] All processes, capabilities, files restored

## Discord IO Bridge

```bash
cogent local cogos io discord --help
```

- [ ] Shows subcommands: start, stop, restart, status, run-local
