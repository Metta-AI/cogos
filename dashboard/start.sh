#!/bin/sh
set -e

# Start FastAPI backend
python -m uvicorn cogos.api.app:app --host 0.0.0.0 --port 8100 &
BACKEND_PID=$!

# Pre-warm: wait for backend, then hit a real dashboard endpoint
# to warm auth (Secrets Manager) + DB (RDS Data API) inside the
# actual uvicorn worker process
echo "[start] Waiting for backend..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8100/healthz > /dev/null 2>&1; then
        echo "[start] Backend ready, pre-warming auth + DB..."
        # Hit an actual dashboard endpoint — this triggers:
        # 1. verify_dashboard_api_key → Secrets Manager lookup (cached after first call)
        # 2. get_repo() → RDS Data API client creation (LRU cached)
        # 3. A real DB query to warm the connection
        # Use alerts endpoint (lightweight, just reads a small table)
        COGENT_NAME="${COGENT:-unknown}"
        curl -sf --max-time 45 "http://127.0.0.1:8100/api/cogents/${COGENT_NAME}/alerts" > /dev/null 2>&1 \
            && echo "[start] Pre-warm complete" \
            || echo "[start] Pre-warm timed out (non-fatal, first user request may be slow)"
        break
    fi
    sleep 1
done

# Start Next.js frontend
node /app/frontend/server.js &
FRONTEND_PID=$!

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0' TERM INT

# Wait — if either exits, shut down
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
done

kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
exit 1
