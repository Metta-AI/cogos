#!/bin/sh
set -e

# Start FastAPI backend
python -m uvicorn cogos.api.app:app --host 0.0.0.0 --port 8100 &
BACKEND_PID=$!

# Pre-warm: wait for backend, then trigger auth + DB cold-start
echo "[start] Waiting for backend..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8100/healthz > /dev/null 2>&1; then
        echo "[start] Backend ready, pre-warming..."
        # Trigger Secrets Manager API key lookup + RDS Data API connection
        # so the first user request doesn't pay the cold-start penalty
        python -c "
from dashboard.auth import _load_api_key
_load_api_key()
from cogos.api.db import get_repo
repo = get_repo()
repo._execute('SELECT 1')
print('[start] Pre-warm: auth + DB ready')
" 2>&1 || echo "[start] Pre-warm failed (non-fatal)"
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
