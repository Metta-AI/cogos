-- Add metadata to cogos_run so dispatcher dead-letter reporting can mark runs
-- as already reported without crashing older stacks.
ALTER TABLE cogos_run
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
