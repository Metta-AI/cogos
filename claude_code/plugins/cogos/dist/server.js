/**
 * CogOS Claude Code Plugin — Thin MCP Proxy Server
 *
 * Connects to a remote CogOS API and proxies the cogent's memory,
 * capabilities, and channels as MCP tools. Makes the Claude Code
 * session *be* the cogent.
 *
 * Starts with a single `connect` tool. After connecting, expands to
 * load_memory, search_capabilities, channels, and dynamically
 * discovered capability tools.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema, } from "@modelcontextprotocol/sdk/types.js";
import { createServer } from "http";
import { exec } from "child_process";
import { getCachedToken, cacheToken } from "./token-cache.js";
// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
    address: "",
    apiUrl: "",
    cogentName: "",
    token: "",
    connected: false,
};
let capabilityTools = [];
const seenMessages = new Set();
const channelIndex = new Map();
let currentRunId = null;
let pollInterval = null;
let heartbeatInterval = null;
// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------
function headers() {
    const h = { "Content-Type": "application/json" };
    if (state.token) {
        h["Authorization"] = `Bearer ${state.token}`;
        h["x-api-key"] = state.token;
    }
    return h;
}
function apiBase() {
    return `${state.apiUrl}/api/cogents/${state.cogentName}`;
}
function capApiBase() {
    return `${state.apiUrl}/api/v1`;
}
function capHeaders() {
    const h = headers();
    // Capability proxy doesn't need process context for search
    return h;
}
async function apiGet(url) {
    const resp = await fetch(url, { headers: headers() });
    if (!resp.ok)
        throw new Error(`GET ${url}: ${resp.status} ${resp.statusText}`);
    return resp.json();
}
async function apiPost(url, body) {
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
function openBrowser(url) {
    const cmd = process.platform === "darwin"
        ? `open "${url}"`
        : process.platform === "win32"
            ? `start "${url}"`
            : `xdg-open "${url}"`;
    exec(cmd, (err) => {
        if (err)
            process.stderr.write(`[cogos] failed to open browser: ${err}\n`);
    });
}
async function browserAuthFlow(address) {
    return new Promise((resolve, reject) => {
        const httpServer = createServer((req, res) => {
            const url = new URL(req.url || "/", `http://localhost`);
            if (url.pathname === "/callback") {
                const token = url.searchParams.get("token");
                if (token) {
                    res.writeHead(200, { "Content-Type": "text/html" });
                    res.end("<html><body><h2>Token received! You can close this tab.</h2></body></html>");
                    httpServer.close();
                    resolve(token);
                }
                else {
                    res.writeHead(400, { "Content-Type": "text/plain" });
                    res.end("Missing token parameter");
                }
            }
            else {
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
        // Timeout after 5 minutes
        setTimeout(() => {
            httpServer.close();
            reject(new Error("Auth flow timed out after 5 minutes"));
        }, 5 * 60 * 1000);
    });
}
// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------
function parseAddress(address) {
    // Format: cogent-name.domain.com or https://domain.com/cogent-name
    // Simple case: name.host — cogent is the first segment
    const parts = address.split(".");
    if (parts.length >= 2) {
        const cogentName = parts[0];
        const domain = parts.slice(1).join(".");
        return {
            apiUrl: `https://${domain}`,
            cogentName,
        };
    }
    // Fallback: treat as local
    return {
        apiUrl: `http://localhost:8100`,
        cogentName: address,
    };
}
async function connect(address, token) {
    const { apiUrl, cogentName } = parseAddress(address);
    state.address = address;
    state.apiUrl = apiUrl;
    state.cogentName = cogentName;
    // Resolve token
    if (token) {
        state.token = token;
    }
    else {
        const cached = getCachedToken(address);
        if (cached) {
            state.token = cached;
            process.stderr.write(`[cogos] Using cached token for ${address}\n`);
        }
        else {
            // Browser auth flow
            try {
                state.token = await browserAuthFlow(address);
                cacheToken(address, state.token, cogentName);
                process.stderr.write(`[cogos] Token acquired and cached for ${address}\n`);
            }
            catch (e) {
                return `Auth failed: ${e}. You can retry with a token: connect("${address}", "your-token")`;
            }
        }
    }
    // Validate connection
    try {
        await apiGet(`${apiBase()}/channels`);
    }
    catch (e) {
        state.connected = false;
        return `Failed to connect to ${address}: ${e}`;
    }
    state.connected = true;
    // Cache token if provided directly
    if (token) {
        cacheToken(address, token, cogentName);
    }
    // Start polling and heartbeat
    startPolling();
    return `Connected to cogent "${cogentName}" at ${apiUrl}. Use load_memory to get the cogent's instructions, and search_capabilities to discover available tools.`;
}
// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------
async function loadMemory() {
    try {
        const data = (await apiGet(`${apiBase()}/memory/rendered`));
        return data.prompt || "(no memory found)";
    }
    catch (e) {
        return `Error loading memory: ${e}`;
    }
}
// ---------------------------------------------------------------------------
// Capabilities
// ---------------------------------------------------------------------------
async function searchCapabilities(query) {
    const tools = [];
    try {
        const data = (await apiGet(`${capApiBase()}/capabilities`));
        const capabilities = data.capabilities || [];
        // Filter by query (case-insensitive substring match)
        const q = query.toLowerCase();
        const matched = capabilities.filter((c) => c.name.toLowerCase().includes(q) ||
            c.description.toLowerCase().includes(q));
        for (const cap of matched) {
            try {
                const methods = (await apiGet(`${capApiBase()}/capabilities/${cap.name}/methods`));
                for (const method of methods) {
                    tools.push({
                        name: `cogos_${cap.name}_${method.name}`,
                        description: `${cap.name}.${method.name}: ${method.docstring}`,
                        inputSchema: {
                            type: "object",
                            properties: Object.fromEntries(method.params.map((p) => [
                                p.name,
                                { type: pythonTypeToJsonSchema(p.type) },
                            ])),
                            required: method.params
                                .filter((p) => p.required)
                                .map((p) => p.name),
                        },
                        capName: cap.name,
                        methodName: method.name,
                    });
                }
            }
            catch {
                // Skip capabilities that fail to load methods
            }
        }
    }
    catch (e) {
        return { tools: [], summary: `Error searching capabilities: ${e}` };
    }
    // Register discovered tools
    capabilityTools = [...capabilityTools, ...tools];
    // Deduplicate by name
    const seen = new Set();
    capabilityTools = capabilityTools.filter((t) => {
        if (seen.has(t.name))
            return false;
        seen.add(t.name);
        return true;
    });
    const names = tools.map((t) => t.name).join("\n  ");
    return {
        tools,
        summary: tools.length > 0
            ? `Found ${tools.length} capability tools:\n  ${names}`
            : `No capabilities matched "${query}"`,
    };
}
async function invokeCapability(capName, methodName, args) {
    try {
        const resp = await fetch(`${capApiBase()}/capabilities/${capName}/${methodName}`, {
            method: "POST",
            headers: capHeaders(),
            body: JSON.stringify({ args }),
        });
        if (!resp.ok) {
            const err = (await resp.json().catch(() => ({})));
            return { error: err.detail || resp.statusText };
        }
        return (await resp.json());
    }
    catch (e) {
        return { error: String(e) };
    }
}
function pythonTypeToJsonSchema(pyType) {
    switch (pyType) {
        case "str":
            return "string";
        case "int":
            return "integer";
        case "float":
            return "number";
        case "bool":
            return "boolean";
        default:
            return "string";
    }
}
// ---------------------------------------------------------------------------
// Channels
// ---------------------------------------------------------------------------
async function fetchChannels() {
    try {
        const data = (await apiGet(`${apiBase()}/channels`));
        return data.channels || [];
    }
    catch {
        return [];
    }
}
async function fetchMessages(channelId, limit = 20) {
    try {
        const data = (await apiGet(`${apiBase()}/channels/${channelId}?limit=${limit}`));
        return (data.messages || []);
    }
    catch {
        return [];
    }
}
async function sendMessage(channelNameOrId, payload) {
    let channelId = channelIndex.get(channelNameOrId);
    if (!channelId) {
        await refreshChannelIndex();
        channelId = channelIndex.get(channelNameOrId) || channelNameOrId;
    }
    try {
        const data = (await apiPost(`${apiBase()}/channels/${channelId}/messages`, { payload }));
        return data;
    }
    catch (e) {
        return { error: String(e) };
    }
}
async function refreshChannelIndex() {
    const channels = await fetchChannels();
    for (const ch of channels) {
        channelIndex.set(ch.name, ch.id);
    }
}
async function completeRun(status, output, error) {
    if (!currentRunId)
        return { ok: false, error: "no active run" };
    const runId = currentRunId;
    try {
        const data = (await apiPost(`${apiBase()}/runs/${runId}/complete`, {
            status,
            output: output || null,
            error: error || null,
        }));
        currentRunId = null;
        return data;
    }
    catch (e) {
        return { ok: false, error: String(e) };
    }
}
// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------
function matchesPattern(name, pattern) {
    const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp("^" + escaped.replace(/\*/g, ".*") + "$");
    return regex.test(name);
}
async function pollOnce() {
    if (!state.connected)
        return;
    const channels = await fetchChannels();
    for (const ch of channels) {
        channelIndex.set(ch.name, ch.id);
        const messages = await fetchMessages(ch.id, 20);
        for (const msg of messages) {
            if (seenMessages.has(msg.id))
                continue;
            seenMessages.add(msg.id);
            // Track run assignments
            const payloadRunId = msg.payload
                ?.run_id;
            if (payloadRunId)
                currentRunId = payloadRunId;
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
            }
            catch {
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
async function seedSeen() {
    const channels = await fetchChannels();
    for (const ch of channels) {
        channelIndex.set(ch.name, ch.id);
        const messages = await fetchMessages(ch.id, 100);
        for (const msg of messages) {
            seenMessages.add(msg.id);
        }
    }
}
function startPolling() {
    if (pollInterval)
        clearInterval(pollInterval);
    if (heartbeatInterval)
        clearInterval(heartbeatInterval);
    // Seed seen messages then start
    seedSeen().then(() => {
        pollInterval = setInterval(async () => {
            try {
                await pollOnce();
            }
            catch {
                // Swallow
            }
        }, 3000);
    });
    // Heartbeat (lightweight — just for presence, no executor registration)
    heartbeatInterval = setInterval(async () => {
        // No-op for now — we don't register as an executor in chat mode
    }, 15000);
}
// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------
const mcpServer = new Server({ name: "cogos", version: "1.0.0" }, {
    capabilities: {
        experimental: { "claude/channel": {} },
        tools: { listChanged: true },
    },
    instructions: "CogOS plugin. Use the `connect` tool to connect to a cogent (e.g. connect with address 'alpha.softmax-cogents.com'). " +
        "After connecting, use `load_memory` to get the cogent's full instructions.",
});
// ---------------------------------------------------------------------------
// Tool definitions
// ---------------------------------------------------------------------------
const CONNECT_TOOL = {
    name: "connect",
    description: "Connect to a CogOS cogent. Provide the cogent address (e.g. 'alpha.softmax-cogents.com'). " +
        "If no token is cached, opens a browser for authentication.",
    inputSchema: {
        type: "object",
        properties: {
            address: {
                type: "string",
                description: "Cogent address (e.g. 'alpha.softmax-cogents.com' or just 'alpha' for localhost)",
            },
            token: {
                type: "string",
                description: "Optional API token (skips browser auth if provided)",
            },
        },
        required: ["address"],
    },
};
const CONNECTED_TOOLS = [
    {
        name: "load_memory",
        description: "Load the cogent's full memory/instructions. Call this after connecting to get the cogent's system prompt and context.",
        inputSchema: {
            type: "object",
            properties: {},
        },
    },
    {
        name: "search_capabilities",
        description: "Search for available cogent capabilities by keyword. Matched capabilities become available as individual tools (cogos_<cap>_<method>). Examples: 'file', 'discord', 'channels'.",
        inputSchema: {
            type: "object",
            properties: {
                query: {
                    type: "string",
                    description: "Search keyword to filter capabilities",
                },
            },
            required: ["query"],
        },
    },
    {
        name: "list_channels",
        description: "List available CogOS channels and their message counts.",
        inputSchema: {
            type: "object",
            properties: {
                pattern: {
                    type: "string",
                    description: "Optional glob pattern to filter (e.g. 'io:*')",
                },
            },
        },
    },
    {
        name: "send",
        description: "Send a message to a CogOS channel by name.",
        inputSchema: {
            type: "object",
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
    },
    {
        name: "reply",
        description: "Reply to a CogOS channel event.",
        inputSchema: {
            type: "object",
            properties: {
                channel: {
                    type: "string",
                    description: "Channel name or ID",
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
        name: "complete_run",
        description: "Signal that the current executor run is complete. Call when you finish an assigned task.",
        inputSchema: {
            type: "object",
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
    },
];
// ---------------------------------------------------------------------------
// Tool handlers
// ---------------------------------------------------------------------------
mcpServer.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
        CONNECT_TOOL,
        ...(state.connected ? CONNECTED_TOOLS : []),
        ...capabilityTools.map((ct) => ({
            name: ct.name,
            description: ct.description,
            inputSchema: ct.inputSchema,
        })),
    ],
}));
mcpServer.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;
    const a = (args || {});
    // --- connect ---
    if (name === "connect") {
        const result = await connect(a.address, a.token);
        // Notify tool list changed after connect
        if (state.connected) {
            try {
                await mcpServer.notification({
                    method: "notifications/tools/list_changed",
                });
            }
            catch {
                // May not be ready
            }
        }
        return { content: [{ type: "text", text: result }] };
    }
    // --- Guard: must be connected ---
    if (!state.connected) {
        return {
            content: [
                {
                    type: "text",
                    text: 'Not connected. Use the `connect` tool first.',
                },
            ],
        };
    }
    // --- load_memory ---
    if (name === "load_memory") {
        const memory = await loadMemory();
        return { content: [{ type: "text", text: memory }] };
    }
    // --- search_capabilities ---
    if (name === "search_capabilities") {
        const { summary } = await searchCapabilities(a.query);
        // Notify tool list changed after capability discovery
        try {
            await mcpServer.notification({
                method: "notifications/tools/list_changed",
            });
        }
        catch {
            // May not be ready
        }
        return { content: [{ type: "text", text: summary }] };
    }
    // --- list_channels ---
    if (name === "list_channels") {
        const pattern = a.pattern || "*";
        const channels = await fetchChannels();
        const filtered = channels.filter((ch) => matchesPattern(ch.name, pattern));
        const lines = filtered.map((ch) => `${ch.name} (${ch.channel_type}, ${ch.message_count} msgs)`);
        return {
            content: [
                {
                    type: "text",
                    text: lines.length > 0 ? lines.join("\n") : "No channels found",
                },
            ],
        };
    }
    // --- send / reply ---
    if (name === "send" || name === "reply") {
        const result = await sendMessage(a.channel, a.payload);
        if (result.error) {
            return {
                content: [
                    {
                        type: "text",
                        text: `Error: ${result.error}`,
                    },
                ],
            };
        }
        return {
            content: [
                {
                    type: "text",
                    text: `Sent to ${a.channel} (id: ${result.id})`,
                },
            ],
        };
    }
    // --- complete_run ---
    if (name === "complete_run") {
        const status = a.status;
        const summary = a.summary;
        const error = a.error;
        const output = summary ? { summary } : undefined;
        const result = await completeRun(status, output, error);
        if (result.ok) {
            return {
                content: [
                    {
                        type: "text",
                        text: `Run completed with status: ${status}`,
                    },
                ],
            };
        }
        return {
            content: [
                {
                    type: "text",
                    text: `Error: ${result.error || "failed"}`,
                },
            ],
        };
    }
    // --- Dynamic capability tools (cogos_<cap>_<method>) ---
    if (name.startsWith("cogos_")) {
        const tool = capabilityTools.find((t) => t.name === name);
        if (!tool) {
            return {
                content: [
                    { type: "text", text: `Unknown capability tool: ${name}` },
                ],
            };
        }
        const result = await invokeCapability(tool.capName, tool.methodName, a);
        if (result.error) {
            return {
                content: [
                    {
                        type: "text",
                        text: `Error: ${result.error}`,
                    },
                ],
            };
        }
        return {
            content: [
                {
                    type: "text",
                    text: typeof result.result === "string"
                        ? result.result
                        : JSON.stringify(result.result, null, 2),
                },
            ],
        };
    }
    return {
        content: [{ type: "text", text: `Unknown tool: ${name}` }],
    };
});
// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main() {
    const transport = new StdioServerTransport();
    await mcpServer.connect(transport);
    process.stderr.write("[cogos] CogOS plugin started. Waiting for connect...\n");
}
main().catch((err) => {
    process.stderr.write(`[cogos] Fatal error: ${err}\n`);
    process.exit(1);
});
