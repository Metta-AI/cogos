import type {
  StatusResponse,
  Program,
  Session,
  DashboardEvent,
  Trigger,
  MemoryItem,
  MemoryVersionItem,
  Task,
  Channel,
  Alert,
  CronItem,
  Resource,
  Tool,
  DashboardData,
} from "./types";

function uuid(): string {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function ago(ms: number): string {
  return new Date(Date.now() - ms).toISOString().replace("T", " ").replace("Z", "");
}

const M = 60_000;
const H = 3_600_000;
const D = 86_400_000;

// ── Status ──────────────────────────────────────────────────────────────────

const status: StatusResponse = {
  cogent_id: "demo-cogent",
  active_sessions: 3,
  total_conversations: 47,
  trigger_count: 8,
  unresolved_alerts: 4,
  recent_events: 42,
};

// ── Programs ────────────────────────────────────────────────────────────────

const programs: Program[] = [
  { name: "code-reviewer", type: "PYTHON", description: "Automated code review bot for PRs", complexity: "high", model: "claude-sonnet-4-20250514", trigger_count: 2, group: "engineering", runs: 156, ok: 142, fail: 14, total_cost: 12.45, last_run: ago(15 * M) },
  { name: "test-agent", type: "PROMPT", description: "Test agent for local development", complexity: "medium", model: "claude-sonnet-4-20250514", trigger_count: 3, group: "engineering", runs: 89, ok: 67, fail: 22, total_cost: 6.78, last_run: ago(2 * H) },
  { name: "do-content", type: "PROMPT", description: "Content generation and management pipeline", complexity: "low", model: "claude-haiku-4-5-20251001", trigger_count: 1, group: "content", runs: 324, ok: 298, fail: 26, total_cost: 4.12, last_run: ago(5 * M) },
  { name: "deploy-manager", type: "PYTHON", description: "Deployment orchestration and rollback", complexity: "high", model: "claude-sonnet-4-20250514", trigger_count: 1, group: "ops", runs: 45, ok: 43, fail: 2, total_cost: 3.21, last_run: ago(6 * H) },
  { name: "alert-responder", type: "PROMPT", description: "Automatic alert triage and response", complexity: "medium", model: "claude-haiku-4-5-20251001", trigger_count: 1, group: "ops", runs: 210, ok: 195, fail: 15, total_cost: 2.56, last_run: ago(30 * M) },
  { name: "daily-digest", type: "PROMPT", description: "Generate daily summary reports", complexity: "low", model: "claude-haiku-4-5-20251001", trigger_count: 0, group: "reporting", runs: 30, ok: 30, fail: 0, total_cost: 0.89, last_run: ago(12 * H) },
];

// ── Sessions ────────────────────────────────────────────────────────────────

const sessions: Session[] = [
  { id: uuid(), context_key: "pr-review-142", status: "active", cli_session_id: null, started_at: ago(2 * H), last_active: ago(3 * M), metadata: { pr_number: 142 }, runs: 12, ok: 11, fail: 1, tokens_in: 45000, tokens_out: 12000, total_cost: 0.45 },
  { id: uuid(), context_key: "daily-digest", status: "active", cli_session_id: null, started_at: ago(12 * H), last_active: ago(30 * M), metadata: null, runs: 3, ok: 3, fail: 0, tokens_in: 18000, tokens_out: 6000, total_cost: 0.18 },
  { id: uuid(), context_key: "deploy-staging", status: "active", cli_session_id: null, started_at: ago(45 * M), last_active: ago(2 * M), metadata: { environment: "staging" }, runs: 5, ok: 4, fail: 1, tokens_in: 22000, tokens_out: 8000, total_cost: 0.31 },
  { id: uuid(), context_key: "alert-triage-7", status: "completed", cli_session_id: null, started_at: ago(4 * H), last_active: ago(3 * H), metadata: null, runs: 8, ok: 8, fail: 0, tokens_in: 32000, tokens_out: 10000, total_cost: 0.38 },
];

// ── Events ──────────────────────────────────────────────────────────────────

const events: DashboardEvent[] = [
  { id: 1, event_type: "GITHUB.PR_OPENED", source: "github-webhooks", payload: { pr: 142, repo: "acme/api", title: "Add user notifications endpoint" }, parent_event_id: null, created_at: ago(5 * M) },
  { id: 2, event_type: "GITHUB.PUSH", source: "github-webhooks", payload: { branch: "main", commits: 3 }, parent_event_id: null, created_at: ago(15 * M) },
  { id: 3, event_type: "TASK.STARTED", source: "task-runner", payload: { task: "/deploy/staging/run" }, parent_event_id: null, created_at: ago(20 * M) },
  { id: 4, event_type: "ALERT.TRIGGERED", source: "cost-monitor", payload: { alert: "Daily spend exceeded $5" }, parent_event_id: null, created_at: ago(30 * M) },
  { id: 5, event_type: "TASK.COMPLETED", source: "task-runner", payload: { task: "/content/blog/generate", status: "completed" }, parent_event_id: null, created_at: ago(45 * M) },
  { id: 6, event_type: "DISCORD.MESSAGE", source: "discord-general", payload: { channel: "#general", author: "alice" }, parent_event_id: null, created_at: ago(1 * H) },
  { id: 7, event_type: "CRON.HEARTBEAT", source: "cron-scheduler", payload: { expression: "*/5 * * * *" }, parent_event_id: null, created_at: ago(1.5 * H) },
  { id: 8, event_type: "EMAIL.RECEIVED", source: "email-ops", payload: { from: "ops@acme.com", subject: "Deploy approval" }, parent_event_id: null, created_at: ago(2 * H) },
  { id: 9, event_type: "GITHUB.PR_MERGED", source: "github-webhooks", payload: { pr: 139, repo: "acme/api" }, parent_event_id: null, created_at: ago(3 * H) },
  { id: 10, event_type: "TEST.LIVE", source: "test-runner", payload: { suite: "integration", passed: 42, failed: 2 }, parent_event_id: null, created_at: ago(4 * H) },
  { id: 11, event_type: "DEPLOY.STARTED", source: "ci", payload: { environment: "production", version: "v2.3.1" }, parent_event_id: null, created_at: ago(5 * H) },
  { id: 12, event_type: "SYSTEM.HEARTBEAT", source: "system", payload: { uptime: "72h" }, parent_event_id: null, created_at: ago(6 * H) },
  { id: 13, event_type: "GITHUB.PUSH", source: "github-webhooks", payload: { branch: "feature/auth", commits: 1 }, parent_event_id: null, created_at: ago(7 * H) },
  { id: 14, event_type: "SLACK.MESSAGE", source: "slack-engineering", payload: { channel: "#engineering", author: "bob" }, parent_event_id: null, created_at: ago(8 * H) },
  { id: 15, event_type: "CRON.DAILY_DIGEST", source: "cron-scheduler", payload: { report: "daily" }, parent_event_id: null, created_at: ago(12 * H) },
  { id: 16, event_type: "ALERT.RESOLVED", source: "alert-responder", payload: { alert_id: "a-001", resolution: "auto-scaled" }, parent_event_id: null, created_at: ago(14 * H) },
  { id: 17, event_type: "TASK.FAILED", source: "task-runner", payload: { task: "/deploy/prod/validate", error: "Health check timeout" }, parent_event_id: null, created_at: ago(18 * H) },
  { id: 18, event_type: "GITHUB.PR_REVIEW", source: "github-webhooks", payload: { pr: 140, reviewer: "carol", state: "approved" }, parent_event_id: null, created_at: ago(20 * H) },
  { id: 19, event_type: "EMAIL.SENT", source: "email-ops", payload: { to: "team@acme.com", subject: "Weekly report" }, parent_event_id: null, created_at: ago(24 * H) },
  { id: 20, event_type: "DEPLOY.COMPLETED", source: "ci", payload: { environment: "production", version: "v2.3.0", duration_ms: 180000 }, parent_event_id: null, created_at: ago(2 * D) },
];

// ── Triggers ────────────────────────────────────────────────────────────────

const triggers: Trigger[] = [
  { id: uuid(), name: "code-reviewer:github.push", trigger_type: null, event_pattern: "github.push", cron_expression: null, program_name: "code-reviewer", priority: 10, enabled: true, created_at: ago(30 * D), fired_1m: 0, fired_5m: 1, fired_1h: 3, fired_24h: 12, max_events: 10, throttle_window_seconds: 60, throttle_rejected: 0, throttle_active: false },
  { id: uuid(), name: "code-reviewer:github.pr.*", trigger_type: null, event_pattern: "github.pr.*", cron_expression: null, program_name: "code-reviewer", priority: 10, enabled: true, created_at: ago(30 * D), fired_1m: 1, fired_5m: 2, fired_1h: 5, fired_24h: 18, max_events: 0, throttle_window_seconds: 60, throttle_rejected: 0, throttle_active: false },
  { id: uuid(), name: "test-agent:github.pr.*", trigger_type: null, event_pattern: "github.pr.*", cron_expression: null, program_name: "test-agent", priority: 5, enabled: true, created_at: ago(20 * D), fired_1m: 1, fired_5m: 2, fired_1h: 5, fired_24h: 18, max_events: 0, throttle_window_seconds: 60, throttle_rejected: 0, throttle_active: false },
  { id: uuid(), name: "test-agent:test.*", trigger_type: null, event_pattern: "test.*", cron_expression: null, program_name: "test-agent", priority: 5, enabled: true, created_at: ago(20 * D), fired_1m: 0, fired_5m: 0, fired_1h: 1, fired_24h: 4, max_events: 0, throttle_window_seconds: 60, throttle_rejected: 0, throttle_active: false },
  { id: uuid(), name: "deploy-manager:deploy.*", trigger_type: null, event_pattern: "deploy.*", cron_expression: null, program_name: "deploy-manager", priority: 8, enabled: true, created_at: ago(15 * D), fired_1m: 0, fired_5m: 0, fired_1h: 0, fired_24h: 2, max_events: 0, throttle_window_seconds: 60, throttle_rejected: 0, throttle_active: false },
  { id: uuid(), name: "alert-responder:alert.triggered", trigger_type: null, event_pattern: "alert.triggered", cron_expression: null, program_name: "alert-responder", priority: 15, enabled: true, created_at: ago(25 * D), fired_1m: 0, fired_5m: 1, fired_1h: 2, fired_24h: 7, max_events: 5, throttle_window_seconds: 300, throttle_rejected: 12, throttle_active: true },
  { id: uuid(), name: "do-content:task.content.*", trigger_type: null, event_pattern: "task.content.*", cron_expression: null, program_name: "do-content", priority: 3, enabled: true, created_at: ago(10 * D), fired_1m: 0, fired_5m: 0, fired_1h: 1, fired_24h: 8, max_events: 0, throttle_window_seconds: 60, throttle_rejected: 0, throttle_active: false },
  { id: uuid(), name: "daily-digest:cron.daily", trigger_type: null, event_pattern: null, cron_expression: "0 9 * * *", program_name: "daily-digest", priority: 1, enabled: false, created_at: ago(30 * D), fired_1m: 0, fired_5m: 0, fired_1h: 0, fired_24h: 1, max_events: 0, throttle_window_seconds: 60, throttle_rejected: 0, throttle_active: false },
];

// ── Memory ──────────────────────────────────────────────────────────────────

function mockMem(
  name: string,
  group: string,
  content: string,
  source: string = "cogent",
  opts: { read_only?: boolean; extra_versions?: Omit<MemoryVersionItem, "id" | "memory_id">[] } = {},
): MemoryItem {
  const id = uuid();
  const v1: MemoryVersionItem = { id: uuid(), version: 1, content, source, read_only: opts.read_only ?? false, created_at: ago(30 * D) };
  const versions = [v1, ...(opts.extra_versions ?? []).map((v) => ({ ...v, id: uuid() }))];
  const active = versions[versions.length - 1];
  return {
    id, name, group, active_version: active.version, content: active.content,
    source: active.source, read_only: active.read_only,
    created_at: ago(30 * D), modified_at: ago(2 * D), versions,
  };
}

const memory: MemoryItem[] = [
  mockMem("identity", "default", "You are Ovo, a cogent — an autonomous agent system built on the cogents framework. Your primary purpose is to help your operator by monitoring channels (Discord, GitHub, email), executing tasks, and managing deployments. You respond in a concise, technical style.", "cogent", {
    extra_versions: [{ version: 2, content: "You are Ovo, a cogent. Help your operator by monitoring channels, executing tasks, and managing deployments. Be concise and technical.", source: "cogent", read_only: false, created_at: ago(2 * D) }],
  }),
  mockMem("personality", "default", "Professional, concise, technically precise. Uses bullet points. Avoids filler words."),
  mockMem("api-conventions", "api", "REST API naming: plural nouns, snake_case, version prefix /v1/. Always return JSON with top-level data wrapper. Use 201 for creation, 204 for deletion."),
  mockMem("discord-channels", "discord", "Monitored Discord channels:\n- #general — main discussion, respond to direct questions\n- #alerts — system alerts, always acknowledge critical ones\n- #dev — development discussion, help with code questions\n- #deploys — deployment notifications, track status"),
  mockMem("deployment-checklist", "deployment", "Pre-deployment verification steps: run tests, check migrations, validate configs, verify health endpoints, confirm rollback plan."),
  mockMem("conversation-history", "conversation", "Summary of recent conversation patterns: most requests relate to PR reviews, deployment status, and test failures. Average response time: 2.3s."),
  mockMem("github-repos", "github", "Monitored repos:\n- acme/api (primary backend)\n- acme/web (frontend)\n- acme/infra (IaC)\n- acme/docs (documentation)"),
  mockMem("cost-limits", "ops", "Daily cost budget: $10. Alert threshold: $5. Escalation at $8. Hard limit at $15."),
  mockMem("test-strategy", "testing", "Run integration tests on every PR. Run full suite nightly. Flaky test threshold: 3 retries. Report failures to #dev channel."),
  mockMem("operator-prefs", "default", "Operator timezone: US/Pacific. Preferred notification channel: Discord #alerts for critical, email for daily summaries. Do not notify between 10pm-7am unless P0.", "polis", { read_only: true }),
  mockMem("team-roster", "team", "Team: Alice (backend lead), Bob (frontend), Carol (infra), Dave (PM). Alice and Carol are deployment approvers.", "polis", { read_only: true }),
  mockMem("email-templates", "email", "Use templates: deploy-notification, weekly-report, alert-escalation. Keep subject lines under 60 chars. Always include action items."),
  mockMem("slack-config", "slack", "Slack workspace: acme-eng. Channels: #engineering, #deploys, #incidents. Use thread replies for ongoing conversations."),
  mockMem("rollback-procedures", "deployment", "Rollback steps: 1. Revert to previous container image 2. Run health checks 3. Verify DB compatibility 4. Notify in #deploys 5. Create post-mortem task"),
  mockMem("security-policies", "security", "Never commit secrets. Use AWS Secrets Manager for all credentials. Rotate API keys quarterly. Review access logs weekly.", "polis", { read_only: true }),
];

// ── Tasks ───────────────────────────────────────────────────────────────────

const tasks: Task[] = [
  { id: uuid(), name: "/deploy/staging/run", description: "Deploy latest to staging environment", program_name: "deploy-manager", content: "Deploy the latest main branch to staging. Run smoke tests after deployment. Report status to #deploys channel.", status: "running", priority: 8, runner: "deploy-runner-1", clear_context: false, recurrent: false, memory_keys: ["deployment-checklist"], tools: ["github-api", "aws-cli", "slack-notify"], resources: ["staging-cluster"], creator: "ci-pipeline", parent_task_id: null, source_event: "deploy.started", limits: { max_duration_ms: 600000 }, metadata: { environment: "staging", version: "v2.3.2" }, created_at: ago(20 * M), updated_at: ago(3 * M), completed_at: null, last_run_status: null, last_run_error: null, last_run_at: ago(20 * M), run_counts: { "1m": { runs: 0, failed: 0 }, "5m": { runs: 1, failed: 0 }, "1h": { runs: 2, failed: 0 }, "24h": { runs: 5, failed: 1 }, "7d": { runs: 12, failed: 2 } } },
  { id: uuid(), name: "/content/blog/generate", description: "Generate weekly blog post draft", program_name: "do-content", content: "Generate a technical blog post about recent engineering improvements. Use data from the past week's PRs and deployments.", status: "running", priority: 3, runner: null, clear_context: true, recurrent: true, memory_keys: ["conversation-history"], tools: ["github-api"], resources: [], creator: "cron", parent_task_id: null, source_event: "cron.weekly", limits: {}, metadata: {}, created_at: ago(45 * M), updated_at: ago(10 * M), completed_at: null, last_run_status: null, last_run_error: null, last_run_at: ago(45 * M), run_counts: { "1m": { runs: 0, failed: 0 }, "5m": { runs: 0, failed: 0 }, "1h": { runs: 1, failed: 0 }, "24h": { runs: 1, failed: 0 }, "7d": { runs: 4, failed: 0 } } },
  { id: uuid(), name: "/review/pr-142", description: "Review PR #142: Add user notifications", program_name: "code-reviewer", content: "Review PR #142 in acme/api. Check for security issues, test coverage, and code style. Post review comments.", status: "running", priority: 10, runner: "review-runner", clear_context: false, recurrent: false, memory_keys: ["api-conventions"], tools: ["github-api"], resources: [], creator: "trigger", parent_task_id: null, source_event: "github.pr.opened", limits: { max_tokens: 50000 }, metadata: { pr_number: 142, repo: "acme/api" }, created_at: ago(5 * M), updated_at: ago(1 * M), completed_at: null, last_run_status: null, last_run_error: null, last_run_at: ago(5 * M), run_counts: { "1m": { runs: 1, failed: 0 }, "5m": { runs: 1, failed: 0 }, "1h": { runs: 1, failed: 0 }, "24h": { runs: 8, failed: 1 }, "7d": { runs: 24, failed: 3 } } },
  { id: uuid(), name: "/deploy/staging/run", description: "Deploy latest to staging environment", program_name: "deploy-manager", content: "Deploy the latest main branch to staging.", status: "completed", priority: 8, runner: "deploy-runner-1", clear_context: false, recurrent: false, memory_keys: ["deployment-checklist"], tools: ["github-api", "aws-cli"], resources: ["staging-cluster"], creator: "ci-pipeline", parent_task_id: null, source_event: "deploy.started", limits: {}, metadata: { environment: "staging", version: "v2.3.1" }, created_at: ago(6 * H), updated_at: ago(5 * H), completed_at: ago(5 * H), last_run_status: "completed", last_run_error: null, last_run_at: ago(5 * H), run_counts: { "1m": { runs: 0, failed: 0 }, "5m": { runs: 0, failed: 0 }, "1h": { runs: 0, failed: 0 }, "24h": { runs: 3, failed: 0 }, "7d": { runs: 12, failed: 2 } } },
  { id: uuid(), name: "/deploy/prod/validate", description: "Validate production deployment health", program_name: "deploy-manager", content: "Run health checks against production. Verify all endpoints respond within SLA. Check error rates.", status: "completed", priority: 10, runner: null, clear_context: false, recurrent: false, memory_keys: [], tools: ["aws-cli", "curl"], resources: ["prod-cluster"], creator: "ci-pipeline", parent_task_id: null, source_event: null, limits: {}, metadata: {}, created_at: ago(18 * H), updated_at: ago(17 * H), completed_at: ago(17 * H), last_run_status: "failed", last_run_error: "Health check timeout after 30s on /api/v1/notifications", last_run_at: ago(17 * H), run_counts: { "1m": { runs: 0, failed: 0 }, "5m": { runs: 0, failed: 0 }, "1h": { runs: 0, failed: 0 }, "24h": { runs: 2, failed: 1 }, "7d": { runs: 8, failed: 3 } } },
  { id: uuid(), name: "/test/integration/run", description: "Run integration test suite", program_name: "test-agent", content: "Execute full integration test suite. Report failures to #dev channel. Create tasks for flaky test fixes.", status: "runnable", priority: 5, runner: null, clear_context: true, recurrent: true, memory_keys: ["test-strategy"], tools: ["pytest", "github-api", "slack-notify"], resources: [], creator: "cron", parent_task_id: null, source_event: null, limits: { max_duration_ms: 900000 }, metadata: {}, created_at: ago(4 * H), updated_at: ago(4 * H), completed_at: ago(4 * H), last_run_status: "completed", last_run_error: null, last_run_at: ago(4 * H), run_counts: { "1m": { runs: 0, failed: 0 }, "5m": { runs: 0, failed: 0 }, "1h": { runs: 0, failed: 0 }, "24h": { runs: 4, failed: 1 }, "7d": { runs: 28, failed: 4 } } },
  { id: uuid(), name: "/alert/triage/cost-spike", description: "Triage cost spike alert", program_name: "alert-responder", content: "Investigate cost spike. Check which programs/tasks are causing increased spend. Recommend throttling if needed.", status: "runnable", priority: 15, runner: null, clear_context: false, recurrent: false, memory_keys: ["cost-limits"], tools: ["aws-cost-explorer"], resources: [], creator: "trigger", parent_task_id: null, source_event: "alert.triggered", limits: {}, metadata: { alert_type: "cost_spike" }, created_at: ago(30 * M), updated_at: ago(30 * M), completed_at: null, last_run_status: null, last_run_error: null, last_run_at: null, run_counts: { "1m": { runs: 0, failed: 0 }, "5m": { runs: 0, failed: 0 }, "1h": { runs: 0, failed: 0 }, "24h": { runs: 0, failed: 0 }, "7d": { runs: 2, failed: 0 } } },
  { id: uuid(), name: "/content/docs/update-api", description: "Update API documentation", program_name: "do-content", content: "Scan recent API changes and update documentation. Ensure all new endpoints are documented with examples.", status: "runnable", priority: 2, runner: null, clear_context: true, recurrent: false, memory_keys: ["api-conventions"], tools: ["github-api"], resources: [], creator: "dashboard", parent_task_id: null, source_event: null, limits: {}, metadata: {}, created_at: ago(2 * H), updated_at: ago(2 * H), completed_at: null, last_run_status: null, last_run_error: null, last_run_at: null, run_counts: null },
  { id: uuid(), name: "/monitor/uptime-check", description: "Run periodic uptime monitoring", program_name: "alert-responder", content: "Check all service endpoints. Verify response times. Alert on degradation.", status: "disabled", priority: 5, runner: null, clear_context: false, recurrent: true, memory_keys: [], tools: ["curl", "slack-notify"], resources: ["prod-cluster"], creator: "system", parent_task_id: null, source_event: null, limits: {}, metadata: {}, created_at: ago(30 * D), updated_at: ago(7 * D), completed_at: ago(7 * D), last_run_status: "completed", last_run_error: null, last_run_at: ago(7 * D), run_counts: { "1m": { runs: 0, failed: 0 }, "5m": { runs: 0, failed: 0 }, "1h": { runs: 0, failed: 0 }, "24h": { runs: 0, failed: 0 }, "7d": { runs: 0, failed: 0 } } },
  { id: uuid(), name: "/review/pr-140", description: "Review PR #140: Fix auth middleware", program_name: "code-reviewer", content: "Review PR #140 for security implications of auth middleware changes.", status: "completed", priority: 10, runner: null, clear_context: false, recurrent: false, memory_keys: ["api-conventions"], tools: ["github-api"], resources: [], creator: "trigger", parent_task_id: null, source_event: "github.pr.opened", limits: {}, metadata: { pr_number: 140 }, created_at: ago(20 * H), updated_at: ago(18 * H), completed_at: ago(18 * H), last_run_status: "completed", last_run_error: null, last_run_at: ago(18 * H), run_counts: { "1m": { runs: 0, failed: 0 }, "5m": { runs: 0, failed: 0 }, "1h": { runs: 0, failed: 0 }, "24h": { runs: 1, failed: 0 }, "7d": { runs: 1, failed: 0 } } },
];

// ── Channels ────────────────────────────────────────────────────────────────

const channels: Channel[] = [
  { name: "discord-general", type: "discord", enabled: true, created_at: ago(60 * D) },
  { name: "discord-alerts", type: "discord", enabled: true, created_at: ago(60 * D) },
  { name: "discord-dev", type: "discord", enabled: true, created_at: ago(45 * D) },
  { name: "email-ops", type: "email", enabled: true, created_at: ago(30 * D) },
  { name: "github-webhooks", type: "github", enabled: true, created_at: ago(55 * D) },
  { name: "slack-engineering", type: "slack", enabled: true, created_at: ago(20 * D) },
  { name: "slack-incidents", type: "slack", enabled: false, created_at: ago(15 * D) },
];

// ── Alerts ──────────────────────────────────────────────────────────────────

const alerts: Alert[] = [
  { id: uuid(), severity: "critical", alert_type: "cost_spike", source: "cost-monitor", message: "Daily API spend exceeded $8 threshold — currently at $9.42. Top consumer: code-reviewer (68%)", metadata: { current_spend: 9.42, threshold: 8, top_program: "code-reviewer" }, resolved_at: null, created_at: ago(30 * M) },
  { id: uuid(), severity: "high", alert_type: "task_failure", source: "task-runner", message: "Task /deploy/prod/validate failed: Health check timeout after 30s on /api/v1/notifications", metadata: { task_id: "t-005", error: "timeout" }, resolved_at: null, created_at: ago(18 * H) },
  { id: uuid(), severity: "medium", alert_type: "flaky_tests", source: "test-agent", message: "Integration test suite has 3 flaky tests (>2 retries in last 24h): test_user_auth, test_webhook_delivery, test_rate_limiter", metadata: { flaky_count: 3 }, resolved_at: null, created_at: ago(4 * H) },
  { id: uuid(), severity: "low", alert_type: "stale_task", source: "system", message: "Task /monitor/uptime-check has been disabled for 7 days. Consider re-enabling or deleting.", metadata: {}, resolved_at: null, created_at: ago(1 * D) },
  { id: uuid(), severity: "high", alert_type: "error_rate", source: "deploy-manager", message: "Error rate on staging environment spiked to 4.2% (threshold: 2%). Most errors: 502 Bad Gateway on /api/v1/notifications", metadata: { error_rate: 4.2, threshold: 2 }, resolved_at: ago(5 * H), created_at: ago(6 * H) },
  { id: uuid(), severity: "medium", alert_type: "cost_warning", source: "cost-monitor", message: "Weekly cost trending 20% above last week. Projected weekly total: $52 (budget: $70)", metadata: { projected: 52, budget: 70 }, resolved_at: ago(2 * D), created_at: ago(3 * D) },
];

// ── Crons ───────────────────────────────────────────────────────────────────

const crons: CronItem[] = [
  { id: uuid(), cron_expression: "*/5 * * * *", event_pattern: "cron.heartbeat", enabled: true, metadata: { description: "System heartbeat every 5 minutes" }, created_at: ago(60 * D) },
  { id: uuid(), cron_expression: "0 9 * * *", event_pattern: "cron.daily-digest", enabled: true, metadata: { description: "Daily digest at 9am" }, created_at: ago(45 * D) },
  { id: uuid(), cron_expression: "0 */6 * * *", event_pattern: "cron.github-sync", enabled: true, metadata: { description: "GitHub sync every 6 hours" }, created_at: ago(30 * D) },
  { id: uuid(), cron_expression: "30 17 * * 1-5", event_pattern: "cron.eod-summary", enabled: false, metadata: { description: "End-of-day summary at 5:30pm weekdays" }, created_at: ago(20 * D) },
  { id: uuid(), cron_expression: "0 0 * * 0", event_pattern: "cron.weekly-report", enabled: true, metadata: { description: "Weekly report every Sunday midnight" }, created_at: ago(15 * D) },
  { id: uuid(), cron_expression: "*/15 * * * *", event_pattern: "cron.cost-check", enabled: true, metadata: { description: "Cost monitoring every 15 minutes" }, created_at: ago(10 * D) },
];

// ── Resources ────────────────────────────────────────────────────────────────

const resources: Resource[] = [
  { name: "concurrent-tasks", resource_type: "pool", capacity: 5, used: 3, metadata: { description: "Max concurrent task executions" }, created_at: ago(60 * D) },
  { name: "review-runner", resource_type: "pool", capacity: 2, used: 1, metadata: { description: "Code review runner slots" }, created_at: ago(30 * D) },
  { name: "deploy-runner-1", resource_type: "pool", capacity: 1, used: 1, metadata: { description: "Staging deployment runner" }, created_at: ago(30 * D) },
  { name: "staging-cluster", resource_type: "pool", capacity: 1, used: 1, metadata: { description: "Staging cluster access" }, created_at: ago(45 * D) },
  { name: "prod-cluster", resource_type: "pool", capacity: 1, used: 0, metadata: { description: "Production cluster access" }, created_at: ago(45 * D) },
  { name: "daily-api-budget", resource_type: "consumable", capacity: 10, used: 9.42, metadata: { description: "Daily API spend limit ($)" }, created_at: ago(30 * D) },
  { name: "weekly-token-budget", resource_type: "consumable", capacity: 500000, used: 317000, metadata: { description: "Weekly token allocation" }, created_at: ago(30 * D) },
];

// ── Tools ────────────────────────────────────────────────────────────────────

const tools: Tool[] = [
  { id: uuid(), name: "mind/memory/get", description: "Retrieve a memory value by key name.", instructions: "Use this to read stored memory values. Pass the exact key name.", handler: "brain.tools.handlers:memory_get", input_schema: { type: "object", properties: { key: { type: "string" } }, required: ["key"] }, iam_role_arn: null, enabled: true, metadata: {}, created_at: ago(30 * D), updated_at: ago(2 * D) },
  { id: uuid(), name: "mind/memory/put", description: "Store a value in memory under a key name.", instructions: "Use this to store values. Provide both key and value.", handler: "brain.tools.handlers:memory_put", input_schema: { type: "object", properties: { key: { type: "string" }, value: { type: "string" } }, required: ["key", "value"] }, iam_role_arn: null, enabled: true, metadata: {}, created_at: ago(30 * D), updated_at: ago(2 * D) },
  { id: uuid(), name: "mind/event/send", description: "Send an event to the event bus.", instructions: "Use this to emit events that can trigger other programs.", handler: "brain.tools.handlers:event_send", input_schema: { type: "object", properties: { event_type: { type: "string" }, payload: { type: "object" } }, required: ["event_type"] }, iam_role_arn: null, enabled: true, metadata: {}, created_at: ago(30 * D), updated_at: ago(5 * D) },
  { id: uuid(), name: "channels/gmail/check", description: "Check Gmail inbox for messages.", instructions: "Search Gmail for messages. Returns recent messages matching the query.", handler: "brain.tools.handlers:gmail_check", input_schema: { type: "object", properties: { query: { type: "string" }, max_results: { type: "integer" } } }, iam_role_arn: "arn:aws:iam::123456789:role/cogent-ovo-tool-gmail", enabled: true, metadata: {}, created_at: ago(20 * D), updated_at: ago(1 * D) },
  { id: uuid(), name: "channels/gmail/send", description: "Send an email via Gmail.", instructions: "Send an email. Requires to, subject, and body.", handler: "brain.tools.handlers:gmail_send", input_schema: { type: "object", properties: { to: { type: "string" }, subject: { type: "string" }, body: { type: "string" } }, required: ["to", "subject", "body"] }, iam_role_arn: "arn:aws:iam::123456789:role/cogent-ovo-tool-gmail", enabled: false, metadata: {}, created_at: ago(20 * D), updated_at: ago(1 * D) },
];

// ── Export ───────────────────────────────────────────────────────────────────

export const MOCK_DATA: DashboardData = {
  status,
  programs,
  sessions,
  events,
  triggers,
  memory,
  tasks,
  channels,
  alerts,
  crons,
  resources,
  tools,
};
