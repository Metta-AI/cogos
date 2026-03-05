"use client";
import type { DashboardData } from "@/lib/types";
import { StatCard } from "@/components/shared/StatCard";
import { Badge } from "@/components/shared/Badge";
import { fmtRelative, fmtNum } from "@/lib/format";

interface Props {
  data: DashboardData;
}

export function OverviewPanel({ data }: Props) {
  const s = data.status;

  return (
    <div>
      {/* Stat grid */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3 mb-5">
        <StatCard value={s?.active_sessions ?? 0} label="Active Sessions" variant="accent" />
        <StatCard value={s?.trigger_count ?? 0} label="Triggers" />
        <StatCard value={s?.unresolved_alerts ?? 0} label="Alerts" variant={(s?.unresolved_alerts ?? 0) > 0 ? "error" : "default"} />
        <StatCard value={s?.recent_events ?? 0} label="Recent Events" />
      </div>

      {/* Two-column layout for recent events and top programs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
