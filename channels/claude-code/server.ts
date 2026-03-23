/**
 * Claude Code channel server for CogOS.
 *
 * Bridges CogOS channels into a running Claude Code session and registers
 * as a cogos executor:
 *   - Registers as an executor and heartbeats to stay alive
 *   - Creates a dedicated executor channel and subscribes to it
 *   - Polls the CogOS dashboard API for new messages on subscribed channels
 *   - Emits MCP channel notifications so Claude sees them as <channel> events
 *   - Exposes send, reply, list_channels, and complete_run tools
 *
 * Environment variables:
 *   COGOS_API_URL      – Dashboard API base URL (e.g. http://localhost:8100)
 *   COGENT             – Cogent name for API path prefix
 *   COGOS_API_KEY      – API key for authenticated access (executor token)
 *   COGOS_CHANNELS     – Comma-separated channel name patterns to subscribe to
 *                        (default: "io:claude-code:*")
 *   COGOS_POLL_MS      – Poll interval in milliseconds (default: 3000)
 *   COGOS_HEARTBEAT_S  – Heartbeat interval in seconds (default: 15)
 *   COGOS_EXECUTOR_ID  – Custom executor ID (auto-generated if omitted)
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { randomBytes } from "crypto";
import { hostname } from "os";
import { readFileSync, writeFileSync } from "fs";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_URL = process.env.COGOS_API_URL || "http://localhost:8100";
const COGENT_NAME = process.env.COGENT || "";
const API_KEY = process.env.COGOS_API_KEY || "";
const CHANNEL_PATTERNS = (
  process.env.COGOS_CHANNELS || "io:claude-code:*"
).split(",").map((s) => s.trim());
const POLL_MS = parseInt(process.env.COGOS_POLL_MS || "3000", 10);
const HEARTBEAT_S = parseInt(process.env.COGOS_HEARTBEAT_S || "15", 10);
const EXECUTOR_ID = (() => {
  if (process.env.COGOS_EXECUTOR_ID) return process.env.COGOS_EXECUTOR_ID;
  const cacheFile = ".cogos_executor";
  try {
    const cached = readFileSync(cacheFile, "utf-8").trim();
    if (cached) return cached;
  } catch {
    // file doesn't exist yet
  }
  const id = `cc-${hostname()}-${randomBytes(4).toString("hex")}`;
  try {
    writeFileSync(cacheFile, id + "\n");
  } catch {
    // non-fatal
  }
  return id;
})();

function apiBase(): string {
  if (COGENT_NAME) {
    return `${API_URL}/api/cogents/${COGENT_NAME}`;
  }
  return API_URL;
}

function hdrs(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) {
    h["x-api-key"] = API_KEY;
    h["Authorization"] = `Bearer ${API_KEY}`;
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
    const resp = await fetch(`${apiBase()}/channels`, { headers: hdrs() });
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
      { headers: hdrs() },
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
      headers: hdrs(),
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
// Executor lifecycle
// ---------------------------------------------------------------------------

let currentRunId: string | null = null;

async function registerExecutor(): Promise<string> {
  try {
    const resp = await fetch(`${apiBase()}/executors/register`, {
      method: "POST",
      headers: hdrs(),
      body: JSON.stringify({
        executor_id: EXECUTOR_ID,
        channel_type: "claude-code",
        capabilities: ["claude-code"],
        metadata: { mcp: true, hostname: hostname() },
      }),
    });
    if (!resp.ok) {
      process.stderr.write(`[cogos] register failed: ${resp.status} ${resp.statusText}\n`);
      return "";
    }
    const data = await resp.json();
    const channel = data.channel || "";
    if (channel) {
      CHANNEL_PATTERNS.push(channel);
      process.stderr.write(`[cogos] registered ${EXECUTOR_ID}, channel: ${channel}\n`);
    }
    return channel;
  } catch (e) {
    process.stderr.write(`[cogos] register error: ${e}\n`);
    return "";
  }
}

async function heartbeat(): Promise<void> {
  try {
    await fetch(`${apiBase()}/executors/${EXECUTOR_ID}/heartbeat`, {
      method: "POST",
      headers: hdrs(),
      body: JSON.stringify({
        status: currentRunId ? "busy" : "idle",
        current_run_id: currentRunId,
      }),
    });
  } catch {
    // swallow
  }
}

async function completeRun(
  status: string,
  output?: Record<string, unknown>,
  error?: string,
): Promise<Record<string, unknown>> {
  if (!currentRunId) return { ok: false, error: "no active run" };
  const runId = currentRunId;
  try {
    const resp = await fetch(`${apiBase()}/runs/${runId}/complete`, {
      method: "POST",
      headers: hdrs(),
      body: JSON.stringify({
        executor_id: EXECUTOR_ID,
        status,
        output: output || null,
        error: error || null,
      }),
    });
    if (!resp.ok) return { ok: false };
    currentRunId = null;
    return await resp.json();
  } catch {
    return { ok: false };
  }
}

// ---------------------------------------------------------------------------
// Channel name matching (fnmatch-style with * glob)
// ---------------------------------------------------------------------------

function matchesPattern(name: string, pattern: string): boolean {
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
  { name: "cogos", version: "0.1.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
      tools: {},
    },
    instructions:
      "You are connected to CogOS. Messages from the cogent arrive as <channel> events. " +
      "Use the reply tool to respond to channels. Use complete_run when you finish an assigned task.",
  },
);

// Track seen message IDs to avoid duplicate notifications
const seenMessages = new Set<string>();
// Cache channel name -> id mapping
const channelIndex = new Map<string, string>();

// ---------------------------------------------------------------------------
// Tools
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
    {
      name: "complete_run",
      description:
        "Signal that the current executor run is complete. Call this when you finish an assigned task.",
      inputSchema: {
        type: "object" as const,
        properties: {
          status: {
            type: "string",
            enum: ["completed", "failed"],
            description: "Run completion status",
          },
          summary: {
            type: "string",
            description: "Optional summary of what was accomplished",
          },
          error: {
            type: "string",
            description: "Optional error message if status is failed",
          },
        },
        required: ["status"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;

  if (name === "reply" || name === "send") {
    const channelNameOrId = (args as Record<string, unknown>).channel as string;
    const payload = (args as Record<string, unknown>).payload as Record<string, unknown>;

    let channelId = channelIndex.get(channelNameOrId);
    if (!channelId) {
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

  if (name === "complete_run") {
    const status = (args as Record<string, unknown>).status as string;
    const summary = (args as Record<string, unknown>).summary as string | undefined;
    const error = (args as Record<string, unknown>).error as string | undefined;
    const output = summary ? { summary } : undefined;
    const result = await completeRun(status, output, error);
    if (result.ok) {
      return {
        content: [{ type: "text" as const, text: `Run completed with status: ${status}` }],
      };
    }
    return {
      content: [{ type: "text" as const, text: `Error: ${result.error || "failed to complete run"}` }],
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

  // Heartbeat loop
  setInterval(async () => {
    try {
      await heartbeat();
    } catch {
      // swallow
    }
  }, HEARTBEAT_S * 1000);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Register executor and start polling after MCP connection is established
  await registerExecutor();
  startPolling();
}

main().catch((err) => {
  process.stderr.write(`cogos-channels: fatal error: ${err}\n`);
  process.exit(1);
});
