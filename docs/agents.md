# Agent Operations Guide

## Asana Integration

### Project

Tasks live in the **Cogents** Asana project:
- **Project URL**: https://app.asana.com/0/1213428766379931
- **Project GID**: `1213428766379931`
- **Workspace GID**: `1209016784099267`

### Authentication

The Claude Code MCP Asana integration handles auth automatically via the `claude_ai_Asana` MCP server (configured in Claude's connected accounts / secrets). No local API keys or AWS secrets needed — this is separate from the cogent runtime's `asana_cap.py` which uses AWS Secrets Manager.

### Working on tasks

Run `/asana.do-task` to have Claude Code:
1. Fetch incomplete tasks from the Cogents project
2. Pick the best one to work on
3. Comment on the Asana task that work is starting
4. Implement the changes in this repo
5. Comment results back on the task
6. Mark the task complete if done
7. Commit and push

### Manual Asana operations

The MCP tools are available directly:
```
asana_get_tasks          — list tasks in a project
asana_get_task           — get full task details
asana_search_tasks       — search by text, assignee, status, etc.
asana_create_task        — create a new task
asana_update_task        — update task fields or mark complete
asana_create_task_story  — add a comment to a task
asana_get_project_sections — list project sections
```

All tools are prefixed with `mcp__claude_ai_Asana__` and loaded via ToolSearch.

## Which cogent to use

Each developer has their own test cogent. All examples below use `$COGENT`. Set it once:

```bash
export COGENT=my-cogent  # replace with your cogent instance name
```

## Testing a Cogent End-to-End

### DM a cogent via CLI (no Discord needed)

Inject a DM into the cogent's Discord handler:

```bash
# Send a test DM
cogos channel send io:discord:dm --payload '{
  "content": "hello, what can you do?",
  "author": "testuser",
  "author_id": "000000000000000000",
  "channel_id": "000000000000000000",
  "message_id": "1484000000000000000",
  "is_dm": true,
  "is_mention": false,
  "timestamp": "2026-03-18T12:00:00Z"
}'
```

Note: `message_id` must be a unique Discord snowflake (monotonically increasing 18-digit number). Increment it for each test message.

### Check the response

```bash
# Check handler stdout for processing output
cogos process get discord/handler

# Check the conversation log
cogos file get data/discord/000000000000000000/recent.log
```

### Verify the handler is alive

```bash
# Handler should be "waiting" (daemon waiting for messages)
cogos status | grep discord

# If handler is missing or disabled, kick discord cog to re-spawn it:
cogos channel send discord-cog:review --payload '{"reason": "respawn handler"}'
```

### Fix stale epochs after reboot

After reboot, child processes may have stale epochs. Fix with:

```bash
PYTHONPATH=src python -c "
import os; cogent = os.environ['COGENT']; os.environ['COGENT_NAME'] = cogent
from cogos.cli.__main__ import _ensure_db_env; _ensure_db_env(cogent)
import boto3; from cogos.db.repository import Repository
repo = Repository(client=boto3.client('rds-data', region_name='us-east-1'), resource_arn=os.environ['DB_CLUSTER_ARN'], secret_arn=os.environ['DB_SECRET_ARN'], database=os.environ.get('DB_NAME', 'cogos'))
epoch = repo.reboot_epoch
repo._execute('UPDATE cogos_handler SET epoch = :e WHERE epoch < :e', [repo._param('e', epoch)])
repo._execute('UPDATE cogos_process SET epoch = :e WHERE epoch < :e', [repo._param('e', epoch)])
repo._execute('UPDATE cogos_process_capability SET epoch = :e WHERE epoch < :e', [repo._param('e', epoch)])
print('All updated to epoch', epoch)
"
```

### Full deploy + test cycle

```bash
# 1. Push code
git push

# 2. Deploy Lambda (executor + event-router + dispatcher)
cogtainer update $COGENT --lambdas

# 3. Load image files into DB
cogos image boot

# 4. Reboot (creates fresh init, spawns all cogs)
cogos reboot -y

# 5. Wait ~90s for init + cogs to run

# 6. Fix epochs (until epoch inheritance is fixed in deploy pipeline)
# (see script above)

# 7. Kick discord to spawn handler
cogos channel send discord-cog:review --payload '{"reason": "test"}'

# 8. Send test DM
cogos channel send io:discord:dm --payload '{"content": "hello!", "author": "test", "author_id": "0", "channel_id": "0", "message_id": "1484200000000000000", "is_dm": true, "is_mention": false}'
```
