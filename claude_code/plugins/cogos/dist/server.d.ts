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
export {};
