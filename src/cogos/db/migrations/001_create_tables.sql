-- CogOS database schema
-- Run against the cogent database to create all CogOS tables.

-- Use gen_random_uuid() (pgcrypto / built-in in PG 13+) instead of uuid-ossp

-- ═══════════════════════════════════════════════════════════
-- FILES (versioned hierarchical store)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_file (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key         TEXT NOT NULL UNIQUE,
    includes    JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cogos_file_version (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id     UUID NOT NULL REFERENCES cogos_file(id) ON DELETE CASCADE,
    version     INT NOT NULL,
    read_only   BOOLEAN NOT NULL DEFAULT FALSE,
    content     TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'cogent',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (file_id, version)
);

-- ═══════════════════════════════════════════════════════════
-- CAPABILITIES (what processes can do)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_capability (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    instructions    TEXT NOT NULL DEFAULT '',
    handler         TEXT NOT NULL DEFAULT '',
    schema          JSONB NOT NULL DEFAULT '{}',
    iam_role_arn    TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB NOT NULL DEFAULT '{}',
    event_types     JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════
-- PROCESSES (the only active entity)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_process (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL UNIQUE,
    mode                TEXT NOT NULL DEFAULT 'one_shot' CHECK (mode IN ('daemon', 'one_shot')),
    content             TEXT NOT NULL DEFAULT '',
    priority            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    resources           JSONB NOT NULL DEFAULT '[]',
    runner              TEXT NOT NULL DEFAULT 'lambda',
    status              TEXT NOT NULL DEFAULT 'waiting'
                        CHECK (status IN ('waiting', 'runnable', 'running', 'blocked',
                                          'suspended', 'completed', 'disabled')),
    runnable_since      TIMESTAMPTZ,
    parent_process      UUID REFERENCES cogos_process(id),
    preemptible         BOOLEAN NOT NULL DEFAULT FALSE,
    model               TEXT,
    model_constraints   JSONB NOT NULL DEFAULT '{}',
    return_schema       JSONB,
    max_duration_ms     INT,
    max_retries         INT NOT NULL DEFAULT 0,
    retry_count         INT NOT NULL DEFAULT 0,
    retry_backoff_ms    INT,
    clear_context       BOOLEAN NOT NULL DEFAULT FALSE,
    metadata            JSONB NOT NULL DEFAULT '{}',
    output_events       JSONB NOT NULL DEFAULT '[]',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════
-- PROCESS CAPABILITIES (join table)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_process_capability (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    process     UUID NOT NULL REFERENCES cogos_process(id) ON DELETE CASCADE,
    capability  UUID NOT NULL REFERENCES cogos_capability(id) ON DELETE CASCADE,
    name        TEXT NOT NULL DEFAULT '',
    config      JSONB,
    UNIQUE (process, name)
);

-- ═══════════════════════════════════════════════════════════
-- HANDLERS (bind process to event pattern)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_handler (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    process         UUID NOT NULL REFERENCES cogos_process(id) ON DELETE CASCADE,
    event_pattern   TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (process, event_pattern)
);

-- ═══════════════════════════════════════════════════════════
-- EVENTS (append-only signal log)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_event (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      TEXT NOT NULL,
    source          TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    parent_event    UUID REFERENCES cogos_event(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cogos_event_type ON cogos_event(event_type);
CREATE INDEX IF NOT EXISTS idx_cogos_event_created ON cogos_event(created_at);

-- ═══════════════════════════════════════════════════════════
-- EVENT DELIVERY (per-handler delivery tracking)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_event_delivery (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event       UUID NOT NULL REFERENCES cogos_event(id) ON DELETE CASCADE,
    handler     UUID NOT NULL REFERENCES cogos_handler(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'queued', 'delivered', 'skipped')),
    run         UUID,  -- FK added after cogos_run is created
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════
-- CONVERSATIONS
-- ═══════════════════════════════════════════════════════════

-- Reuse existing conversations table (no changes needed)

-- ═══════════════════════════════════════════════════════════
-- RUNS (execution records)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_run (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    process         UUID NOT NULL REFERENCES cogos_process(id),
    event           UUID REFERENCES cogos_event(id),
    conversation    UUID,  -- FK to conversations table
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'completed', 'failed', 'timeout', 'suspended')),
    tokens_in       INT NOT NULL DEFAULT 0,
    tokens_out      INT NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(12, 6) NOT NULL DEFAULT 0,
    duration_ms     INT,
    error           TEXT,
    model_version   TEXT,
    result          JSONB,
    snapshot        JSONB,
    scope_log       JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

-- Add FK from event_delivery to run
ALTER TABLE cogos_event_delivery
    ADD CONSTRAINT fk_event_delivery_run
    FOREIGN KEY (run) REFERENCES cogos_run(id);

-- ═══════════════════════════════════════════════════════════
-- RESOURCES (pool and consumable limits)
-- Reuse existing resource/resource_usage tables
-- ═══════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════
-- CRON (scheduled event emitter)
-- Reuse existing cron table
-- ═══════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════
-- EVENT TYPES (registry for typeahead suggestions)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_event_type (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════
-- TRACES (detailed execution audit)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_trace (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run                 UUID NOT NULL REFERENCES cogos_run(id) ON DELETE CASCADE,
    capability_calls    JSONB NOT NULL DEFAULT '[]',
    file_ops            JSONB NOT NULL DEFAULT '[]',
    model_version       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
