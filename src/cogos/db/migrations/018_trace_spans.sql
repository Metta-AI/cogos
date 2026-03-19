-- Distributed tracing: request traces, spans, and span events
CREATE TABLE IF NOT EXISTS cogos_request_trace (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cogent_id       VARCHAR NOT NULL DEFAULT '',
    source          VARCHAR NOT NULL DEFAULT '',
    source_ref      VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cogos_span (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID NOT NULL REFERENCES cogos_request_trace(id),
    parent_span_id  UUID REFERENCES cogos_span(id),
    name            VARCHAR NOT NULL,
    coglet          VARCHAR,
    status          VARCHAR NOT NULL DEFAULT 'running',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cogos_span_event (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    span_id         UUID NOT NULL REFERENCES cogos_span(id),
    event           VARCHAR NOT NULL,
    message         TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_cogos_span_trace ON cogos_span(trace_id);
CREATE INDEX IF NOT EXISTS idx_cogos_span_parent ON cogos_span(parent_span_id) WHERE parent_span_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cogos_span_event_span ON cogos_span_event(span_id);
CREATE INDEX IF NOT EXISTS idx_cogos_request_trace_created ON cogos_request_trace(created_at);
