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
  epoch: number;
  name: string;
  mode: "daemon" | "one_shot";
  executor: string;
  content: string;
  priority: number;
  resources: string[];
  required_tags: string[];
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
  schema: Record<string, unknown>;
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
  grant_name: string;
  config: Record<string, unknown> | null;
}

export interface CogosHandler {
  id: string;
  process: string;
  process_name?: string;
  channel_id?: string;
  channel_name?: string;
  enabled: boolean;
  created_at?: string;
}

export interface CogosRun {
  id: string;
  epoch: number;
  process: string;
  process_name?: string;
  executor?: string | null;
  required_tags?: string[] | null;
  status: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  duration_ms: number | null;
  error: string | null;
  model_version: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface CogosRunLogEntry {
  timestamp: string;
  message: string;
  log_stream: string;
}

export interface CogosRunLogsResponse {
  log_group: string;
  log_stream: string | null;
  entries: CogosRunLogEntry[];
  error: string | null;
}

export interface RunFileMutation {
  key: string;
  version: number;
  diff: string | null;
  created_at: string | null;
}

export interface RunSentMessage {
  id: string;
  channel_name: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface RunChildRun {
  id: string;
  process: string;
  process_name: string | null;
  status: string;
  duration_ms: number | null;
  created_at: string | null;
}

export interface RunOutputsResponse {
  files: RunFileMutation[];
  messages: RunSentMessage[];
  children: RunChildRun[];
}

export interface CogosChannel {
  id: string;
  name: string;
  channel_type: string;
  owner_process: string | null;
  owner_process_name: string | null;
  schema_name: string | null;
  schema_id: string | null;
  schema_definition: Record<string, unknown> | null;
  inline_schema: Record<string, unknown> | null;
  auto_close: boolean;
  closed_at: string | null;
  message_count: number;
  subscriber_count: number;
  created_at: string | null;
}

export interface ChannelSendResult {
  id: string;
  channel_id: string;
  channel_name: string;
  payload: Record<string, unknown>;
}

export interface AgeInfo {
  image: string | null;
  content: string | null;
  stack: string | null;
  schema: string | null;
  state: string | null;
}

export interface CogosStatus {
  processes: { total: number; by_status: Record<string, number> };
  files: number;
  capabilities: number;
  recent_channels: number;
  recent_runs: Array<{ id: string; process_name: string; status: string; duration_ms: number | null; created_at: string }>;
  scheduler_last_tick: string | null;
  ages: AgeInfo | null;
  reboot_epoch: number;
}

export interface TraceMessage {
  id: string;
  channel_id: string;
  channel_name: string;
  message_type: string | null;
  trace_id: string | null;
  request_id: string | null;
  sender_process: string | null;
  sender_process_name: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface TraceRun {
  id: string;
  process: string;
  process_name: string | null;
  required_tags: string[] | null;
  status: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  duration_ms: number | null;
  error: string | null;
  model_version: string | null;
  result: Record<string, unknown> | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface TraceDelivery {
  id: string;
  handler_id: string;
  status: string;
  created_at: string | null;
  process_id: string | null;
  process_name: string | null;
  run: TraceRun | null;
  emitted_messages: TraceMessage[];
}

export interface MessageTrace {
  message: TraceMessage;
  deliveries: TraceDelivery[];
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
  channel_name: string;
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

export interface ProcessLogEntry {
  stream: string;
  text: string;
  process_name: string | null;
  created_at: string | null;
}

export interface ProcessLogsResponse {
  process_id: string;
  process_name: string;
  entries: ProcessLogEntry[];
}

export type TimeRange = "1m" | "10m" | "1h" | "24h" | "1w";
export type Timezone = "local" | "utc" | "pst";

export interface CogosExecutor {
  id: string;
  executor_id: string;
  channel_type: string;
  executor_tags: string[];
  dispatch_type: string;
  metadata: Record<string, unknown>;
  status: string;
  current_run_id: string | null;
  last_heartbeat_at: string | null;
  registered_at: string | null;
}

export interface DashboardData {
  status: StatusResponse | null;
  cogosStatus: CogosStatus | null;
  traces: MessageTrace[];
  alerts: Alert[];
  crons: CronItem[];
  resources: Resource[];
  processes: CogosProcess[];
  files: CogosFile[];
  capabilities: CogosCapability[];
  handlers: CogosHandler[];
  runs: CogosRun[];
  eventTypes: EventType[];
  executors: CogosExecutor[];
}

export type SetupStatus = "ready" | "needs_action" | "manual" | "unknown";

export interface SetupAction {
  label: string;
  command: string | null;
  href: string | null;
}

export interface SetupStep {
  key: string;
  title: string;
  description: string;
  status: SetupStatus;
  detail: string | null;
  action: SetupAction | null;
}

export interface ChannelSetup {
  key: string;
  title: string;
  description: string;
  status: SetupStatus;
  summary: string;
  ready_for_test: boolean;
  steps: SetupStep[];
  diagnostics: string[];
}

export interface SetupResponse {
  channels: ChannelSetup[];
}
