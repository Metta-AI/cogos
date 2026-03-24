-- Make wait_condition FKs cascade on delete so clear_config ordering doesn't matter.

ALTER TABLE cogos_wait_condition DROP CONSTRAINT IF EXISTS cogos_wait_condition_run_fkey;
ALTER TABLE cogos_wait_condition ADD CONSTRAINT cogos_wait_condition_run_fkey
    FOREIGN KEY (run) REFERENCES cogos_run(id) ON DELETE CASCADE;

ALTER TABLE cogos_wait_condition DROP CONSTRAINT IF EXISTS cogos_wait_condition_process_fkey;
ALTER TABLE cogos_wait_condition ADD CONSTRAINT cogos_wait_condition_process_fkey
    FOREIGN KEY (process) REFERENCES cogos_process(id) ON DELETE CASCADE;
