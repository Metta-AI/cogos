-- Add idempotency_key to channel messages to prevent duplicate inserts
-- from external sources (e.g. Discord bridge reconnects).

ALTER TABLE cogos_channel_message
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_cogos_channel_message_idempotency
    ON cogos_channel_message(channel, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
