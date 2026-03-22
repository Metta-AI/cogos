-- Discord metadata tables for guild and channel info synced by the bridge.

CREATE TABLE IF NOT EXISTS cogos_discord_guild (
    guild_id TEXT PRIMARY KEY,
    cogent_name TEXT NOT NULL,
    name TEXT NOT NULL,
    icon_url TEXT,
    member_count INTEGER,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cogos_discord_channel (
    channel_id TEXT PRIMARY KEY,
    guild_id TEXT NOT NULL,
    name TEXT NOT NULL,
    topic TEXT,
    category TEXT,
    channel_type TEXT NOT NULL,
    position INTEGER DEFAULT 0,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
