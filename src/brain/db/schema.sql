-- Cogent database schema v3
-- Requires: PostgreSQL 16, pgvector optional (for semantic search)
-- Each cogent has its own database; no cogent_id column needed.

DO $$ BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector not available, semantic search disabled';
END $$;

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════
-- CORE
-- ═══════════════════════════════════════════════════════════

-- Knowledge store: facts, episodic memories, prompts
CREATE TABLE IF NOT EXISTS memory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope       TEXT NOT NULL CHECK (scope IN ('polis', 'cogent')),
    type        TEXT NOT NULL CHECK (type IN ('fact', 'episodic', 'prompt', 'policy')),
    name        TEXT,
    content     TEXT NOT NULL DEFAULT '',
    provenance  JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_unique_name ON memory (scope, name) WHERE name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory (scope, type);
CREATE INDEX IF NOT EXISTS idx_memory_name ON memory (name) WHERE name IS NOT NULL;

-- Add embedding column if pgvector is available
DO $$ BEGIN
    ALTER TABLE memory ADD COLUMN IF NOT EXISTS embedding vector(1536);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector not available, skipping embedding column';
END $$;

-- Program definitions
CREATE TABLE IF NOT EXISTS programs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL UNIQUE,
    program_type  TEXT NOT NULL DEFAULT 'prompt' CHECK (program_type IN ('prompt', 'python')),
    content       TEXT NOT NULL DEFAULT '',
    includes      JSONB NOT NULL DEFAULT '[]',
    tools         JSONB NOT NULL DEFAULT '[]',
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_programs_name ON programs (name);

-- Event→program wiring
CREATE TABLE IF NOT EXISTS triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_name    TEXT NOT NULL REFERENCES programs(name),
    event_pattern   TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 10,
    config          JSONB NOT NULL DEFAULT '{}',
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_triggers_enabled ON triggers (event_pattern) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_triggers_program ON triggers (program_name);

-- Cron schedules (emit events on schedule)
CREATE TABLE IF NOT EXISTS cron (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cron_expression TEXT NOT NULL,
    event_pattern   TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cron_enabled ON cron (enabled) WHERE enabled = true;

-- ═══════════════════════════════════════════════════════════
-- WORK
-- ═══════════════════════════════════════════════════════════

-- Channel registry
CREATE TABLE IF NOT EXISTS channels (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        TEXT NOT NULL CHECK (type IN ('discord', 'github', 'email', 'asana', 'cli')),
    name        TEXT NOT NULL,
    external_id TEXT,
    secret_arn  TEXT,
    config      JSONB NOT NULL DEFAULT '{}',
    enabled     BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (type, name)
);
CREATE INDEX IF NOT EXISTS idx_channels_type ON channels (type);

-- Work queue
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'failed', 'completed')),
    priority        INTEGER NOT NULL DEFAULT 0,
    parent_task_id  UUID REFERENCES tasks(id),
    creator         TEXT NOT NULL DEFAULT '',
    source_event    TEXT,
    limits          JSONB NOT NULL DEFAULT '{}',
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks (parent_task_id) WHERE parent_task_id IS NOT NULL;

-- Multi-turn conversation routing
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_key TEXT NOT NULL,
    channel_id  UUID REFERENCES channels(id),
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'idle', 'closed')),
    cli_session_id TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_conversations_context ON conversations (context_key) WHERE status != 'closed';
CREATE INDEX IF NOT EXISTS idx_conversations_channel ON conversations (channel_id) WHERE channel_id IS NOT NULL;

-- Per-invocation summary
CREATE TABLE IF NOT EXISTS runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_name    TEXT NOT NULL,
    task_id         UUID REFERENCES tasks(id),
    trigger_id      UUID REFERENCES triggers(id),
    conversation_id UUID REFERENCES conversations(id),
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'completed', 'failed', 'timeout')),
    tokens_input    INTEGER NOT NULL DEFAULT 0,
    tokens_output   INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10, 6) NOT NULL DEFAULT 0,
    duration_ms     INTEGER,
    model_version   TEXT,
    events_emitted  JSONB NOT NULL DEFAULT '[]',
    error           TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_program ON runs (program_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status);

-- Detailed execution audit
CREATE TABLE IF NOT EXISTS traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES runs(id),
    tool_calls      JSONB NOT NULL DEFAULT '[]',
    memory_ops      JSONB NOT NULL DEFAULT '[]',
    model_version   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traces_run ON traces (run_id);

-- ═══════════════════════════════════════════════════════════
-- INFRASTRUCTURE
-- ═══════════════════════════════════════════════════════════

-- Append-only event log with causal chain
CREATE TABLE IF NOT EXISTS events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    source          TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    parent_event_id BIGINT REFERENCES events(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events (parent_event_id) WHERE parent_event_id IS NOT NULL;

-- Algedonic emergency alerts
CREATE TABLE IF NOT EXISTS alerts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    severity    TEXT NOT NULL CHECK (severity IN ('warning', 'critical', 'emergency')),
    alert_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    message     TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}',
    acknowledged_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alerts_unresolved ON alerts (created_at DESC) WHERE resolved_at IS NULL;

-- Token/cost budget accounting
CREATE TABLE IF NOT EXISTS budget (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period          TEXT NOT NULL CHECK (period IN ('daily', 'weekly', 'monthly')),
    period_start    DATE NOT NULL,
    tokens_spent    BIGINT NOT NULL DEFAULT 0,
    cost_spent_usd  NUMERIC(10, 4) NOT NULL DEFAULT 0,
    token_limit     BIGINT NOT NULL DEFAULT 0,
    cost_limit_usd  NUMERIC(10, 4) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (period, period_start)
);

-- Enable IAM auth for the cogent user
DO $$ BEGIN
    EXECUTE 'GRANT rds_iam TO cogent';
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'rds_iam grant skipped (not on RDS or already granted)';
END $$;

-- Insert initial schema version
INSERT INTO schema_version (version) VALUES (3) ON CONFLICT DO NOTHING;
