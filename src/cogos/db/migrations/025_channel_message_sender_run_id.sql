-- Track which run sent each channel message
ALTER TABLE cogos_channel_message
  ADD COLUMN IF NOT EXISTS sender_run_id UUID;

ALTER TABLE cogos_channel_message
  DROP CONSTRAINT IF EXISTS cogos_channel_message_sender_run_id_fkey;

ALTER TABLE cogos_channel_message
  ADD CONSTRAINT cogos_channel_message_sender_run_id_fkey
  FOREIGN KEY (sender_run_id) REFERENCES cogos_run(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_channel_message_sender_run_id
  ON cogos_channel_message(sender_run_id);
