Deploy everything for the currently selected cogent (assumes cogtainer infra is up to date).

## Pre-flight

1. Ensure no uncommitted changes: `git status --porcelain` must be empty. If dirty, stop and ask.
2. Pull latest: `git pull --ff-only`. If it fails (diverged), stop and ask.
3. Ensure the right cogent is selected: check `.env` for COGTAINER/COGENT, or run `cogent select <name>` to set them. Confirm selection with the user before proceeding.

## Monitoring rules

**CRITICAL: Actively monitor every step. Do NOT fire-and-forget.**

- Run each command with a timeout. If a step takes longer than expected, do NOT just wait — investigate immediately.
- For CDK stack updates: if it takes >3 minutes, check CloudFormation events for stuck resources:
  ```bash
  aws cloudformation describe-stack-events --stack-name <stack> --query 'StackEvents[?ResourceStatus==`CREATE_IN_PROGRESS` || ResourceStatus==`UPDATE_IN_PROGRESS`].[LogicalResourceId,ResourceStatus,ResourceStatusReason]' --output table --profile softmax-org
  ```
- For ECS deployments (dashboard, discord): if stabilization takes >2 minutes, check the service events and task status:
  ```bash
  # Check service events for errors
  aws ecs describe-services --cluster <cluster> --services <service> --query 'services[0].events[:5].[createdAt,message]' --output table
  # Check if tasks are failing to start
  aws ecs list-tasks --cluster <cluster> --service-name <service> --desired-status STOPPED --query 'taskArns[:3]'
  # Get stopped task reason
  aws ecs describe-tasks --cluster <cluster> --tasks <task-arn> --query 'tasks[0].{stopCode:stopCode,reason:stoppedReason,container:containers[0].reason}'
  ```
- For Lambda updates: these should be fast (<30s each). If one hangs, check if the function exists and is not in an update-in-progress state.
- For `cogos restart`: watch the output. If it stalls during boot or migration, check the dispatcher logs.
- On ANY failure or timeout: stop, diagnose, and report to the user with the specific error. Do not retry blindly.

## Deploy sequence

Run these steps in order. Stop on any failure and report to the user.

### 1. CDK stack (task definitions, IAM, Lambda config)

```bash
cogent update stack
```

Expected: ~1-3 min. Watch for CloudFormation rollbacks.

### 2. Lambda functions (executor, dispatcher, event-router)

```bash
cogent update lambda
```

Expected: ~30-60s. Should report each function as "updated" or "not found (skip)".

### 3. DB migrations

```bash
cogent update rds
```

Expected: ~10-30s. Watch for schema version output and statement count.

### 4. Dashboard (ECS)

**IMPORTANT: Before deploying, verify the dashboard ECR image exists.** Dashboard ECR tags use `sha-{sha}` format (not bare SHA). Check `versions.defaults.json` for the dashboard SHA, then verify `sha-{sha}` exists in the `cogent-dashboard` ECR repo. If the tag doesn't exist, find the latest available tag and use that instead via `--sha`.

```bash
cogent update dashboard --skip-health
```

Use `--skip-health` to avoid blocking on the waiter. Instead, manually poll the service events while it deploys to catch image pull failures, OOM, or health check issues early. Check service stability yourself:

```bash
# Poll until deployment completes or fails — check every 15s, bail after 3 min
aws ecs describe-services --cluster <cluster> --services <service> --query 'services[0].deployments[*].[status,runningCount,desiredCount,rolloutState]' --output table
```

If `rolloutState` is `FAILED` or running count stays at 0, investigate immediately.

### 5. Discord bridge (ECS)

```bash
cogent update discord --skip-health
```

Same monitoring approach as dashboard. Discord bridge is less critical — if it fails, note it but continue.

### 6. Reboot image (capabilities, files, processes)

```bash
cogos restart
```

Watch for successful boot completion. If it stalls, check for migration errors or capability loading failures in the output.

## Post-deploy

1. Verify the running system:

```bash
cogos status
cogos process list
```

2. Check the deployed API version. Derive the cogent URL from `.env` — the safe name is COGENT with dots replaced by hyphens:

```bash
curl -s "https://$(grep COGENT .env | cut -d= -f2 | tr '.' '-').softmax-cogents.com/api/version" | python3 -m json.tool
```

Confirm the `components` in the response match expectations (lambda SHA, dashboard SHA, etc.).

3. Load the dashboard in a browser and verify it works. Use `/dashboard.test` to:
   - Hit `/healthz` and `/api/version` via curl
   - Open the dashboard URL in a browser with `agent-browser`
   - Confirm the page loads (no 502, no Cloudflare login wall)
   - Verify processes and status are visible
   - If the dashboard fails to load or shows errors, diagnose and report immediately

4. Report a summary showing which steps succeeded, how long each took, and any warnings.
