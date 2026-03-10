-- Add files jsonb array to cogos_process (replaces single code FK)
ALTER TABLE cogos_process ADD COLUMN IF NOT EXISTS files JSONB NOT NULL DEFAULT '[]';

-- Migrate existing code references into files array
UPDATE cogos_process
SET files = jsonb_build_array(code::text)
WHERE code IS NOT NULL AND files = '[]';
