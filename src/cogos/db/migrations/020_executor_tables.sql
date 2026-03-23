-- Channel-based persistent executor registry and token management.

CREATE TABLE IF NOT EXISTS cogos_executor (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    executor_id       TEXT NOT NULL,
    channel_type      TEXT NOT NULL DEFAULT 'claude-code',
    executor_tags     JSONB NOT NULL DEFAULT '[]',
    dispatch_type     TEXT NOT NULL DEFAULT 'channel',
    metadata          JSONB NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'idle'
                      CHECK (status IN ('idle', 'busy', 'stale', 'dead')),
    current_run_id    UUID,
    last_heartbeat_at TIMESTAMPTZ,
    registered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(executor_id)
);

CREATE INDEX IF NOT EXISTS idx_executor_status ON cogos_executor(status);

CREATE TABLE IF NOT EXISTS cogos_executor_token (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    token_hash  TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'executor',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_executor_token_hash ON cogos_executor_token(token_hash) WHERE revoked_at IS NULL;
