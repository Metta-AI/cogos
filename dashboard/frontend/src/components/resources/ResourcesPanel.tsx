"use client";

import type { DashboardData } from "@/lib/types";
import { StatCard } from "@/components/shared/StatCard";

interface ResourcesPanelProps {
  data: DashboardData;
}

export function ResourcesPanel({ data }: ResourcesPanelProps) {
  const activeSessions = data.status?.active_sessions ?? 0;
  const sessions = data.sessions ?? [];

  return (
    <div className="space-y-5">
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <StatCard
          value={activeSessions}
          label="Active Sessions"
          variant={activeSessions > 0 ? "accent" : "default"}
        />
      </div>

      {/* Active conversations */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
        <div className="px-4 py-2.5 border-b border-[var(--border)]">
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">
            Active Conversations
          </span>
          <span className="text-[11px] text-[var(--text-muted)] ml-2">
            ({sessions.length})
          </span>
        </div>

        {sessions.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13px] text-[var(--text-muted)]">
            No active conversations
          </div>
        ) : (
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  ID
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Context Key
                </th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr
                  key={s.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-[var(--text-secondary)]">
                    {s.id}
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--text-muted)]">
                    {s.context_key ?? "--"}
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
