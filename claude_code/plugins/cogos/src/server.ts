/**
 * CogOS Claude Code Plugin — Thin MCP Proxy
 *
 * Connects to a remote CogOS FastAPI server's /mcp endpoint (powered by
 * fastapi-mcp) and proxies the auto-generated tools to Claude Code.
 *
 * Local responsibilities: auth, discovery, channel polling, executor lifecycle.
 * Remote responsibilities: all tool definitions and execution (via fastapi-mcp).
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { createServer } from "http";
import { exec } from "child_process";
import {
  getCachedToken,
  cacheToken,
  removeCachedToken,
} from "./token-cache.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RemoteTool {
  name: string;
  description?: string;
  inputSchema: {
    type: "object";
    properties?: Record<string, object>;
    required?: string[];
    [key: string]: unknown;
  };
}

interface ConnectionState {
  address: string;
  apiUrl: string;
  cogentName: string;
  token: string;
  connected: boolean;
  isExecutor: boolean;
  executorId: string;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state: ConnectionState = {
  address: "",
  apiUrl: "",
  cogentName: "",
  token: "",
  connected: false,
  isExecutor: false,
  executorId: "",
};

let remoteClient: Client | null = null;
let remoteTransport: StreamableHTTPClientTransport | null = null;
let remoteTools: RemoteTool[] = [];
const seenMessages = new Set<string>();
const channelIndex = new Map<string, string>();
let currentRunId: string | null = null;
let pollInterval: ReturnType<typeof setInterval> | null = null;
let heartbeatInterval: ReturnType<typeof setInterval> | null = null;

// ---------------------------------------------------------------------------
// HTTP helpers (for channel polling and executor lifecycle — not proxied)
// ---------------------------------------------------------------------------

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (state.token) {
    h["Authorization"] = `Bearer ${state.token}`;
    h["x-api-key"] = state.token;
  }
  return h;
}

function apiBase(): string {
  return `${state.apiUrl}/api/cogents/${state.cogentName}`;
}

async function apiGet(url: string): Promise<unknown> {
  try {
    const resp = await fetch(url, { headers: headers() });
    if (!resp.ok) throw new Error(`GET ${url}: ${resp.status} ${resp.statusText}`);
    return resp.json();
  } catch (e: any) {
    const cause = e?.cause ? ` cause=${e.cause?.code || e.cause?.message || JSON.stringify(e.cause)}` : "";
    throw new Error(`GET ${url}: ${e?.message}${cause}`);
  }
}

async function apiPost(url: string, body: unknown): Promise<unknown> {
  const resp = await fetch(url, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!resp.ok)
    throw new Error(`POST ${url}: ${resp.status} ${resp.statusText}`);
  return resp.json();
}

// ---------------------------------------------------------------------------
// Token auth — browser-based flow
// ---------------------------------------------------------------------------

function openBrowser(url: string): void {
  const cmd =
    process.platform === "darwin"
      ? `open "${url}"`
      : process.platform === "win32"
        ? `start "${url}"`
        : `xdg-open "${url}"`;
  exec(cmd, (err) => {
    if (err) process.stderr.write(`[cogos] failed to open browser: ${err}\n`);
  });
}

async function browserAuthFlow(address: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const httpServer = createServer((req, res) => {
      const url = new URL(req.url || "/", `http://localhost`);
      if (url.pathname === "/callback") {
        const token = url.searchParams.get("token");
        if (token) {
          res.writeHead(200, { "Content-Type": "text/html" });
          res.end(
            "<html><body><h2>Token received! You can close this tab.</h2></body></html>",
          );
          httpServer.close();
          resolve(token);
        } else {
          res.writeHead(400, { "Content-Type": "text/plain" });
          res.end("Missing token parameter");
        }
      } else {
        res.writeHead(404);
        res.end();
      }
    });

    httpServer.listen(0, "127.0.0.1", () => {
      const addr = httpServer.address();
      if (!addr || typeof addr === "string") {
        reject(new Error("Failed to start callback server"));
        return;
      }
      const callbackUrl = `http://127.0.0.1:${addr.port}/callback`;
      const authUrl = `https://${address}/token-auth?callback=${encodeURIComponent(callbackUrl)}`;
      process.stderr.write(`[cogos] Opening browser for auth: ${authUrl}\n`);
      openBrowser(authUrl);
    });

    setTimeout(() => {
      httpServer.close();
      reject(new Error("Auth flow timed out after 5 minutes"));
    }, 5 * 60 * 1000);
  });
}

// ---------------------------------------------------------------------------
// Address parsing
// ---------------------------------------------------------------------------

function parseAddress(address: string): { apiUrl: string; cogentName: string } {
  const parts = address.split(".");
  if (parts.length >= 2) {
    const cogentName = parts[0];
    return { apiUrl: `https://${address}`, cogentName };
  }
  return { apiUrl: `http://localhost:8100`, cogentName: address };
}

// ---------------------------------------------------------------------------
// Remote MCP client — connects to CogOS fastapi-mcp at /api/mcp
// ---------------------------------------------------------------------------

async function connectRemoteMcp(): Promise<void> {
  const mcpUrl = new URL(`${state.apiUrl}/api/mcp`);

  remoteTransport = new StreamableHTTPClientTransport(mcpUrl, {
    requestInit: { headers: headers() },
  });

  remoteClient = new Client(
    { name: "cogos-proxy", version: "1.0.0" },
    { capabilities: {} },
  );

  await remoteClient.connect(remoteTransport);
  process.stderr.write(`[cogos] Connected to remote MCP at ${mcpUrl}\n`);

  // Fetch remote tools
  await refreshRemoteTools();
}

async function refreshRemoteTools(): Promise<void> {
  if (!remoteClient) return;
  try {
    const result = await remoteClient.listTools();
    remoteTools = (result.tools || []) as RemoteTool[];
    process.stderr.write(
      `[cogos] Loaded ${remoteTools.length} remote tools\n`,
    );
  } catch (e) {
    process.stderr.write(`[cogos] Failed to list remote tools: ${e}\n`);
    remoteTools = [];
  }
}

async function disconnectRemoteMcp(): Promise<void> {
  if (remoteTransport) {
    try {
      await remoteTransport.close();
    } catch {
      // ignore
    }
    remoteTransport = null;
  }
  remoteClient = null;
  remoteTools = [];
}

// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------

async function connect(address: string, token?: string): Promise<string> {
  // Disconnect existing connection first
  await disconnect();

  const { apiUrl, cogentName } = parseAddress(address);
  state.address = address;
  state.apiUrl = apiUrl;
  state.cogentName = cogentName;

  // Resolve token
  if (token) {
    state.token = token;
  } else {
    const cached = getCachedToken(address);
    if (cached) {
      state.token = cached;
      process.stderr.write(`[cogos] Using cached token for ${address}\n`);
      try {
        await apiGet(`${apiBase()}/cogos-status`);
      } catch (e) {
        process.stderr.write(`[cogos] Cached token invalid, re-authenticating: ${e}\n`);
        removeCachedToken(address);
        state.token = "";
      }
    }

    if (!state.token) {
      try {
        state.token = await browserAuthFlow(address);
        cacheToken(address, state.token, cogentName);
        process.stderr.write(
          `[cogos] Token acquired and cached for ${address}\n`,
        );
      } catch (e) {
        return `Auth failed: ${e}. You can retry with a token: connect("${address}", "your-token")`;
      }
    }
  }

  // Validate connection
  try {
    await apiGet(`${apiBase()}/cogos-status`);
  } catch (e) {
    state.connected = false;
    removeCachedToken(address);
    state.token = "";
    return `Failed to connect to ${address}: ${e}`;
  }

  // Cache token if provided directly
  if (token) {
    cacheToken(address, token, cogentName);
  }

  // Connect to remote MCP
  try {
    await connectRemoteMcp();
  } catch (e) {
    process.stderr.write(
      `[cogos] Warning: remote MCP connection failed: ${e}. Falling back to direct API.\n`,
    );
  }

  state.connected = true;

  // Start channel polling
  startPolling();

  // Notify tool list changed
  try {
    await mcpServer.notification({
      method: "notifications/tools/list_changed",
    });
  } catch {
    // May not be ready
  }

  return `Connected to cogent "${cogentName}" at ${apiUrl}. ${remoteTools.length} tools available. Use load_memory to get the cogent's instructions.`;
}

async function disconnect(): Promise<string> {
  // Stop polling
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
  if (heartbeatInterval) {
    clearInterval(heartbeatInterval);
    heartbeatInterval = null;
  }

  // Disconnect remote MCP
  await disconnectRemoteMcp();

  // Clear state
  const wasConnected = state.connected;
  const oldCogent = state.cogentName;
  state.address = "";
  state.apiUrl = "";
  state.cogentName = "";
  state.token = "";
  state.connected = false;
  state.isExecutor = false;
  state.executorId = "";
  currentRunId = null;
  seenMessages.clear();
  channelIndex.clear();

  // Notify tool list changed
  try {
    await mcpServer.notification({
      method: "notifications/tools/list_changed",
    });
  } catch {
    // May not be ready
  }

  return wasConnected
    ? `Disconnected from cogent "${oldCogent}". Use connect to connect to another cogent.`
    : "Not connected.";
}

// ---------------------------------------------------------------------------
// Executor lifecycle
// ---------------------------------------------------------------------------

async function registerExecutor(): Promise<string> {
  if (!state.connected)
    return "Not connected. Use connect first.";
  if (state.isExecutor)
    return `Already registered as executor ${state.executorId}`;

  const executorId = `cc-${process.env.HOSTNAME || "local"}-${Math.random().toString(36).slice(2, 10)}`;

  try {
    const data = (await apiPost(`${apiBase()}/executors/register`, {
      executor_id: executorId,
      channel_type: "claude-code",
      executor_tags: ["claude-code"],
      dispatch_type: "channel",
      metadata: { mcp: true, hostname: process.env.HOSTNAME || "local" },
    })) as { channel?: string };

    state.isExecutor = true;
    state.executorId = executorId;

    // Subscribe to executor's dedicated channel if provided
    const executorChannel = data.channel;
    if (executorChannel) {
      process.stderr.write(
        `[cogos] Subscribed to executor channel: ${executorChannel}\n`,
      );
    }

    // Start heartbeat
    heartbeatInterval = setInterval(async () => {
      try {
        await apiPost(
          `${apiBase()}/executors/${state.executorId}/heartbeat`,
          {
            status: currentRunId ? "busy" : "idle",
            current_run_id: currentRunId,
          },
        );
      } catch {
        // Heartbeat failure is non-fatal
      }
    }, 15000);

    // Notify tool list changed (executor tools now available)
    try {
      await mcpServer.notification({
        method: "notifications/tools/list_changed",
      });
    } catch {
      // May not be ready
    }

    return `Registered as executor ${executorId}. Heartbeat active. Channel notifications enabled.`;
  } catch (e) {
    return `Failed to register executor: ${e}`;
  }
}

async function completeRun(
  status: string,
  output?: Record<string, unknown>,
  error?: string,
): Promise<{ ok?: boolean; error?: string }> {
  if (!currentRunId) return { ok: false, error: "no active run" };
  const runId = currentRunId;
  try {
    const data = (await apiPost(`${apiBase()}/runs/${runId}/complete`, {
      executor_id: state.executorId,
      status,
      output: output || null,
      error: error || null,
    })) as { ok: boolean };
    currentRunId = null;
    return data;
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// ---------------------------------------------------------------------------
// Channel polling
// ---------------------------------------------------------------------------

async function fetchChannels(): Promise<
  Array<{
    id: string;
    name: string;
    channel_type: string;
    message_count: number;
  }>
> {
  try {
    const data = (await apiGet(`${apiBase()}/channels`)) as {
      channels: Array<{
        id: string;
        name: string;
        channel_type: string;
        message_count: number;
      }>;
    };
    return data.channels || [];
  } catch {
    return [];
  }
}

async function fetchMessages(
  channelId: string,
  limit: number = 20,
): Promise<
  Array<{
    id: string;
    payload: Record<string, unknown>;
    sender_process?: string;
    sender_process_name?: string;
    created_at?: string;
  }>
> {
  try {
    const data = (await apiGet(
      `${apiBase()}/channels/${channelId}?limit=${limit}`,
    )) as { messages: Array<Record<string, unknown>> };
    return (data.messages || []) as Array<{
      id: string;
      payload: Record<string, unknown>;
      sender_process?: string;
      sender_process_name?: string;
      created_at?: string;
    }>;
  } catch {
    return [];
  }
}

async function pollOnce(): Promise<void> {
  if (!state.connected) return;

  const channels = await fetchChannels();
  for (const ch of channels) {
    channelIndex.set(ch.name, ch.id);
    const messages = await fetchMessages(ch.id, 20);

    for (const msg of messages) {
      if (seenMessages.has(msg.id)) continue;
      seenMessages.add(msg.id);

      // Track run assignments
      const payloadRunId = (msg.payload as Record<string, unknown>)
        ?.run_id as string | undefined;
      if (payloadRunId) currentRunId = payloadRunId;

      try {
        await mcpServer.notification({
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
        // Connection may not be ready
      }
    }
  }

  // Prune seen set
  if (seenMessages.size > 10000) {
    const arr = Array.from(seenMessages);
    for (let i = 0; i < arr.length - 5000; i++) {
      seenMessages.delete(arr[i]);
    }
  }
}

async function seedSeen(): Promise<void> {
  const channels = await fetchChannels();
  for (const ch of channels) {
    channelIndex.set(ch.name, ch.id);
    const messages = await fetchMessages(ch.id, 100);
    for (const msg of messages) {
      seenMessages.add(msg.id);
    }
  }
}

function startPolling(): void {
  if (pollInterval) clearInterval(pollInterval);

  seedSeen().then(() => {
    pollInterval = setInterval(async () => {
      try {
        await pollOnce();
      } catch {
        // Swallow
      }
    }, 3000);
  });
}

// ---------------------------------------------------------------------------
// Channel send helper (for local send/reply tools)
// ---------------------------------------------------------------------------

async function sendMessage(
  channelNameOrId: string,
  payload: Record<string, unknown>,
): Promise<{ id?: string; error?: string }> {
  let channelId = channelIndex.get(channelNameOrId);
  if (!channelId) {
    const channels = await fetchChannels();
    for (const ch of channels) {
      channelIndex.set(ch.name, ch.id);
    }
    channelId = channelIndex.get(channelNameOrId) || channelNameOrId;
  }

  try {
    const data = (await apiPost(
      `${apiBase()}/channels/${channelId}/messages`,
      { payload },
    )) as { id: string };
    return data;
  } catch (e) {
    return { error: String(e) };
  }
}

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

const mcpServer = new Server(
  { name: "cogos", version: "2.0.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
      tools: { listChanged: true },
    },
    instructions:
      "CogOS plugin. Use the `connect` tool to connect to a cogent (e.g. connect with address 'alpha.softmax-cogents.com'). " +
      "After connecting, use `load_memory` (a remote tool) to get the cogent's full instructions. " +
      "Use `disconnect` to switch to a different cogent without restarting.",
  },
);

// ---------------------------------------------------------------------------
// Local tool definitions
// ---------------------------------------------------------------------------

const CONNECT_TOOL = {
  name: "connect",
  description:
    "Connect to a CogOS cogent. Provide the cogent address (e.g. 'alpha.softmax-cogents.com'). " +
    "If no token is cached, opens a browser for authentication.",
  inputSchema: {
    type: "object" as const,
    properties: {
      address: {
        type: "string",
        description:
          "Cogent address (e.g. 'alpha.softmax-cogents.com' or just 'alpha' for localhost)",
      },
      token: {
        type: "string",
        description: "Optional API token (skips browser auth if provided)",
      },
    },
    required: ["address"],
  },
};

const DISCONNECT_TOOL = {
  name: "disconnect",
  description:
    "Disconnect from the current cogent. Use this to switch to a different cogent without restarting Claude Code.",
  inputSchema: {
    type: "object" as const,
    properties: {},
  },
};

const REGISTER_EXECUTOR_TOOL = {
  name: "register_executor",
  description:
    "Register as an executor for the connected cogent. Enables heartbeat, channel notifications, and run assignments.",
  inputSchema: {
    type: "object" as const,
    properties: {},
  },
};

const COMPLETE_RUN_TOOL = {
  name: "complete_run",
  description:
    "Signal that the current executor run is complete. Call when you finish an assigned task.",
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
        description: "Brief summary of what was done",
      },
      error: {
        type: "string",
        description: "Error message if failed",
      },
    },
    required: ["status"],
  },
};

const SEND_TOOL = {
  name: "send",
  description: "Send a message to a CogOS channel by name.",
  inputSchema: {
    type: "object" as const,
    properties: {
      channel: {
        type: "string",
        description: "Channel name (e.g. 'io:discord:dm')",
      },
      payload: {
        type: "object",
        description: "Message payload",
        additionalProperties: true,
      },
    },
    required: ["channel", "payload"],
  },
};

const LIST_CHANNELS_TOOL = {
  name: "list_channels",
  description: "List available CogOS channels and their message counts.",
  inputSchema: {
    type: "object" as const,
    properties: {
      pattern: {
        type: "string",
        description: "Optional glob pattern to filter (e.g. 'io:*')",
      },
    },
  },
};

// Set of local tool names for routing
const LOCAL_TOOL_NAMES = new Set([
  "connect",
  "disconnect",
  "register_executor",
  "complete_run",
  "send",
  "reply",
  "list_channels",
]);

// ---------------------------------------------------------------------------
// Tool handlers
// ---------------------------------------------------------------------------

mcpServer.setRequestHandler(ListToolsRequestSchema, async () => {
  const tools: Array<{
    name: string;
    description?: string;
    inputSchema: Record<string, unknown>;
  }> = [];

  // Always available
  tools.push(CONNECT_TOOL);

  if (state.connected) {
    tools.push(DISCONNECT_TOOL);
    tools.push(LIST_CHANNELS_TOOL);
    tools.push(SEND_TOOL);
    // "reply" is an alias for send
    tools.push({
      ...SEND_TOOL,
      name: "reply",
      description: "Reply to a CogOS channel event.",
    });

    // Executor tools
    if (!state.isExecutor) {
      tools.push(REGISTER_EXECUTOR_TOOL);
    } else {
      tools.push(COMPLETE_RUN_TOOL);
    }

    // Remote tools from fastapi-mcp
    for (const rt of remoteTools) {
      // Skip remote tools that collide with local tool names
      if (LOCAL_TOOL_NAMES.has(rt.name)) continue;
      tools.push({
        name: rt.name,
        description: rt.description,
        inputSchema: rt.inputSchema,
      });
    }
  }

  return { tools };
});

mcpServer.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  const a = (args || {}) as Record<string, unknown>;

  // --- connect ---
  if (name === "connect") {
    const result = await connect(
      a.address as string,
      a.token as string | undefined,
    );
    return { content: [{ type: "text" as const, text: result }] };
  }

  // --- disconnect ---
  if (name === "disconnect") {
    const result = await disconnect();
    return { content: [{ type: "text" as const, text: result }] };
  }

  // --- Guard: must be connected ---
  if (!state.connected) {
    return {
      content: [
        {
          type: "text" as const,
          text: "Not connected. Use the `connect` tool first.",
        },
      ],
    };
  }

  // --- register_executor ---
  if (name === "register_executor") {
    const result = await registerExecutor();
    return { content: [{ type: "text" as const, text: result }] };
  }

  // --- complete_run ---
  if (name === "complete_run") {
    const status = a.status as string;
    const summary = a.summary as string | undefined;
    const error = a.error as string | undefined;
    const output = summary ? { summary } : undefined;
    const result = await completeRun(status, output, error);
    if (result.ok) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Run completed with status: ${status}`,
          },
        ],
      };
    }
    return {
      content: [
        {
          type: "text" as const,
          text: `Error: ${result.error || "failed"}`,
        },
      ],
    };
  }

  // --- list_channels ---
  if (name === "list_channels") {
    const pattern = (a.pattern as string) || "*";
    const channels = await fetchChannels();
    const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp("^" + escaped.replace(/\*/g, ".*") + "$");
    const filtered = channels.filter((ch) => regex.test(ch.name));
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

  // --- send / reply ---
  if (name === "send" || name === "reply") {
    const result = await sendMessage(
      a.channel as string,
      a.payload as Record<string, unknown>,
    );
    if (result.error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${result.error}` }],
      };
    }
    return {
      content: [
        {
          type: "text" as const,
          text: `Sent to ${a.channel} (id: ${result.id})`,
        },
      ],
    };
  }

  // --- Remote tool proxy ---
  if (remoteClient) {
    try {
      const result = await remoteClient.callTool({ name, arguments: a });
      // Pass through the remote result directly
      if ("content" in result) {
        return {
          content: result.content as Array<{ type: "text"; text: string }>,
        };
      }
      // Fallback: serialize the result
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    } catch (e) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Remote tool error: ${e}`,
          },
        ],
      };
    }
  }

  return {
    content: [{ type: "text" as const, text: `Unknown tool: ${name}` }],
  };
});

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await mcpServer.connect(transport);
  process.stderr.write("[cogos] CogOS plugin v2 started. Waiting for connect...\n");
}

main().catch((err) => {
  process.stderr.write(`[cogos] Fatal error: ${err}\n`);
  process.exit(1);
});
