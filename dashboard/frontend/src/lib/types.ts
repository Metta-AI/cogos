export interface StatusResponse {
  cogent_id: string;
  active_sessions: number;
  total_conversations: number;
  trigger_count: number;
  unresolved_alerts: number;
  recent_events: number;
}

export interface Execution {
  id: string;
  program_name: string;
  conversation_id: string | null;
  status: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  tokens_input: number | null;
  tokens_output: number | null;
  cost_usd: number;
  error: string | null;
}

export interface Program {
  name: string;
  type: string;
  description: string;
  complexity: string | null;
  model: string | null;
  trigger_count: number;
  group: string;
  runs: number;
  ok: number;
  fail: number;
  total_cost: number;
  last_run: string | null;
}

export interface Session {
  id: string;
  context_key: string | null;
  status: string | null;
  cli_session_id: string | null;
  started_at: string | null;
  last_active: string | null;
  metadata: Record<string, unknown> | null;
  runs: number;
  ok: number;
  fail: number;
  tokens_in: number;
  tokens_out: number;
  total_cost: number;
}

export interface DashboardEvent {
  id: number | string;
  event_type: string | null;
  source: string | null;
  payload: unknown;
  parent_event_id: number | null;
  created_at: string | null;
}

export interface Trigger {
  id: string;
  name: string;
  trigger_type: string | null;
  event_pattern: string | null;
  cron_expression: string | null;
  program_name: string | null;
  priority: number | null;
  enabled: boolean;
  created_at: string | null;
  fired_1m: number;
  fired_5m: number;
  fired_1h: number;
  fired_24h: number;
}

export interface MemoryVersionItem {
  id: string;
  version: number;
  content: string;
  source: string;
  read_only: boolean;
  created_at: string | null;
}

export interface MemoryItem {
  id: string;
  name: string;
  group: string;
  active_version: number;
  content: string;
  source: string;
  read_only: boolean;
  created_at: string | null;
  modified_at: string | null;
  versions: MemoryVersionItem[];
}

export interface Task {
  id: string;
  name: string | null;
  description: string | null;
  program_name: string | null;
  content: string | null;
  status: string | null;
  priority: number | null;
  runner: string | null;
  clear_context: boolean | null;
  recurrent: boolean | null;
  memory_keys: string[] | null;
  tools: string[] | null;
  resources: string[] | null;
  creator: string | null;
  parent_task_id: string | null;
  source_event: string | null;
  limits: Record<string, unknown> | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
  last_run_status: string | null;
  last_run_error: string | null;
  last_run_at: string | null;
  run_counts: Record<string, { runs: number; failed: number }> | null;
}

export interface Channel {
  name: string;
  type: string | null;
  enabled: boolean;
  created_at: string | null;
}

export interface Alert {
  id: string;
  severity: string | null;
  alert_type: string | null;
  source: string | null;
  message: string | null;
  metadata: Record<string, unknown> | null;
  resolved_at: string | null;
  created_at: string | null;
}

export interface CronItem {
  id: string;
  cron_expression: string;
  event_pattern: string;
  enabled: boolean;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

export interface Resource {
  name: string;
  resource_type: string;
  capacity: number;
  used: number;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

export type TimeRange = "1m" | "10m" | "1h" | "24h" | "1w";
export type Timezone = "local" | "utc" | "pst";

export interface DashboardData {
  status: StatusResponse | null;
  programs: Program[];
  sessions: Session[];
  events: DashboardEvent[];
  triggers: Trigger[];
  memory: MemoryItem[];
  tasks: Task[];
  channels: Channel[];
  alerts: Alert[];
  crons: CronItem[];
  resources: Resource[];
}