-- Cogent dashboard database schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    context_key TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    cli_session_id TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    last_active TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversations_cogent ON conversations(cogent_id);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    cogent_id TEXT NOT NULL,
    event_type TEXT,
    source TEXT,
    payload JSONB DEFAULT '{}'::jsonb,
    parent_event_id BIGINT REFERENCES events(id),
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_cogent ON events(cogent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(cogent_id, event_type);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events(parent_event_id);

CREATE TABLE IF NOT EXISTS executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    conversation_id UUID REFERENCES conversations(id),
    trigger_id UUID,
    status TEXT DEFAULT 'running',
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    duration_ms INT,
    tokens_input INT DEFAULT 0,
    tokens_output INT DEFAULT 0,
    cost_usd NUMERIC(12, 6) DEFAULT 0,
    events_emitted JSONB,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_executions_cogent ON executions(cogent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_executions_skill ON executions(cogent_id, skill_name);
CREATE INDEX IF NOT EXISTS idx_executions_conv ON executions(conversation_id);

CREATE TABLE IF NOT EXISTS triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    trigger_type TEXT,
    event_pattern TEXT,
    cron_expression TEXT,
    skill_name TEXT,
    priority INT DEFAULT 100,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_triggers_cogent ON triggers(cogent_id);

CREATE TABLE IF NOT EXISTS memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    scope TEXT DEFAULT 'agent',
    type TEXT DEFAULT 'text',
    name TEXT,
    content TEXT,
    provenance JSONB,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_cogent ON memory(cogent_id, name);

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    title TEXT,
    description TEXT,
    status TEXT DEFAULT 'pending',
    priority INT DEFAULT 100,
    source TEXT,
    external_id TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_cogent ON tasks(cogent_id, status);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    severity TEXT DEFAULT 'warning',
    alert_type TEXT,
    source TEXT,
    message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alerts_cogent ON alerts(cogent_id);

CREATE TABLE IF NOT EXISTS channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_channels_cogent ON channels(cogent_id);

CREATE TABLE IF NOT EXISTS skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    skill_type TEXT DEFAULT 'markdown',
    description TEXT,
    content TEXT,
    sla JSONB,
    triggers JSONB,
    resources JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_skills_cogent ON skills(cogent_id, name);

CREATE TABLE IF NOT EXISTS traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID REFERENCES executions(id),
    tool_calls JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traces_exec ON traces(execution_id);
