import type {
  CronItem,
  TimeRange,
  CogosStatus,
  CogosProcess,
  CogosProcessRun,
  CogosFile,
  CogosFileVersion,
  CogosCapability,
  CapabilityProcess,
  CogosHandler,
  CogosRun,
  CogosRunLogsResponse,
  CogosOperation,
  EventType,
  Resource,
  Alert,
  SetupResponse,
  MessageTrace,
  CogosChannel,
  ChannelSendResult,
  ProcessLogsResponse,
} from "./types";

interface MessageTraceFilters {
  messageTypes?: string[];
  emittedMessageTypes?: string[];
  categories?: string[];
  requestIds?: string[];
  limit?: number;
}

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("cogent-api-key");
}

function headers(): Record<string, string> {
  const key = getApiKey();
  return key ? { "x-api-key": key } : {};
}

function encodeFileKey(key: string): string {
  return encodeURIComponent(key);
}

async function fetchJSON<T>(path: string): Promise<T> {
  const resp = await fetch(path, { headers: headers() });
  if (resp.status === 401) throw new Error("unauthorized");
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

// ── Message Traces ──────────────────────────────────────────────────────────

export async function getMessageTraces(
  name: string,
  range: TimeRange = "1h",
  filters: MessageTraceFilters = {},
): Promise<MessageTrace[]> {
  const params = new URLSearchParams({ range });
  for (const value of filters.messageTypes ?? []) {
    params.append("message_type", value);
  }
  for (const value of filters.emittedMessageTypes ?? []) {
    params.append("emitted_message_type", value);
  }
  for (const value of filters.categories ?? []) {
    params.append("category", value);
  }
  for (const value of filters.requestIds ?? []) {
    params.append("request_id", value);
  }
  if (filters.limit != null) {
    params.set("limit", String(filters.limit));
  }
  const r = await fetchJSON<{ traces: MessageTrace[] }>(
    `/api/cogents/${name}/message-traces?${params.toString()}`,
  );
  return r.traces;
}

export async function getChannels(
  name: string,
  channelType?: string,
): Promise<CogosChannel[]> {
  const params = new URLSearchParams();
  if (channelType) {
    params.set("channel_type", channelType);
  }
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  const response = await fetchJSON<{ channels: CogosChannel[] }>(
    `/api/cogents/${name}/channels${suffix}`,
  );
  return response.channels;
}

export async function sendChannelMessage(
  name: string,
  channelId: string,
  payload: Record<string, unknown>,
): Promise<ChannelSendResult> {
  const resp = await fetch(
    `/api/cogents/${name}/channels/${encodeURIComponent(channelId)}/messages`,
    {
      method: "POST",
      headers: { "content-type": "application/json", ...headers() },
      body: JSON.stringify({ payload }),
    },
  );
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Preserve the default status message when the body is not JSON.
    }
    throw new Error(detail);
  }
  return resp.json();
}

// ── Cron ────────────────────────────────────────────────────────────────────

export async function getCrons(name: string): Promise<CronItem[]> {
  const r = await fetchJSON<{ crons: CronItem[] }>(
    `/api/cogents/${name}/cron`,
  );
  return r.crons;
}

export async function createCron(
  name: string,
  cron: { cron_expression: string; event_pattern: string; enabled?: boolean; metadata?: Record<string, unknown> },
): Promise<CronItem> {
  const resp = await fetch(`/api/cogents/${name}/cron`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(cron),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function updateCron(
  name: string,
  cronId: string,
  updates: { cron_expression?: string; event_pattern?: string; enabled?: boolean; metadata?: Record<string, unknown> },
): Promise<CronItem> {
  const resp = await fetch(`/api/cogents/${name}/cron/${cronId}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteCron(name: string, cronId: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/cron/${cronId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

export async function toggleCrons(
  name: string,
  ids: string[],
  enabled: boolean,
): Promise<void> {
  await fetch(`/api/cogents/${name}/cron/toggle`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ ids, enabled }),
  });
}

// ── CogOS API ───────────────────────────────────────────────────────────────

export async function getCogosStatus(name: string, epoch?: string): Promise<CogosStatus> {
  const params = epoch ? `?epoch=${epoch}` : "";
  return fetchJSON(`/api/cogents/${name}/cogos-status${params}`);
}

export async function getSetup(name: string): Promise<SetupResponse> {
  return fetchJSON(`/api/cogents/${name}/setup`);
}

export async function getProcesses(name: string, epoch?: string): Promise<CogosProcess[]> {
  const params = epoch ? `?epoch=${epoch}` : "";
  const r = await fetchJSON<{ processes: CogosProcess[] }>(
    `/api/cogents/${name}/processes${params}`,
  );
  return r.processes;
}

export async function getProcessDetail(
  name: string,
  processId: string,
): Promise<{ process: CogosProcess; runs: CogosProcessRun[]; resolved_prompt: string; prompt_tree: Array<{ key: string; content: string; is_direct: boolean }>; capabilities: string[]; capability_configs: Record<string, Record<string, unknown>>; cap_grants: Array<{ id: string; grant_name: string; capability_name: string; config: Record<string, unknown> | null }>; includes: Array<{ key: string; content: string }>; handlers: Array<{ id: string; event_pattern: string; enabled: boolean }> }> {
  return fetchJSON(`/api/cogents/${name}/processes/${processId}`);
}

export async function createProcess(
  name: string,
  body: Partial<Omit<CogosProcess, "id" | "created_at" | "updated_at" | "retry_count">> & { name: string },
): Promise<CogosProcess> {
  const resp = await fetch(`/api/cogents/${name}/processes`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function updateProcess(
  name: string,
  processId: string,
  updates: Partial<Omit<CogosProcess, "id" | "created_at" | "updated_at" | "retry_count">>,
): Promise<CogosProcess> {
  const resp = await fetch(`/api/cogents/${name}/processes/${processId}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteProcess(name: string, processId: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/processes/${processId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

export async function getProcessLogs(
  cogentName: string,
  processId: string,
  limit: number = 100,
): Promise<ProcessLogsResponse> {
  return fetchJSON(
    `/api/cogents/${cogentName}/processes/${processId}/logs?limit=${limit}`,
  );
}

export async function getFiles(name: string): Promise<CogosFile[]> {
  const r = await fetchJSON<{ files: CogosFile[] }>(
    `/api/cogents/${name}/files?limit=5000`,
  );
  return r.files;
}

export async function getFileDetail(
  name: string,
  key: string,
): Promise<{ file: CogosFile; versions: CogosFileVersion[] }> {
  return fetchJSON(`/api/cogents/${name}/files/${encodeFileKey(key)}`);
}

export async function createFile(
  name: string,
  body: { key: string; content: string; source?: string; read_only?: boolean },
): Promise<CogosFile> {
  const resp = await fetch(`/api/cogents/${name}/files`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers() },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function updateFile(
  name: string,
  key: string,
  body: { content: string; source?: string; read_only?: boolean },
): Promise<CogosFileVersion> {
  const resp = await fetch(`/api/cogents/${name}/files/${encodeFileKey(key)}`, {
    method: "PUT",
    headers: { "content-type": "application/json", ...headers() },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function activateFileVersion(
  name: string,
  key: string,
  version: number,
): Promise<void> {
  const resp = await fetch(
    `/api/cogents/${name}/files/${encodeFileKey(key)}/versions/${version}/activate`,
    { method: "POST", headers: headers() },
  );
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

export async function updateFileVersionContent(
  name: string,
  key: string,
  version: number,
  content: string,
): Promise<CogosFileVersion> {
  const resp = await fetch(
    `/api/cogents/${name}/files/${encodeFileKey(key)}/versions/${version}/content`,
    {
      method: "PUT",
      headers: { "content-type": "application/json", ...headers() },
      body: JSON.stringify({ content }),
    },
  );
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteFileVersion(
  name: string,
  key: string,
  version: number,
): Promise<void> {
  const resp = await fetch(
    `/api/cogents/${name}/files/${encodeFileKey(key)}/versions/${version}`,
    { method: "DELETE", headers: headers() },
  );
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

export async function deleteFile(name: string, key: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/files/${encodeFileKey(key)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

export async function getCapabilities(name: string): Promise<CogosCapability[]> {
  const r = await fetchJSON<{ capabilities: CogosCapability[] }>(
    `/api/cogents/${name}/capabilities`,
  );
  return r.capabilities;
}

export async function updateCapability(
  name: string,
  capName: string,
  updates: {
    enabled?: boolean;
    description?: string;
    instructions?: string;
    schema?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
  },
): Promise<CogosCapability> {
  const resp = await fetch(`/api/cogents/${name}/capabilities/${encodeURIComponent(capName)}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function getCapabilityProcesses(
  name: string,
  capName: string,
): Promise<CapabilityProcess[]> {
  return fetchJSON(`/api/cogents/${name}/capabilities/${encodeURIComponent(capName)}/processes`);
}

export interface CapabilityMethod {
  name: string;
  params: { name: string; type: string; default: string | null }[];
  return_type: string;
}

export async function getCapabilityMethods(
  name: string,
  capName: string,
): Promise<CapabilityMethod[]> {
  return fetchJSON(`/api/cogents/${name}/capabilities/${encodeURIComponent(capName)}/methods`);
}

export async function getResources(name: string): Promise<Resource[]> {
  const r = await fetchJSON<{ resources: Resource[] }>(
    `/api/cogents/${name}/resources`,
  );
  return r.resources;
}

export async function getEventTypes(name: string): Promise<EventType[]> {
  const r = await fetchJSON<{ event_types: EventType[] }>(
    `/api/cogents/${name}/event-types`,
  );
  return r.event_types;
}

export async function getHandlers(name: string): Promise<CogosHandler[]> {
  const r = await fetchJSON<{ handlers: CogosHandler[] }>(
    `/api/cogents/${name}/handlers`,
  );
  return r.handlers;
}

export async function getRuns(name: string, epoch?: string): Promise<CogosRun[]> {
  const params = epoch ? `?epoch=${epoch}` : "";
  const r = await fetchJSON<{ runs: CogosRun[] }>(
    `/api/cogents/${name}/runs${params}`,
  );
  return r.runs;
}

export async function getOperations(name: string): Promise<CogosOperation[]> {
  const r = await fetchJSON<{ operations: CogosOperation[] }>(
    `/api/cogents/${name}/operations`,
  );
  return r.operations;
}

export async function getRunLogs(
  name: string,
  runId: string,
  limit = 20,
): Promise<CogosRunLogsResponse> {
  return fetchJSON(`/api/cogents/${name}/runs/${runId}/logs?limit=${limit}`);
}

// ── Trigger management (stubs until backend routes exist) ────────────────────

export async function createTrigger(_name: string, _body: Record<string, unknown>): Promise<unknown> { return {}; }
export async function updateTrigger(_name: string, _id: string, _body: Record<string, unknown>): Promise<unknown> { return {}; }
export async function deleteTrigger(_name: string, _id: string): Promise<void> {}

// ── Tool management (stubs until backend routes exist) ───────────────────────

export async function updateTool(_name: string, _id: string, _body: Record<string, unknown>): Promise<unknown> { return {}; }
export async function deleteTool(_name: string, _id: string): Promise<void> {}
export async function toggleTools(_name: string, _ids: string[], _enabled: boolean): Promise<void> {}

// ── Task management (stubs until backend routes exist) ───────────────────────

export async function createTask(_name: string, _body: Record<string, unknown>): Promise<unknown> { return {}; }
export async function updateTask(_name: string, _id: string, _body: Record<string, unknown>): Promise<unknown> { return {}; }
export async function deleteTask(_name: string, _id: string): Promise<void> {}
export async function getTaskDetail(_name: string, _id: string): Promise<{ runs: never[]; task: { content: string | null } }> { return { runs: [], task: { content: null } }; }

// ── Memory management (stubs until backend routes exist) ─────────────────────

export async function createMemory(
  _name: string,
  _body: { name: string; content: string; group?: string },
): Promise<unknown> { return {}; }
export async function updateMemory(
  _name: string,
  _key: string,
  _body: { content: string },
): Promise<{ versions: { version: number }[] }> { return { versions: [{ version: 1 }] }; }
export async function deleteMemory(_name: string, _key: string): Promise<void> {}
export async function activateVersion(_name: string, _key: string, _version: number): Promise<void> {}
export async function updateVersionContent(
  _name: string,
  _key: string,
  _version: number,
  _content: string,
): Promise<unknown> { return {}; }
export async function deleteVersion(_name: string, _key: string, _version: number): Promise<void> {}

// ── Alert management ─────────────────────────────────────────────────────────

export async function getAlerts(name: string): Promise<Alert[]> {
  const data = await fetchJSON<{ alerts: Alert[] }>(`/api/cogents/${name}/alerts`);
  return data.alerts;
}

export async function resolveAlert(name: string, id: string): Promise<void> {
  await fetch(`/api/cogents/${name}/alerts/${id}/resolve`, {
    method: "POST",
    headers: headers(),
  });
}

export async function resolveAllAlerts(name: string): Promise<void> {
  await fetch(`/api/cogents/${name}/alerts/resolve-all`, {
    method: "POST",
    headers: headers(),
  });
}

export async function getResolvedAlerts(name: string, limit?: number): Promise<Alert[]> {
  const params = new URLSearchParams({ resolved: "true" });
  if (limit) params.set("limit", String(limit));
  const data = await fetchJSON<{ alerts: Alert[] }>(`/api/cogents/${name}/alerts?${params}`);
  return data.alerts;
}

export async function createAlert(name: string, alert: Partial<Alert>): Promise<void> {
  await fetch(`/api/cogents/${name}/alerts`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(alert),
  });
}

export async function deleteAlert(name: string, id: string): Promise<void> {
  await fetch(`/api/cogents/${name}/alerts/${id}`, {
    method: "DELETE",
    headers: headers(),
  });
}

// ── System ──────────────────────────────────────────────────────────────────

export async function reboot(name: string): Promise<{ cleared: number }> {
  const resp = await fetch(`/api/cogents/${name}/reboot`, {
    method: "POST",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}
