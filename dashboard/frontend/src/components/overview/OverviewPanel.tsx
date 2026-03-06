"use client";
import type { DashboardData } from "@/lib/types";
import { StatCard } from "@/components/shared/StatCard";
import { Badge } from "@/components/shared/Badge";
import { fmtRelative, fmtNum } from "@/lib/format";

interface Props {
  data: DashboardData;
}

const TASK_STATUS_VARIANT: Record<string, "accent" | "info" | "success" | "neutral" | "error" | "warning"> = {
  running: "accent",
  runnable: "info",
  completed: "success",
  disabled: "neutral",
  failed: "error",
  timeout: "warning",
};

export function OverviewPanel({ data }: Props) {
  const s = data.status;
  const tasksByStatus = data.tasks.reduce<Record<string, number>>((acc, t) => {
    const key = t.status || "unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const runningTasks = data.tasks.filter((t) => t.status === "running");
  const runnableTasks = data.tasks.filter((t) => t.status === "runnable");

  return (
    <div>
      {/* Stat grid */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3 mb-5">
        <StatCard value={s ? s.active_sessions : null} label="Active Sessions" variant="accent" />
        <StatCard value={data.tasks.length || null} label="Tasks" />
        <StatCard value={s ? s.trigger_count : null} label="Triggers" />
        <StatCard value={s ? s.unresolved_alerts : null} label="Alerts" variant={(s?.unresolved_alerts ?? 0) > 0 ? "error" : "default"} />
        <StatCard value={s ? s.recent_events : null} label="Recent Events" />
      </div>

      {/* Three-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Tasks */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">Tasks</h3>
          {data.tasks.length > 0 ? (
            <>
              <div className="flex flex-wrap gap-1.5 mb-3">
                {Object.entries(tasksByStatus).map(([status, count]) => (
                  <Badge key={status} variant={TASK_STATUS_VARIANT[status] || "neutral"}>
                    {count} {status}
                  </Badge>
                ))}
              </div>
              {runningTasks.length > 0 && (
                <div className="mb-2">
                  <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Running</div>
                  {runningTasks.slice(0, 3).map((t) => (
                    <div key={t.id} className="flex items-center gap-2 py-1 text-xs">
                      <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--accent)]" style={{ animation: "pulse-dot 1.5s ease-in-out infinite" }} />
                      <span className="text-[var(--text-primary)] font-mono truncate">{t.name}</span>
                      {t.updated_at && <span className="text-[var(--text-muted)] ml-auto">{fmtRelative(t.updated_at)}</span>}
                    </div>
                  ))}
                </div>
              )}
              {runnableTasks.length > 0 && runningTasks.length === 0 && (
                <div>
                  <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Runnable</div>
                  {runnableTasks.slice(0, 5).map((t) => (
                    <div key={t.id} className="flex items-center gap-2 py-1 text-xs">
                      <span className="text-[var(--text-primary)] font-mono truncate">{t.name}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="text-[var(--text-muted)] text-xs py-2">No tasks</div>
          )}
        </div>

        {/* Recent events */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">Recent Events</h3>
          {data.events.slice(0, 5).map((e, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5 text-xs">
              <Badge variant="info">{e.event_type || "unknown"}</Badge>
              <span className="text-[var(--text-secondary)] font-mono truncate">{e.source}</span>
              <span className="text-[var(--text-muted)] ml-auto">{fmtRelative(e.created_at)}</span>
            </div>
          ))}
          {data.events.length === 0 && (
            <div className="text-[var(--text-muted)] text-xs py-2">No recent events</div>
          )}
        </div>

        {/* Top programs */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">Top Programs</h3>
          {[...data.programs].sort((a, b) => b.runs - a.runs).slice(0, 5).map((p, i) => (
            <div key={i} className="flex items-center gap-3 py-1.5 text-xs">
              <span className="text-[var(--text-primary)] font-medium truncate flex-1">{p.name}</span>
              <span className="text-[var(--text-secondary)] font-mono">{fmtNum(p.runs)} runs</span>
              <span className="text-green-400 font-mono">{p.runs > 0 ? Math.round((p.ok / p.runs) * 100) : 0}%</span>
            </div>
          ))}
          {data.programs.length === 0 && (
            <div className="text-[var(--text-muted)] text-xs py-2">No programs</div>
          )}
        </div>
      </div>
    </div>
  );
}
