import type {
  StatusResponse,
  Program,
  Session,
  DashboardEvent,
  Trigger,
  MemoryItem,
  Task,
  Alert,
  CronItem,
  Resource,
  Tool,
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

export async function getStatus(
  name: string,
  range: TimeRange = "1h",
): Promise<StatusResponse> {
  return fetchJSON(`/api/cogents/${name}/status?range=${range}`);
}

export async function getPrograms(name: string): Promise<Program[]> {
  const r = await fetchJSON<{ programs: Program[] }>(
    `/api/cogents/${name}/programs`,
  );
  return r.programs;
}

export async function getSessions(name: string): Promise<Session[]> {
  const r = await fetchJSON<{ sessions: Session[] }>(
    `/api/cogents/${name}/sessions`,
  );
  return r.sessions;
}

export async function getEvents(
  name: string,
  range: TimeRange = "1h",
): Promise<DashboardEvent[]> {
  const r = await fetchJSON<{ events: DashboardEvent[] }>(
    `/api/cogents/${name}/events?range=${range}`,
  );
  return r.events;
}

export async function getTriggers(name: string): Promise<Trigger[]> {
  const r = await fetchJSON<{ triggers: Trigger[] }>(
    `/api/cogents/${name}/triggers`,
  );
  return r.triggers;
}

export async function getMemory(name: string): Promise<MemoryItem[]> {
  const r = await fetchJSON<{ memory: MemoryItem[] }>(
    `/api/cogents/${name}/memory`,
  );
  return r.memory;
}

export async function createMemory(
  name: string,
  mem: { name: string; content?: string; scope?: string; provenance?: Record<string, string> },
): Promise<MemoryItem> {
  const resp = await fetch(`/api/cogents/${name}/memory`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(mem),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function updateMemory(
  name: string,
  memoryId: string,
  updates: { name?: string; content?: string; scope?: string },
): Promise<MemoryItem> {
  const resp = await fetch(`/api/cogents/${name}/memory/${encodeURIComponent(memoryId)}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteMemory(name: string, memoryId: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/memory/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

export async function updateVersionContent(
  name: string,
  memoryName: string,
  version: number,
  content: string,
): Promise<MemoryItem> {
  const resp = await fetch(
    `/api/cogents/${name}/memory/${encodeURIComponent(memoryName)}/versions/${version}`,
    {
      method: "PATCH",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteVersion(
  name: string,
  memoryName: string,
  version: number,
): Promise<MemoryItem> {
  const resp = await fetch(
    `/api/cogents/${name}/memory/${encodeURIComponent(memoryName)}/versions/${version}`,
    { method: "DELETE", headers: headers() },
  );
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function activateVersion(
  name: string,
  memoryName: string,
  version: number,
): Promise<void> {
  const resp = await fetch(
    `/api/cogents/${name}/memory/${encodeURIComponent(memoryName)}/activate`,
    {
      method: "POST",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    },
  );
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

export async function getResources(name: string): Promise<Resource[]> {
  const r = await fetchJSON<{ resources: Resource[] }>(
    `/api/cogents/${name}/resources`,
  );
  return r.resources;
}

export async function getTasks(name: string): Promise<Task[]> {
  const r = await fetchJSON<{ tasks: Task[] }>(
    `/api/cogents/${name}/tasks`,
  );
  return r.tasks;
}

export async function getTaskDetail(
  name: string,
  taskId: string,
): Promise<{ task: Task; runs: Array<{ id: string; program_name: string; status: string | null; started_at: string | null; completed_at: string | null; duration_ms: number | null; tokens_input: number | null; tokens_output: number | null; cost_usd: number; error: string | null }> }> {
  return fetchJSON(`/api/cogents/${name}/tasks/${taskId}`);
}

export async function createTask(
  name: string,
  task: Partial<Omit<Task, "id" | "created_at" | "updated_at" | "completed_at" | "last_run_status" | "last_run_error" | "last_run_at">> & { name: string },
): Promise<Task> {
  const resp = await fetch(`/api/cogents/${name}/tasks`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(task),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function updateTask(
  name: string,
  taskId: string,
  updates: Partial<Omit<Task, "id" | "created_at" | "updated_at" | "completed_at" | "last_run_status" | "last_run_error" | "last_run_at">>,
): Promise<Task> {
  const resp = await fetch(`/api/cogents/${name}/tasks/${taskId}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteTask(name: string, taskId: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/tasks/${taskId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}


export async function getAlerts(name: string): Promise<Alert[]> {
  const r = await fetchJSON<{ alerts: Alert[] }>(
    `/api/cogents/${name}/alerts`,
  );
  return r.alerts;
}

export async function getResolvedAlerts(name: string, limit = 25): Promise<Alert[]> {
  const r = await fetchJSON<{ alerts: Alert[] }>(
    `/api/cogents/${name}/alerts?status=resolved&limit=${limit}`,
  );
  return r.alerts;
}

export async function resolveAllAlerts(name: string): Promise<{ resolved_count: number }> {
  const resp = await fetch(`/api/cogents/${name}/alerts/resolve-all`, {
    method: "POST",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function resolveAlert(
  name: string,
  alertId: string,
): Promise<{ resolved: boolean }> {
  const resp = await fetch(`/api/cogents/${name}/alerts/${alertId}/resolve`, {
    method: "POST",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function createAlert(
  name: string,
  alert: {
    severity?: string;
    alert_type?: string;
    source?: string;
    message: string;
    metadata?: Record<string, unknown>;
  },
): Promise<Alert> {
  const resp = await fetch(`/api/cogents/${name}/alerts`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(alert),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteAlert(
  name: string,
  alertId: string,
): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/alerts/${alertId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
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

export async function createTrigger(
  name: string,
  trigger: { program_name: string; event_pattern: string; priority?: number; enabled?: boolean; metadata?: Record<string, unknown>; max_events?: number; throttle_window_seconds?: number },
): Promise<Trigger> {
  const resp = await fetch(`/api/cogents/${name}/triggers`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(trigger),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function updateTrigger(
  name: string,
  triggerId: string,
  updates: { program_name?: string; event_pattern?: string; priority?: number; max_events?: number; throttle_window_seconds?: number },
): Promise<Trigger> {
  const resp = await fetch(`/api/cogents/${name}/triggers/${triggerId}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteTrigger(name: string, triggerId: string): Promise<{ deleted: boolean }> {
  const resp = await fetch(`/api/cogents/${name}/triggers/${triggerId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function toggleTriggers(
  name: string,
  ids: string[],
  enabled: boolean,
): Promise<void> {
  await fetch(`/api/cogents/${name}/triggers/toggle`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ ids, enabled }),
  });
}

// ── Tools ──────────────────────────────────────────────────────────────────

export async function getTools(name: string): Promise<Tool[]> {
  const r = await fetchJSON<{ tools: Tool[] }>(
    `/api/cogents/${name}/tools`,
  );
  return r.tools;
}

export async function updateTool(
  name: string,
  toolName: string,
  updates: { description?: string; instructions?: string; enabled?: boolean; metadata?: Record<string, unknown> },
): Promise<Tool> {
  const resp = await fetch(`/api/cogents/${name}/tools/${toolName}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function toggleTools(
  name: string,
  ids: string[],
  enabled: boolean,
): Promise<void> {
  await fetch(`/api/cogents/${name}/tools/toggle`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ ids, enabled }),
  });
}

export async function deleteTool(name: string, toolName: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/tools/${toolName}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
}

// ── CogOS API ───────────────────────────────────────────────────────────────

export async function getCogosStatus(name: string): Promise<CogosStatus> {
  return fetchJSON(`/api/cogents/${name}/cogos-status`);
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
): Promise<{ process: CogosProcess; runs: CogosProcessRun[]; resolved_prompt: string; file_keys: string[]; capabilities: string[]; capability_configs: Record<string, Record<string, unknown>> }> {
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