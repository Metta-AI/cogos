export interface StatusResponse {
  cogent_id: string;
  active_sessions: number;
  total_conversations: number;
  trigger_count: number;
  unresolved_alerts: number;
  recent_events: number;
}

// ── CogOS Types ─────────────────────────────────────────────────────────────

export interface CogosProcess {
  id: string;
  name: string;
  mode: "daemon" | "one_shot";
  content: string;
  code: string | null;
  files: string[];
  priority: number;
  resources: string[];
  runner: string;
  status: string;
  runnable_since: string | null;
  parent_process: string | null;
  preemptible: boolean;
  model: string | null;
  model_constraints: Record<string, unknown>;
  return_schema: Record<string, unknown> | null;
  max_duration_ms: number | null;
  max_retries: number;
  retry_count: number;
  retry_backoff_ms: number | null;
  clear_context: boolean;
  metadata: Record<string, unknown>;
  output_events: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface EventType {
  name: string;
  description: string;
  source: string;
  created_at: string | null;
}

export interface CogosProcessRun {
  id: string;
  status: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  duration_ms: number | null;
  error: string | null;
  result: Record<string, unknown> | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface CogosFileVersion {
  id: string;
  file_id: string;
  version: number;
  content: string;
  source: string;
  read_only: boolean;
  is_active: boolean;
  created_at: string | null;
}

export interface CogosFile {
  id: string;
  key: string;
  includes: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CogosCapability {
  id: string;
  name: string;
  description: string;
  instructions: string;
  handler: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  iam_role_arn: string | null;
  enabled: boolean;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface CapabilityProcess {
  process_id: string;
  process_name: string;
  process_status: string;
  delegatable: boolean;
  config: Record<string, unknown> | null;
}

export interface CogosHandler {
  id: string;
  process: string;
  process_name?: string;
  event_pattern: string;
  enabled: boolean;
  fired_1m: number;
  fired_5m: number;
  fired_1h: number;
  fired_24h: number;
}

export interface CogosRun {
  id: string;
  process: string;
  process_name?: string;
  status: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  duration_ms: number | null;
  error: string | null;
  model_version: string | null;
  created_at: string | null;
}

export interface CogosStatus {
  processes: { total: number; by_status: Record<string, number> };
  files: number;
  capabilities: number;
  recent_events: number;
  recent_runs: Array<{ id: string; process_name: string; status: string; duration_ms: number | null; created_at: string }>;
  scheduler_last_tick: string | null;
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
  parent_event_id: number | string | null;
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
  max_events: number;
  throttle_window_seconds: number;
  throttle_rejected: number;
  throttle_active: boolean;
}

export interface MemoryVersionItem {
  id: string;
  version: number;
  content: string;
  source: string | null;
  read_only: boolean;
  created_at: string | null;
}

export interface MemoryItem {
  id: string;
  name: string;
  group: string;
  active_version: number;
  includes: string[];
  content: string;
  source: string | null;
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

export interface Tool {
  id: string;
  name: string;
  description: string;
  instructions: string;
  input_schema: Record<string, unknown>;
  handler: string;
  iam_role_arn: string | null;
  enabled: boolean;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export type TimeRange = "1m" | "10m" | "1h" | "24h" | "1w";
export type Timezone = "local" | "utc" | "pst";

export interface DashboardData {
  status: StatusResponse | null;
  cogosStatus: CogosStatus | null;
  programs: Program[];
  sessions: Session[];
  events: DashboardEvent[];
  triggers: Trigger[];
  memory: MemoryItem[];
  tasks: Task[];
  alerts: Alert[];
  crons: CronItem[];
  resources: Resource[];
  tools: Tool[];
  processes: CogosProcess[];
  files: CogosFile[];
  capabilities: CogosCapability[];
  handlers: CogosHandler[];
  runs: CogosRun[];
  eventTypes: EventType[];
}