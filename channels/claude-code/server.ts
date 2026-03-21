/**
 * Claude Code channel server for CogOS.
 *
 * Bridges CogOS channels into a running Claude Code session:
 *   - Polls the CogOS dashboard API for new messages on subscribed channels
 *   - Emits MCP channel notifications so Claude sees them as <channel> events
 *   - Exposes `send` and `reply` tools for writing back to CogOS channels
 *
 * Environment variables:
 *   COGOS_API_URL      – Dashboard API base URL (e.g. http://localhost:8100)
 *   COGOS_COGENT_NAME  – Cogent name for API path prefix
 *   COGOS_API_KEY      – Optional API key for authenticated access
 *   COGOS_CHANNELS     – Comma-separated channel name patterns to subscribe to
 *                        (default: "io:claude-code:*")
 *   COGOS_POLL_MS      – Poll interval in milliseconds (default: 3000)
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_URL = process.env.COGOS_API_URL || "http://localhost:8100";
const COGENT_NAME = process.env.COGOS_COGENT_NAME || "";
const API_KEY = process.env.COGOS_API_KEY || "";
const CHANNEL_PATTERNS = (
  process.env.COGOS_CHANNELS || "io:claude-code:*"
).split(",").map((s) => s.trim());
const POLL_MS = parseInt(process.env.COGOS_POLL_MS || "3000", 10);

function apiBase(): string {
  if (COGENT_NAME) {
    return `${API_URL}/api/cogents/${COGENT_NAME}`;
  }
  return API_URL;
}

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) {
    h["x-api-key"] = API_KEY;
  }
  return h;
}

// ---------------------------------------------------------------------------
// CogOS API client
// ---------------------------------------------------------------------------

interface CogosChannel {
  id: string;
  name: string;
  channel_type: string;
  message_count: number;
}

interface CogosMessage {
  id: string;
  channel: string;
  sender_process: string;
  sender_process_name?: string;
  payload: Record<string, unknown>;
  created_at: string;
}

async function fetchChannels(): Promise<CogosChannel[]> {
  try {
    const resp = await fetch(`${apiBase()}/channels`, { headers: headers() });
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.channels || [];
  } catch {
    return [];
  }
}

async function fetchChannelMessages(
  channelId: string,
  limit = 50,
): Promise<CogosMessage[]> {
  try {
    const resp = await fetch(
      `${apiBase()}/channels/${channelId}?limit=${limit}`,
      { headers: headers() },
    );
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.messages || [];
  } catch {
    return [];
  }
}

async function sendChannelMessage(
  channelId: string,
  payload: Record<string, unknown>,
): Promise<{ id?: string; error?: string }> {
  try {
    const resp = await fetch(`${apiBase()}/channels/${channelId}/messages`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ payload }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      return { error: (err as Record<string, string>).detail || resp.statusText };
    }
    const data = await resp.json();
    return { id: data.id };
  } catch (e) {
    return { error: String(e) };
  }
}

// ---------------------------------------------------------------------------
// Channel name matching (fnmatch-style with * glob)
// ---------------------------------------------------------------------------

function matchesPattern(name: string, pattern: string): boolean {
  // Convert fnmatch pattern to regex
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp("^" + escaped.replace(/\*/g, ".*") + "$");
  return regex.test(name);
}

function matchesAnyPattern(name: string): boolean {
  return CHANNEL_PATTERNS.some((p) => matchesPattern(name, p));
}

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

const server = new Server(
  { name: "cogos-channels", version: "0.1.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
      tools: {},
    },
  },
);

// Track seen message IDs to avoid duplicate notifications
const seenMessages = new Set<string>();
// Cache channel name -> id mapping
const channelIndex = new Map<string, string>();

// ---------------------------------------------------------------------------
// Tools: send to a CogOS channel, list channels
// ---------------------------------------------------------------------------

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "reply",
      description:
        "Send a message back to a CogOS channel. Use this to respond to channel events.",
      inputSchema: {
        type: "object" as const,
        properties: {
          channel: {
            type: "string",
            description:
              "Channel name (e.g. 'io:claude-code:responses') or channel ID",
          },
          payload: {
            type: "object",
            description: "Message payload (must match channel schema if defined)",
            additionalProperties: true,
          },
        },
        required: ["channel", "payload"],
      },
    },
    {
      name: "send",
      description:
        "Send a message to any CogOS channel by name. For writing to arbitrary channels.",
      inputSchema: {
        type: "object" as const,
        properties: {
          channel: {
            type: "string",
            description: "Channel name (e.g. 'system:alerts', 'io:discord:dm')",
          },
          payload: {
            type: "object",
            description: "Message payload",
            additionalProperties: true,
          },
        },
        required: ["channel", "payload"],
      },
    },
    {
      name: "list_channels",
      description: "List available CogOS channels and their message counts.",
      inputSchema: {
        type: "object" as const,
        properties: {
          pattern: {
            type: "string",
            description:
              "Optional glob pattern to filter channels (e.g. 'io:*', 'system:*')",
          },
        },
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;

  if (name === "reply" || name === "send") {
    const channelNameOrId = (args as Record<string, unknown>).channel as string;
    const payload = (args as Record<string, unknown>).payload as Record<string, unknown>;

    // Resolve channel name to ID
    let channelId = channelIndex.get(channelNameOrId);
    if (!channelId) {
      // Maybe it's already an ID, or refresh the index
      await refreshChannelIndex();
      channelId = channelIndex.get(channelNameOrId) || channelNameOrId;
    }

    const result = await sendChannelMessage(channelId, payload);
    if (result.error) {
      return {
        content: [
          { type: "text" as const, text: `Error sending to ${channelNameOrId}: ${result.error}` },
        ],
      };
    }
    return {
      content: [
        {
          type: "text" as const,
          text: `Message sent to ${channelNameOrId} (id: ${result.id})`,
        },
      ],
    };
  }

  if (name === "list_channels") {
    const pattern = ((args as Record<string, unknown>)?.pattern as string) || "*";
    const channels = await fetchChannels();
    const filtered = channels.filter((ch) => matchesPattern(ch.name, pattern));
    const lines = filtered.map(
      (ch) => `${ch.name} (${ch.channel_type}, ${ch.message_count} msgs)`,
    );
    return {
      content: [
        {
          type: "text" as const,
          text: lines.length > 0 ? lines.join("\n") : "No channels found",
        },
      ],
    };
  }

  return {
    content: [{ type: "text" as const, text: `Unknown tool: ${name}` }],
  };
});

// ---------------------------------------------------------------------------
// Polling loop: watch CogOS channels and emit notifications
// ---------------------------------------------------------------------------

async function refreshChannelIndex(): Promise<void> {
  const channels = await fetchChannels();
  for (const ch of channels) {
    channelIndex.set(ch.name, ch.id);
  }
}

async function pollOnce(): Promise<void> {
  const channels = await fetchChannels();

  for (const ch of channels) {
    if (!matchesAnyPattern(ch.name)) continue;

    channelIndex.set(ch.name, ch.id);

    const messages = await fetchChannelMessages(ch.id, 20);
    for (const msg of messages) {
      if (seenMessages.has(msg.id)) continue;
      seenMessages.add(msg.id);

      // Emit channel notification to Claude Code
      try {
        await server.notification({
          method: "notifications/claude/channel",
          params: {
            channel: ch.name,
            content: JSON.stringify(msg.payload, null, 2),
            meta: {
              message_id: msg.id,
              channel_id: ch.id,
              channel_name: ch.name,
              sender_process: msg.sender_process,
              sender_process_name: msg.sender_process_name || undefined,
              created_at: msg.created_at,
            },
          },
        });
      } catch {
        // Connection may not be ready yet during startup
      }
    }
  }

  // Prune seen set to prevent unbounded growth
  if (seenMessages.size > 10000) {
    const arr = Array.from(seenMessages);
    for (let i = 0; i < arr.length - 5000; i++) {
      seenMessages.delete(arr[i]);
    }
  }
}

async function startPolling(): Promise<void> {
  // Initial index build — mark all existing messages as seen so we only
  // forward *new* messages arriving after the channel server starts.
  const channels = await fetchChannels();
  for (const ch of channels) {
    if (!matchesAnyPattern(ch.name)) continue;
    channelIndex.set(ch.name, ch.id);
    const messages = await fetchChannelMessages(ch.id, 100);
    for (const msg of messages) {
      seenMessages.add(msg.id);
    }
  }

  // Poll loop
  setInterval(async () => {
    try {
      await pollOnce();
    } catch {
      // Swallow polling errors — will retry on next interval
    }
  }, POLL_MS);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Start polling after MCP connection is established
  startPolling();
}

main().catch((err) => {
  process.stderr.write(`cogos-channels: fatal error: ${err}\n`);
  process.exit(1);
});
