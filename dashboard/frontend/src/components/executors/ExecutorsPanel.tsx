"use client";

import type { CogosExecutor, CogosRun } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { StatCard } from "@/components/shared/StatCard";
import { TokenManager } from "@/components/executors/TokenManager";
import { fmtRelative, fmtTimestamp } from "@/lib/format";

interface ExecutorsPanelProps {
  executors: CogosExecutor[];
  runs: CogosRun[];
  cogentName: string;
}

type StatusVariant = "success" | "accent" | "warning" | "error" | "neutral";

const STATUS_VARIANT: Record<string, StatusVariant> = {
  idle: "success",
  busy: "accent",
  stale: "warning",
  dead: "error",
};

function statusVariant(status: string): StatusVariant {
  return STATUS_VARIANT[status] ?? "neutral";
}

function HeartbeatIndicator({ lastHeartbeat }: { lastHeartbeat: string | null }) {
  if (!lastHeartbeat) return <span className="text-[var(--text-muted)]">--</span>;

  const diffMs = Date.now() - new Date(lastHeartbeat.endsWith("Z") ? lastHeartbeat : lastHeartbeat + "Z").getTime();
  const isHealthy = diffMs < 90_000; // 3 * 30s
  const isStale = diffMs >= 90_000 && diffMs < 300_000;

  return (
    <span
      className="inline-flex items-center gap-1 text-[11px]"
      title={fmtTimestamp(lastHeartbeat)}
    >
      <span
        className="inline-block w-[6px] h-[6px] rounded-full"
        style={{
          backgroundColor: isHealthy
            ? "var(--success)"
            : isStale
              ? "var(--warning)"
              : "var(--error)",
        }}
      />
      {fmtRelative(lastHeartbeat)}
    </span>
  );
}

function RunInfo({ runId, runs }: { runId: string | null; runs: CogosRun[] }) {
  if (!runId) return <span className="text-[var(--text-muted)]">--</span>;
  const run = runs.find((r) => r.id === runId);
  if (!run) return <span className="font-mono text-[10px] text-[var(--text-muted)]">{runId.slice(0, 8)}</span>;

  return (
    <span className="inline-flex items-center gap-1.5">
      <Badge variant={run.status === "running" ? "accent" : run.status === "completed" ? "success" : "error"}>
        {run.status}
      </Badge>
      <span className="text-[var(--text-secondary)]">{run.process_name ?? runId.slice(0, 8)}</span>
    </span>
  );
}

function CapabilityTags({ capabilities }: { capabilities: string[] }) {
  if (!capabilities.length) return <span className="text-[var(--text-muted)]">none</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {capabilities.map((cap) => (
        <span
          key={cap}
          className="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono bg-[var(--bg-hover)] text-[var(--text-muted)]"
        >
          {cap}
        </span>
      ))}
    </div>
  );
}

function findRecentRuns(executorId: string, runs: CogosRun[], limit = 3): CogosRun[] {
  // Find runs that were assigned to this executor (via metadata or just recent runs)
  // Since runs don't track executor_id directly, show most recent runs for context
  return runs
    .filter((r) => r.status !== "running")
    .slice(0, limit);
}

export function ExecutorsPanel({ executors = [], runs = [], cogentName }: ExecutorsPanelProps) {
  const idle = executors.filter((e) => e.status === "idle");
  const busy = executors.filter((e) => e.status === "busy");
  const stale = executors.filter((e) => e.status === "stale");
  const dead = executors.filter((e) => e.status === "dead");
  const active = executors.filter((e) => e.status === "idle" || e.status === "busy");

  // Recent completed runs (for "recently finished" section)
  const recentRuns = runs
    .filter((r) => r.runner === "channel" || busy.some((e) => e.current_run_id === r.id))
    .filter((r) => r.status !== "running")
    .slice(0, 10);

  return (
    <div className="space-y-5">
      {/* Token Management */}
      <TokenManager cogentName={cogentName} />

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-3">
        <StatCard value={executors.length} label="Total Executors" />
        <StatCard value={idle.length} label="Idle" variant="default" />
        <StatCard value={busy.length} label="Busy" variant={busy.length > 0 ? "accent" : "default"} />
        <StatCard value={stale.length} label="Stale" variant={stale.length > 0 ? "warning" : "default"} />
        <StatCard value={dead.length} label="Dead" variant={dead.length > 0 ? "error" : "default"} />
      </div>

      {/* Active Executors (busy first, then idle) */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
        <div className="px-4 py-2.5 border-b border-[var(--border)]">
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">
            Active Executors
          </span>
          <span className="text-[11px] text-[var(--text-muted)] ml-2">
            ({active.length})
          </span>
        </div>

        {active.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13px] text-[var(--text-muted)]">
            No active executors registered
          </div>
        ) : (
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Executor
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Status
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Heartbeat
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Current Run
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Capabilities
                </th>
              </tr>
            </thead>
            <tbody>
              {[...busy, ...idle].map((e) => (
                <tr
                  key={e.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                >
                  <td className="px-4 py-2.5">
                    <div className="font-mono text-[var(--text-secondary)]">{e.executor_id}</div>
                    <div className="text-[10px] text-[var(--text-muted)] mt-0.5">
                      {e.channel_type} &middot; registered {fmtRelative(e.registered_at)}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge variant={statusVariant(e.status)}>{e.status}</Badge>
                  </td>
                  <td className="px-3 py-2.5">
                    <HeartbeatIndicator lastHeartbeat={e.last_heartbeat_at} />
                  </td>
                  <td className="px-3 py-2.5">
                    <RunInfo runId={e.current_run_id} runs={runs} />
                  </td>
                  <td className="px-3 py-2.5">
                    <CapabilityTags capabilities={e.capabilities} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Stale / Dead Executors */}
      {(stale.length > 0 || dead.length > 0) && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
          <div className="px-4 py-2.5 border-b border-[var(--border)]">
            <span className="text-[13px] font-semibold text-[var(--text-primary)]">
              Unhealthy Executors
            </span>
            <span className="text-[11px] text-[var(--text-muted)] ml-2">
              ({stale.length + dead.length})
            </span>
          </div>
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Executor
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Status
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Last Heartbeat
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Registered
                </th>
              </tr>
            </thead>
            <tbody>
              {[...stale, ...dead].map((e) => (
                <tr
                  key={e.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                  style={{ opacity: e.status === "dead" ? 0.5 : 0.75 }}
                >
                  <td className="px-4 py-2 font-mono text-[var(--text-muted)]">{e.executor_id}</td>
                  <td className="px-3 py-2">
                    <Badge variant={statusVariant(e.status)}>{e.status}</Badge>
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)]">
                    <HeartbeatIndicator lastHeartbeat={e.last_heartbeat_at} />
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)]">
                    {fmtTimestamp(e.registered_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent Channel Runs */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
        <div className="px-4 py-2.5 border-b border-[var(--border)]">
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">
            Recent Channel Runs
          </span>
          <span className="text-[11px] text-[var(--text-muted)] ml-2">
            (last {recentRuns.length})
          </span>
        </div>

        {recentRuns.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13px] text-[var(--text-muted)]">
            No recent channel runs
          </div>
        ) : (
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Process
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Status
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Tokens In
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Tokens Out
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Duration
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Completed
                </th>
              </tr>
            </thead>
            <tbody>
              {recentRuns.map((r) => (
                <tr
                  key={r.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                >
                  <td className="px-4 py-2 text-[var(--text-secondary)]">
                    {r.process_name ?? r.process.slice(0, 8)}
                  </td>
                  <td className="px-3 py-2">
                    <Badge
                      variant={
                        r.status === "completed" ? "success" :
                        r.status === "failed" ? "error" :
                        r.status === "timeout" ? "warning" :
                        "neutral"
                      }
                    >
                      {r.status}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-muted)] tabular-nums">
                    {r.tokens_in?.toLocaleString() ?? "--"}
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-muted)] tabular-nums">
                    {r.tokens_out?.toLocaleString() ?? "--"}
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-muted)] tabular-nums">
                    {r.duration_ms != null
                      ? r.duration_ms < 1000
                        ? `${r.duration_ms}ms`
                        : `${(r.duration_ms / 1000).toFixed(1)}s`
                      : "--"}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)]">
                    {fmtRelative(r.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
