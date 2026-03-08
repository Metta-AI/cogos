import type {
  StatusResponse,
  Program,
  Session,
  DashboardEvent,
  Trigger,
  MemoryItem,
  Task,
  Channel,
  Alert,
  CronItem,
  Resource,
  TimeRange,
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

export async function getChannels(name: string): Promise<Channel[]> {
  const r = await fetchJSON<{ channels: Channel[] }>(
    `/api/cogents/${name}/channels`,
  );
  return r.channels;
}

export async function createChannel(
  name: string,
  channel: { name: string; type?: string; enabled?: boolean; config?: Record<string, unknown> },
): Promise<Channel> {
  const resp = await fetch(`/api/cogents/${name}/channels`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(channel),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function updateChannel(
  name: string,
  channelName: string,
  updates: { type?: string; enabled?: boolean; config?: Record<string, unknown> },
): Promise<Channel> {
  const resp = await fetch(`/api/cogents/${name}/channels/${encodeURIComponent(channelName)}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function deleteChannel(name: string, channelName: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${name}/channels/${encodeURIComponent(channelName)}`, {
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