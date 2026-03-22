#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Starting..."

# Start SSM agent in background (required for ECS Exec)
if command -v amazon-ssm-agent &>/dev/null; then
    nohup amazon-ssm-agent &>/var/log/ssm-agent.log &
    echo "[entrypoint] SSM agent started (pid $!)"
else
    echo "[entrypoint] WARNING: amazon-ssm-agent not found"
fi

# Write the runner script (captures exit code and signals tmux)
cat > /tmp/run-ecs-entry.sh << 'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
cd /app

if [ $# -gt 0 ]; then
    echo "[runner] Running command: $*"
    "$@" 2>&1 | tee /tmp/ecs-entry.log
    EXIT_CODE=${PIPESTATUS[0]}
elif [ -n "${EXECUTOR_PAYLOAD:-}" ]; then
    python -m cogtainer.lambdas.executor.ecs_entry 2>&1 | tee /tmp/ecs-entry.log
    EXIT_CODE=${PIPESTATUS[0]}
else
    SHELL_CMD="${SHELL_CMD:-bash}"
    echo "[runner] No EXECUTOR_PAYLOAD — starting $SHELL_CMD"
    echo "[runner] Exit to stop the container"
    $SHELL_CMD
    EXIT_CODE=$?
fi

# Write exit code for entrypoint to read
echo "$EXIT_CODE" > /tmp/ecs-exit-code
# Signal tmux wait-for
tmux wait-for -S claude-done
SCRIPT
chmod +x /tmp/run-ecs-entry.sh

echo "[entrypoint] Launching tmux session..."

# Start tmux session running the entry point, forwarding docker CMD args
tmux new-session -d -s claude "/tmp/run-ecs-entry.sh $*"

echo "[entrypoint] Waiting for session to complete..."

# Block until the session signals completion
tmux wait-for claude-done

# Exit with the same code as the Python process
EXIT_CODE=$(cat /tmp/ecs-exit-code 2>/dev/null || echo 1)
echo "[entrypoint] === ecs_entry.py output ==="
cat /tmp/ecs-entry.log 2>/dev/null || true
echo "[entrypoint] Exiting with code $EXIT_CODE"
exit "$EXIT_CODE"
