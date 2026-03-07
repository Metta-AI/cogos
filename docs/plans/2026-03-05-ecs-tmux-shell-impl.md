# ECS tmux + Interactive Shell Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run Claude Code inside tmux in ECS containers, with `cogent dr.alpha run shell` to attach interactively via ECS Exec.

**Architecture:** Container entrypoint boots SSM agent + tmux, runs ecs_entry.py inside the tmux session. ECS Exec (SSM-based) lets operators attach to the running tmux session. Images are built and pushed to the shared polis ECR repo.

**Tech Stack:** AWS CDK (ECS, ECR, IAM), Click CLI, boto3, tmux, SSM agent, Docker

**Design doc:** `docs/brain/ecs-tmux-shell-design.md`

---

### Task 1: Dockerfile

**Files:**
- Create: `src/brain/docker/Dockerfile`

**Step 1: Create the Dockerfile**

```dockerfile
FROM python:3.12-slim

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux vim curl wget sudo git unzip \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# Node.js 22 (for Claude Code CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# uv (Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# AWS CLI v2
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install && rm -rf /tmp/aws /tmp/awscliv2.zip

# SSM agent (required for ECS Exec)
RUN curl -fsSL "https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_$(dpkg --print-architecture)/amazon-ssm-agent.deb" \
    -o /tmp/ssm.deb && dpkg -i /tmp/ssm.deb && rm /tmp/ssm.deb

# Project source
COPY src/ /app/src/
COPY pyproject.toml /app/
COPY eggs/ /app/eggs/
WORKDIR /app

# Install project in the system Python (so cogent/mind CLIs are available)
RUN uv pip install --system -e .

# Entrypoint
COPY src/brain/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

**Step 2: Commit**

```bash
git add src/brain/docker/Dockerfile
git commit -m "feat(brain): add executor Dockerfile with tmux, SSM, Claude Code CLI"
```

---

### Task 2: Entrypoint Script

**Files:**
- Create: `src/brain/docker/entrypoint.sh`

**Step 1: Create the entrypoint script**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Start SSM agent in background (required for ECS Exec)
nohup amazon-ssm-agent &>/var/log/ssm-agent.log &

# Write the ecs_entry runner script (captures exit code and signals tmux)
cat > /tmp/run-ecs-entry.sh << 'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
cd /app
python -m brain.lambdas.executor.ecs_entry
EXIT_CODE=$?
# Write exit code for entrypoint to read
echo "$EXIT_CODE" > /tmp/ecs-exit-code
# Signal tmux wait-for
tmux wait-for -S claude-done
SCRIPT
chmod +x /tmp/run-ecs-entry.sh

# Start tmux session running the entry point
tmux new-session -d -s claude /tmp/run-ecs-entry.sh

# Block until the session signals completion
tmux wait-for claude-done

# Exit with the same code as the Python process
EXIT_CODE=$(cat /tmp/ecs-exit-code 2>/dev/null || echo 1)
exit "$EXIT_CODE"
```

**Step 2: Commit**

```bash
git add src/brain/docker/entrypoint.sh
git commit -m "feat(brain): add tmux entrypoint script for ECS executor"
```

---

### Task 3: Modify ecs_entry.py

**Files:**
- Modify: `src/brain/lambdas/executor/ecs_entry.py:155-161` (remove capture_output)

**Step 1: Remove `capture_output=True` and `text=True`**

Change lines 155-161 from:
```python
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.ecs_timeout_s if hasattr(config, "ecs_timeout_s") else 3600,
            cwd=WORKSPACE_DIR,
        )
```
to:
```python
        result = subprocess.run(
            cmd,
            timeout=config.ecs_timeout_s if hasattr(config, "ecs_timeout_s") else 3600,
            cwd=WORKSPACE_DIR,
        )
```

**Step 2: Update the error capture on line 170**

The `result.stderr` reference no longer works without `capture_output`. Change lines 169-170 from:
```python
            run.error = result.stderr[:4000] if result.stderr else f"Exit code {result.returncode}"
```
to:
```python
            run.error = f"Exit code {result.returncode}"
```

**Step 3: Commit**

```bash
git add src/brain/lambdas/executor/ecs_entry.py
git commit -m "feat(brain): remove capture_output so Claude Code output is visible in tmux"
```

---

### Task 4: CDK — ECS Exec support and ECR image

**Files:**
- Modify: `src/brain/cdk/constructs/compute.py`
- Modify: `src/brain/cdk/config.py`

**Step 1: Add `ecr_repo_uri` to BrainConfig**

In `src/brain/cdk/config.py`, add a field after `ecs_timeout_s`:
```python
    ecr_repo_uri: str = ""
```

**Step 2: Update ComputeConstruct**

In `src/brain/cdk/constructs/compute.py`, make these changes:

**a) Add ECR import at the top (line 8 area):**
```python
from aws_cdk import aws_ecr as ecr
```

**b) Add SSM permissions to the task role (after line 152, `sessions_bucket.grant_read_write(task_role)`):**
```python
        # SSM permissions for ECS Exec
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=["*"],
            )
        )
```

**c) Add execute command configuration to the cluster (replace lines 137-142):**

Change:
```python
        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=f"cogent-{safe_name}",
            vpc=vpc,
        )
```
to:
```python
        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=f"cogent-{safe_name}",
            vpc=vpc,
            execute_command_configuration=ecs.ExecuteCommandConfiguration(
                logging=ecs.ExecuteCommandLogging.DEFAULT,
            ),
        )
```

**d) Switch container image (replace lines 164-169):**

Change:
```python
        self.task_definition.add_container(
            "Executor",
            image=ecs.ContainerImage.from_registry("python:3.12-slim"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="executor"),
            environment=env,
        )
```
to:
```python
        # Use custom executor image from polis ECR repo
        if config.ecr_repo_uri:
            image = ecs.ContainerImage.from_registry(
                f"{config.ecr_repo_uri}:executor-{safe_name}"
            )
        else:
            image = ecs.ContainerImage.from_registry("python:3.12-slim")

        self.task_definition.add_container(
            "Executor",
            image=image,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="executor"),
            environment=env,
        )
```

**Step 3: Commit**

```bash
git add src/brain/cdk/constructs/compute.py src/brain/cdk/config.py
git commit -m "feat(brain): CDK support for ECS Exec, SSM permissions, polis ECR image"
```

---

### Task 5: Orchestrator — enableExecuteCommand

**Files:**
- Modify: `src/brain/lambdas/orchestrator/handler.py:170`

**Step 1: Add `enableExecuteCommand=True` to `run_task()`**

In `_dispatch_ecs()`, add the parameter to the `ecs_client.run_task()` call. Change lines 170-189 to:

```python
    ecs_client.run_task(
        cluster=config.ecs_cluster_arn,
        taskDefinition=config.ecs_task_definition,
        launchType="FARGATE",
        enableExecuteCommand=True,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                "securityGroups": [config.ecs_security_group],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": "Executor",
                    "environment": env_vars,
                }
            ]
        },
    )
```

**Step 2: Commit**

```bash
git add src/brain/lambdas/orchestrator/handler.py
git commit -m "feat(brain): enable ECS Exec on dispatched tasks"
```

---

### Task 6: CLI — `cogent dr.alpha run list` and `cogent dr.alpha run shell`

**Files:**
- Create: `src/run/__init__.py`
- Create: `src/run/cli.py`
- Modify: `src/cli/__main__.py`

**Step 1: Create `src/run/__init__.py`**

Empty file.

**Step 2: Create `src/run/cli.py`**

```python
"""cogent run — interact with running ECS tasks."""

from __future__ import annotations

import os
import subprocess
import sys

import boto3
import click
from rich.console import Console
from rich.table import Table

from cli import get_cogent_name


@click.group()
def run():
    """Interact with running ECS tasks."""
    pass


def _get_cluster_name(cogent_name: str) -> str:
    return f"cogent-{cogent_name.replace('.', '-')}"


def _list_running_tasks(ecs_client, cluster: str) -> list[dict]:
    """List running ECS tasks with their details."""
    task_arns = ecs_client.list_tasks(
        cluster=cluster, desiredStatus="RUNNING"
    ).get("taskArns", [])
    if not task_arns:
        return []
    resp = ecs_client.describe_tasks(cluster=cluster, tasks=task_arns)
    return resp.get("tasks", [])


def _extract_env(task: dict, var_name: str) -> str:
    """Extract an environment variable from a task's container overrides."""
    for override in task.get("overrides", {}).get("containerOverrides", []):
        for env in override.get("environment", []):
            if env["name"] == var_name:
                return env["value"]
    return ""


def _task_id_from_arn(arn: str) -> str:
    """Extract task ID from full ARN."""
    return arn.rsplit("/", 1)[-1]


@run.command("list")
@click.pass_context
def list_cmd(ctx: click.Context):
    """List running ECS tasks."""
    name = get_cogent_name(ctx)
    cluster = _get_cluster_name(name)
    ecs_client = boto3.client("ecs")

    tasks = _list_running_tasks(ecs_client, cluster)
    if not tasks:
        click.echo("No running tasks.")
        return

    console = Console()
    table = Table(title=f"Running tasks — {cluster}")
    table.add_column("Task ID", style="cyan")
    table.add_column("Program")
    table.add_column("Started")
    table.add_column("Status")

    for task in tasks:
        task_id = _task_id_from_arn(task["taskArn"])
        payload_json = _extract_env(task, "EXECUTOR_PAYLOAD")
        program = ""
        if payload_json:
            import json
            try:
                payload = json.loads(payload_json)
                program = payload.get("trigger", {}).get("program_name", "")
            except (json.JSONDecodeError, KeyError):
                pass
        started = task.get("startedAt", "")
        if started:
            started = started.strftime("%H:%M:%S") if hasattr(started, "strftime") else str(started)
        status = task.get("lastStatus", "")
        table.add_row(task_id, program, started, status)

    console.print(table)


@run.command("shell")
@click.argument("run_id", required=False)
@click.pass_context
def shell_cmd(ctx: click.Context, run_id: str | None):
    """Attach to a running ECS task's tmux session.

    If RUN_ID is provided, connect to that specific task.
    Otherwise, list running tasks and prompt for selection.
    """
    name = get_cogent_name(ctx)
    cluster = _get_cluster_name(name)
    ecs_client = boto3.client("ecs")

    tasks = _list_running_tasks(ecs_client, cluster)
    if not tasks:
        click.echo("No running tasks.")
        return

    if run_id:
        # Find task matching the run_id (could be task ID prefix or full ARN)
        target = None
        for task in tasks:
            task_id = _task_id_from_arn(task["taskArn"])
            if task_id == run_id or task_id.startswith(run_id):
                target = task
                break
        if not target:
            click.echo(f"No running task found matching: {run_id}")
            return
    elif len(tasks) == 1:
        target = tasks[0]
    else:
        # Prompt for selection
        click.echo("Multiple running tasks:")
        for i, task in enumerate(tasks):
            task_id = _task_id_from_arn(task["taskArn"])
            payload_json = _extract_env(task, "EXECUTOR_PAYLOAD")
            program = ""
            if payload_json:
                import json
                try:
                    payload = json.loads(payload_json)
                    program = payload.get("trigger", {}).get("program_name", "")
                except (json.JSONDecodeError, KeyError):
                    pass
            click.echo(f"  [{i}] {task_id[:12]}  {program}")

        choice = click.prompt("Select task", type=int)
        if choice < 0 or choice >= len(tasks):
            click.echo("Invalid selection.")
            return
        target = tasks[choice]

    task_arn = target["taskArn"]
    task_id = _task_id_from_arn(task_arn)
    click.echo(f"Connecting to {task_id[:12]}...")

    # Use aws ecs execute-command to attach to tmux
    cmd = [
        "aws", "ecs", "execute-command",
        "--cluster", cluster,
        "--task", task_arn,
        "--container", "Executor",
        "--interactive",
        "--command", "tmux attach -t claude",
    ]
    os.execvp("aws", cmd)
```

**Step 3: Register the `run` command in `src/cli/__main__.py`**

Add `"run"` to the `_COMMANDS` set on line 9:
```python
_COMMANDS = {"dashboard", "brain", "memory", "mind", "run", "--help", "-h"}
```

Add the import and registration after the mind block (after line 53):
```python
# Run management CLI
from run.cli import run  # noqa: E402

main.add_command(run)
```

**Step 4: Add `src/run` to hatch packages in `pyproject.toml`**

In the `packages` list on line 49, add `"src/run"`.

**Step 5: Commit**

```bash
git add src/run/ src/cli/__main__.py pyproject.toml
git commit -m "feat(cli): add 'cogent run list' and 'cogent run shell' commands"
```

---

### Task 7: CLI — `cogent dr.alpha brain build`

**Files:**
- Modify: `src/brain/cli.py`

**Step 1: Add the `build` command to `src/brain/cli.py`**

Add after the `destroy_cmd` function (after line 96):

```python
@brain.command("build")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def build_cmd(ctx: click.Context, profile: str):
    """Build and push the executor Docker image to polis ECR."""
    import subprocess

    from polis.aws import get_polis_session

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    tag = f"executor-{safe_name}"

    # Get polis ECR repo URI
    polis_session, _ = get_polis_session()
    ecr_client = polis_session.client("ecr")
    repos = ecr_client.describe_repositories(repositoryNames=["cogent"])["repositories"]
    repo_uri = repos[0]["repositoryUri"]

    image = f"{repo_uri}:{tag}"
    click.echo(f"Building executor image: {image}")

    # Build
    result = subprocess.run(
        ["docker", "build", "-f", "src/brain/docker/Dockerfile", "-t", image, "."],
        capture_output=False,
    )
    if result.returncode != 0:
        raise click.ClickException("Docker build failed")

    # Login to ECR
    token = ecr_client.get_authorization_token()
    registry = repo_uri.split("/")[0]
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=token["authorizationData"][0]["authorizationToken"].encode(),
        capture_output=False,
    )

    # Push
    click.echo(f"Pushing {image}...")
    result = subprocess.run(["docker", "push", image], capture_output=False)
    if result.returncode != 0:
        raise click.ClickException("Docker push failed")

    click.echo(f"Image pushed: {image}")
```

**Step 2: Commit**

```bash
git add src/brain/cli.py
git commit -m "feat(brain): add 'brain build' command for executor Docker image"
```

---

### Task 8: Wire ECR repo URI into CDK deploy

**Files:**
- Modify: `src/brain/cli.py` (create_cmd)
- Modify: `src/brain/cdk/app.py`

**Step 1: Check how the CDK app receives context**

Read `src/brain/cdk/app.py` to see how `cogent_name` is passed, then pass `ecr_repo_uri` the same way.

In the `create_cmd` function in `src/brain/cli.py`, the CDK command is built on lines 48-58. Add a context parameter for the ECR repo URI by looking it up from polis before running CDK:

After `name = get_cogent_name(ctx)` (line 46), add:
```python
    # Look up polis ECR repo URI
    ecr_repo_uri = ""
    try:
        from polis.aws import get_polis_session
        polis_session, _ = get_polis_session()
        ecr_client = polis_session.client("ecr")
        repos = ecr_client.describe_repositories(repositoryNames=["cogent"])["repositories"]
        ecr_repo_uri = repos[0]["repositoryUri"]
    except Exception:
        click.echo("Warning: Could not resolve polis ECR repo. Using default image.")
```

Then add to the CDK cmd list:
```python
        "-c", f"ecr_repo_uri={ecr_repo_uri}",
```

**Step 2: Read `ecr_repo_uri` in the CDK app**

In `src/brain/cdk/app.py`, pass `ecr_repo_uri` from context into BrainConfig. Read the file first to see the current structure, then add:
```python
ecr_repo_uri=app.node.try_get_context("ecr_repo_uri") or "",
```
to the BrainConfig construction.

**Step 3: Commit**

```bash
git add src/brain/cli.py src/brain/cdk/app.py
git commit -m "feat(brain): pass polis ECR repo URI into CDK deploy"
```

---

### Task 9: Smoke test — build image locally

**Step 1: Verify the Dockerfile builds**

```bash
docker build -f src/brain/docker/Dockerfile -t cogent-executor-test .
```

Expected: successful build

**Step 2: Verify entrypoint and tools are present**

```bash
docker run --rm cogent-executor-test bash -c "which tmux && which claude && which gh && which vim && which aws && which uv && cogent --help"
```

Expected: paths for all tools, plus cogent CLI help output

**Step 3: Verify mind CLI is available**

```bash
docker run --rm cogent-executor-test mind --help
```

Expected: mind CLI help output

---

### Task 10: Final commit — all files together

**Step 1: Run lint**

```bash
ruff check src/run/ src/brain/cli.py src/brain/cdk/constructs/compute.py src/brain/cdk/config.py src/brain/lambdas/orchestrator/handler.py src/brain/lambdas/executor/ecs_entry.py src/cli/__main__.py --fix
```

**Step 2: Run type check**

```bash
pyright src/run/ src/brain/cli.py src/brain/cdk/constructs/compute.py
```

**Step 3: Final commit if any lint fixes**

```bash
git add -A && git commit -m "chore: lint fixes for ecs-tmux-shell feature"
```
