-- Rename event_delivery table and event column to match channels model
ALTER TABLE IF EXISTS cogos_event_delivery RENAME TO cogos_delivery;

DO $$ BEGIN
    ALTER TABLE cogos_delivery RENAME COLUMN event TO message;
EXCEPTION WHEN undefined_column THEN NULL;
END $$;

-- Also rename event column on cogos_run to message
DO $$ BEGIN
    ALTER TABLE cogos_run RENAME COLUMN event TO message;
EXCEPTION WHEN undefined_column THEN NULL;
END $$;

-- Drop event_pattern from handler if it still exists
ALTER TABLE IF EXISTS cogos_handler DROP COLUMN IF EXISTS event_pattern;

-- Drop event_types from capability if it still exists
ALTER TABLE IF EXISTS cogos_capability DROP COLUMN IF EXISTS event_types;

-- Rename event_pattern to channel_name on cron table (if column exists)
DO $$ BEGIN
    ALTER TABLE cron RENAME COLUMN event_pattern TO channel_name;
EXCEPTION WHEN undefined_column THEN NULL;
END $$;
