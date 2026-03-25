-- Rename input_schema/output_schema to single schema column on cogos_capability
-- Also add name column and update unique constraint on cogos_process_capability

-- Step 1: Add schema column if missing (old tables have input_schema instead)
ALTER TABLE cogos_capability ADD COLUMN IF NOT EXISTS schema JSONB NOT NULL DEFAULT '{}';

-- Step 2: Drop old columns if they exist
ALTER TABLE cogos_capability DROP COLUMN IF EXISTS input_schema;
ALTER TABLE cogos_capability DROP COLUMN IF EXISTS output_schema;

-- Step 3: Add name column to cogos_process_capability if missing
ALTER TABLE cogos_process_capability ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '';

-- Step 4: Drop old delegatable column if it exists
ALTER TABLE cogos_process_capability DROP COLUMN IF EXISTS delegatable;

-- Step 5: Add unique constraint on (process, name) if not exists
-- Uses CREATE UNIQUE INDEX which supports IF NOT EXISTS (no DO $$ block needed).
ALTER TABLE cogos_process_capability DROP CONSTRAINT IF EXISTS cogos_process_capability_process_capability_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_process_capability_process_name ON cogos_process_capability (process, name);
