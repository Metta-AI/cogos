#!/bin/sh
set -e

FRONTEND_PID=""

download_frontend() {
    local target="${1:-/app/frontend}"
    if [ -n "$DASHBOARD_ASSETS_S3" ]; then
        echo "Downloading frontend assets from $DASHBOARD_ASSETS_S3 ..."
        mkdir -p "$target"
        aws s3 cp "$DASHBOARD_ASSETS_S3" /tmp/frontend.tar.gz --quiet
        rm -rf "$target"/*
        tar xzf /tmp/frontend.tar.gz -C "$target"
        rm /tmp/frontend.tar.gz
        echo "Frontend assets ready."
    else
        echo "WARNING: DASHBOARD_ASSETS_S3 not set, frontend may not be available."
    fi
}

start_frontend() {
    if [ -f /app/frontend/server.js ]; then
        node /app/frontend/server.js &
        FRONTEND_PID=$!
        echo "Frontend started (PID $FRONTEND_PID)."
    else
        echo "WARNING: /app/frontend/server.js not found, frontend not started."
        FRONTEND_PID=""
    fi
}

reload_frontend() {
    echo "Reloading frontend assets..."
    # Download to staging dir first (Node keeps serving old build)
    rm -rf /app/frontend_staging
    download_frontend /app/frontend_staging

    # Kill old Node, swap dirs, restart — minimizes downtime
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        kill "$FRONTEND_PID" 2>/dev/null
        wait "$FRONTEND_PID" 2>/dev/null || true
    fi
    rm -rf /app/frontend
    mv /app/frontend_staging /app/frontend
    start_frontend
}

# Initial download
download_frontend

# Start FastAPI backend
python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8100 &
BACKEND_PID=$!

# Start Next.js frontend
start_frontend

# Write PID file so the backend can signal us
echo $$ > /tmp/entrypoint.pid

# SIGUSR1 = reload frontend assets from S3
trap 'reload_frontend' USR1
# SIGTERM/SIGINT = clean shutdown
trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0' TERM INT

# Wait for both; if either exits, kill the other
# Use sleep loop (not wait) so traps are delivered promptly
while kill -0 "$BACKEND_PID" 2>/dev/null; do
    if [ -n "$FRONTEND_PID" ] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "Frontend process exited unexpectedly."
        break
    fi
    sleep 1
done

kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
exit 1
