# ECS Task Runner: tmux + Interactive Shell Access

## Problem

ECS tasks run Claude Code headlessly via `subprocess.run(capture_output=True)`. There is no way to observe a running task in real-time or interact with it. Debugging requires waiting for completion and reading logs after the fact.

## Solution

Run Claude Code inside a tmux session in the ECS container. Enable ECS Exec (SSM-based) so operators can attach to the tmux session at any time via `cogent dr.alpha run shell`.

## Architecture

```
Local machine                         ECS Fargate container
+--------------------------+          +----------------------------------+
| cogent dr.alpha run shell|  SSM     | entrypoint.sh                    |
|   -> aws ecs             | -------> |   -> SSM agent (background)      |
|      execute-command     |          |   -> tmux new-session -s claude   |
|      --command           |          |       -> python -m ...ecs_entry  |
|        "tmux attach"     |          |           -> claude CLI          |
+--------------------------+          +----------------------------------+
                                                    |
                                              S3 session sync
                                            (unchanged from today)
```

## Components

### 1. Dockerfile (`src/brain/docker/Dockerfile`)

Custom image based on `python:3.12-slim`. Installs:

- **Runtime:** tmux, Node.js, Claude Code CLI (`@anthropic-ai/claude-code`)
- **Dev tools:** gh (GitHub CLI), vim, curl, wget, sudo, git
- **Python:** uv, project source (includes mind CLI)
- **AWS:** awscli, Amazon SSM agent (required for ECS Exec)

Image is pushed to the shared polis ECR repo (`cogent`), tagged as `executor-{cogent-name}` (e.g., `cogent:executor-dr-alpha`).

### 2. Entrypoint (`src/brain/docker/entrypoint.sh`)

1. Start SSM agent in background (required for ECS Exec connectivity)
2. Create tmux session: `tmux new-session -d -s claude`
3. Run `python -m brain.lambdas.executor.ecs_entry` inside the tmux session
4. Block on `tmux wait-for claude-done` until the Python process signals completion
5. Exit with the Python process's exit code

### 3. Modified `ecs_entry.py`

Two changes only:

- Remove `capture_output=True` from `subprocess.run(cmd)` so Claude Code output is visible in the tmux pane
- In the `finally` block, signal tmux: `tmux wait-for -S claude-done`

Everything else (DB writes, S3 session sync, event emission) stays identical. The S3 session sync is orthogonal to tmux — it syncs `~/.claude/` regardless of how Claude Code is launched.

### 4. CDK Changes (`src/brain/cdk/constructs/compute.py`)

- Switch container image from `python:3.12-slim` to polis ECR repo with tag `executor-{safe_name}`
- Add SSM permissions to task role: `ssmmessages:CreateControlChannel`, `ssmmessages:CreateDataChannel`, `ssmmessages:OpenControlChannel`, `ssmmessages:OpenDataChannel`
- Add `execute_command_configuration` with logging to the ECS cluster

### 5. Orchestrator Change (`src/brain/lambdas/orchestrator/handler.py`)

Add `enableExecuteCommand=True` to the `ecs_client.run_task()` call in `_dispatch_ecs()`.

### 6. CLI — `cogent dr.alpha run shell` (`src/run/cli.py`)

New `run` command group with two commands:

**`cogent dr.alpha run list`**
- Calls ECS `list_tasks` + `describe_tasks` for cluster `cogent-dr-alpha`, status `RUNNING`
- Displays: run ID, program name, start time, duration

**`cogent dr.alpha run shell [run-id]`**
- If `run-id` provided: finds that specific ECS task
- If omitted: lists active runs, prompts for selection
- Executes: `aws ecs execute-command --cluster cogent-dr-alpha --task <task-arn> --container Executor --interactive --command "tmux attach -t claude"`

**CLI registration** (`src/cli/__main__.py`):
- Import and register `run` command group
- Add `"run"` to the `_COMMANDS` set

### 7. Image Build — `cogent dr.alpha brain build`

New CLI command under the `brain` group:

1. Looks up polis ECR repo URI
2. Builds Docker image from `src/brain/docker/Dockerfile`
3. Tags as `cogent:executor-{cogent-name}`
4. Pushes to polis ECR repo

Separate from `brain create` — image rebuilds are more frequent than infra deploys.

## Local Prerequisites

To use `cogent dr.alpha run shell`, the operator needs:

- AWS CLI with valid credentials
- [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) installed
- `ecs:ExecuteCommand` permission in their IAM policy

## File Changes Summary

| File | Change |
|------|--------|
| `src/brain/docker/Dockerfile` | **New** — custom executor image |
| `src/brain/docker/entrypoint.sh` | **New** — tmux + SSM bootstrap |
| `src/run/cli.py` | **New** — `run list` and `run shell` commands |
| `src/brain/lambdas/executor/ecs_entry.py` | Remove `capture_output=True`, add tmux signal on exit |
| `src/brain/cdk/constructs/compute.py` | Polis ECR image, SSM permissions, execute command config |
| `src/brain/lambdas/orchestrator/handler.py` | Add `enableExecuteCommand=True` to `run_task()` |
| `src/cli/__main__.py` | Register `run` command group |
