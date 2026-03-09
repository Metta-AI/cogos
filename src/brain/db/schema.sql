-- Cogent database schema v4
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

-- Knowledge store: hierarchical named memory records
CREATE TABLE IF NOT EXISTS memory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope       TEXT NOT NULL CHECK (scope IN ('polis', 'cogent')),
    name        TEXT,
    content     TEXT NOT NULL DEFAULT '',
    provenance  JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_unique_name ON memory (scope, name) WHERE name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory (scope);
CREATE INDEX IF NOT EXISTS idx_memory_name ON memory (name) WHERE name IS NOT NULL;

-- Add embedding column if pgvector is available
DO $$ BEGIN
    ALTER TABLE memory ADD COLUMN IF NOT EXISTS embedding vector(1536);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector not available, skipping embedding column';
END $$;

-- Versioned memory store
CREATE TABLE IF NOT EXISTS memory_v2 (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT UNIQUE NOT NULL,
    active_version  INT NOT NULL DEFAULT 1,
    includes        JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT now(),
    modified_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_version (
    id          UUID DEFAULT gen_random_uuid(),
    memory_id   UUID NOT NULL REFERENCES memory_v2(id) ON DELETE CASCADE,
    version     INT NOT NULL,
    read_only   BOOLEAN DEFAULT FALSE,
    content     TEXT DEFAULT '',
    source      TEXT DEFAULT 'cogent',
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (memory_id, version)
);

-- Program definitions
CREATE TABLE IF NOT EXISTS programs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL UNIQUE,
    memory_id     UUID REFERENCES memory_v2(id),
    memory_version INT,
    tools         JSONB NOT NULL DEFAULT '[]',
    metadata      JSONB NOT NULL DEFAULT '{}',
    runner          TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL,
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
    throttle_timestamps JSONB NOT NULL DEFAULT '[]',
    throttle_rejected   INTEGER NOT NULL DEFAULT 0,
    throttle_active     BOOLEAN NOT NULL DEFAULT false,
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

-- Tool definitions (Code Mode)
CREATE TABLE IF NOT EXISTS tools (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    instructions    TEXT NOT NULL DEFAULT '',
    input_schema    JSONB NOT NULL DEFAULT '{}',
    handler         TEXT NOT NULL DEFAULT '',
    iam_role_arn    TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tools_name ON tools (name);
CREATE INDEX IF NOT EXISTS idx_tools_enabled ON tools (enabled) WHERE enabled = true;

-- ═══════════════════════════════════════════════════════════
-- WORK
-- ═══════════════════════════════════════════════════════════

-- Work queue
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    program_name    TEXT NOT NULL REFERENCES programs(name),
    content         TEXT NOT NULL DEFAULT '',
    memory_keys     JSONB NOT NULL DEFAULT '[]',
    tools           JSONB NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'runnable'
                    CHECK (status IN ('runnable', 'scheduled', 'running', 'completed', 'disabled')),
    priority        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    runner          TEXT CHECK (runner IN ('lambda', 'ecs')) DEFAULT NULL,
    clear_context   BOOLEAN NOT NULL DEFAULT false,
    recurrent       BOOLEAN NOT NULL DEFAULT false,
    resources       JSONB NOT NULL DEFAULT '[]',
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_unique_name ON tasks (name);

-- Multi-turn conversation routing
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_key TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'idle', 'closed')),
    cli_session_id TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_conversations_context ON conversations (context_key) WHERE status != 'closed';

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

-- Resource pool and budget tracking
CREATE TABLE IF NOT EXISTS resources (
    name          TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('pool', 'consumable')),
    capacity      DOUBLE PRECISION NOT NULL DEFAULT 1,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resource_usage (
    id            BIGSERIAL PRIMARY KEY,
    resource_name TEXT NOT NULL REFERENCES resources(name),
    run_id        UUID NOT NULL REFERENCES runs(id),
    amount        DOUBLE PRECISION NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_resource_usage_resource ON resource_usage (resource_name);
CREATE INDEX IF NOT EXISTS idx_resource_usage_run ON resource_usage (run_id);

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
    status          TEXT NOT NULL DEFAULT 'proposed'
                    CHECK (status IN ('proposed', 'sent')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events (parent_event_id) WHERE parent_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_proposed ON events (id) WHERE status = 'proposed';

-- Auto-emit task:run event when a task is scheduled
CREATE OR REPLACE FUNCTION task_scheduled_trigger() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'scheduled' AND (OLD IS NULL OR OLD.status != 'scheduled') THEN
        INSERT INTO events (event_type, source, payload, status)
        VALUES (
            'task:run',
            'db-trigger',
            jsonb_build_object('task_id', NEW.id::text, 'task_name', NEW.name),
            'proposed'
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS task_scheduled ON tasks;
CREATE TRIGGER task_scheduled
    AFTER INSERT OR UPDATE OF status ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION task_scheduled_trigger();

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
INSERT INTO schema_version (version) VALUES (9) ON CONFLICT DO NOTHING;
