-- Backfill NULL config → '{}' and set column default
UPDATE cogos_process_capability SET config = '{}' WHERE config IS NULL;
ALTER TABLE cogos_process_capability ALTER COLUMN config SET DEFAULT '{}';
ALTER TABLE cogos_process_capability ALTER COLUMN config SET NOT NULL;
