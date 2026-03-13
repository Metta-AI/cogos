-- Rename event_delivery table and event column to match channels model
ALTER TABLE IF EXISTS cogos_event_delivery RENAME TO cogos_delivery;
ALTER TABLE IF EXISTS cogos_delivery RENAME COLUMN event TO message;

-- Also rename event column on cogos_run to message
ALTER TABLE IF EXISTS cogos_run RENAME COLUMN event TO message;

-- Drop event_pattern from handler if it still exists
ALTER TABLE IF EXISTS cogos_handler DROP COLUMN IF EXISTS event_pattern;

-- Drop event_types from capability if it still exists
ALTER TABLE IF EXISTS cogos_capability DROP COLUMN IF EXISTS event_types;

-- Rename event_pattern to channel_name on cogos_cron (if column exists)
DO $$ BEGIN
    ALTER TABLE cogos_cron RENAME COLUMN event_pattern TO channel_name;
EXCEPTION WHEN undefined_column THEN NULL;
END $$;
