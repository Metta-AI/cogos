import type {
  DashboardEvent,
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
  EventType,
  Resource,
  Alert,
  DiscordSetupStatus,
} from "./types";

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("cogent-api-key");
}

function headers(): Record<string, string> {
  const key = getApiKey();
  return key ? { "x-api-key": key } : {};
}

async function fetchJSON<T>(path: string): Promise<T> {
  const resp = await fetch(path, { headers: headers() });
  if (resp.status === 401) throw new Error("unauthorized");
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

// ── Events ──────────────────────────────────────────────────────────────────

export async function getEvents(
  name: string,
  range: TimeRange = "1h",
): Promise<DashboardEvent[]> {
  const r = await fetchJSON<{ events: DashboardEvent[] }>(
    `/api/cogents/${name}/events?range=${range}`,
  );
  return r.events;
}

export async function getEventTree(
  name: string,
  eventId: number | string,
): Promise<DashboardEvent[]> {
  const r = await fetchJSON<{ events: DashboardEvent[] }>(
    `/api/cogents/${name}/events/${eventId}/tree`,
  );
  return r.events;
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

export async function getCogosStatus(name: string): Promise<CogosStatus> {
  return fetchJSON(`/api/cogents/${name}/cogos-status`);
}

export async function getDiscordSetup(name: string): Promise<DiscordSetupStatus> {
  return fetchJSON(`/api/cogents/${name}/setup/discord`);
}

export async function getProcesses(name: string): Promise<CogosProcess[]> {
  const r = await fetchJSON<{ processes: CogosProcess[] }>(
    `/api/cogents/${name}/processes`,
  );
  return r.processes;
}

export async function getProcessDetail(
  name: string,
  processId: string,
): Promise<{ process: CogosProcess; runs: CogosProcessRun[]; resolved_prompt: string; prompt_tree: Array<{ key: string; content: string; is_direct: boolean }>; file_keys: string[]; capabilities: string[]; capability_configs: Record<string, Record<string, unknown>>; includes: Array<{ key: string; content: string }>; handlers: Array<{ id: string; event_pattern: string; enabled: boolean }> }> {
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

export async function getFiles(name: string): Promise<CogosFile[]> {
  const r = await fetchJSON<{ files: CogosFile[] }>(
    `/api/cogents/${name}/files`,
  );
  return r.files;
}

export async function getFileDetail(
  name: string,
  key: string,
): Promise<{ file: CogosFile; versions: CogosFileVersion[] }> {
  return fetchJSON(`/api/cogents/${name}/files/${key}`);
}

export async function createFile(
  name: string,
  body: { key: string; content: string; source?: string; read_only?: boolean; includes?: string[] },
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
  const resp = await fetch(`/api/cogents/${name}/files/${key}`, {
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
    `/api/cogents/${name}/files/${key}/versions/${version}/activate`,
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
    `/api/cogents/${name}/files/${key}/versions/${version}/content`,
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
    `/api/cogents/${name}/files/${key}/versions/${version}`,
    { method: "DELETE", headers: headers() },
  );
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

export async function deleteFile(name: string, key: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/files/${key}`, {
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
    input_schema?: Record<string, unknown>;
    output_schema?: Record<string, unknown>;
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

export async function getRuns(name: string): Promise<CogosRun[]> {
  const r = await fetchJSON<{ runs: CogosRun[] }>(
    `/api/cogents/${name}/runs`,
  );
  return r.runs;
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

// ── Alert management (stubs until backend routes exist) ─────────────────────

export async function resolveAlert(_name: string, _id: string): Promise<void> {}
export async function resolveAllAlerts(_name: string): Promise<void> {}
export async function getResolvedAlerts(_name: string, _limit?: number): Promise<Alert[]> { return []; }
export async function createAlert(_name: string, _alert: Partial<Alert>): Promise<void> {}
export async function deleteAlert(_name: string, _id: string): Promise<void> {}
