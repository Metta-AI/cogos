"use client";

import type { Resource } from "@/lib/types";
import { StatCard } from "@/components/shared/StatCard";

interface ResourcesPanelProps {
  resources: Resource[];
}

function UsageBar({ used, capacity, type }: { used: number; capacity: number; type: string }) {
  const pct = capacity > 0 ? Math.min((used / capacity) * 100, 100) : 0;
  const isHigh = pct >= 80;
  const isFull = pct >= 100;

  return (
    <div className="flex items-center gap-2 min-w-[140px]">
      <div className="flex-1 h-[6px] rounded-full bg-[var(--bg-hover)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pct}%`,
            backgroundColor: isFull
              ? "var(--error)"
              : isHigh
                ? "var(--warning)"
                : "var(--accent)",
          }}
        />
      </div>
      <span className="text-[11px] text-[var(--text-muted)] tabular-nums whitespace-nowrap">
        {type === "pool"
          ? `${used} / ${capacity}`
          : `${formatNumber(used)} / ${formatNumber(capacity)}`}
      </span>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  if (n % 1 !== 0) return n.toFixed(2);
  return String(n);
}

export function ResourcesPanel({ resources = [] }: ResourcesPanelProps) {
  const pools = resources.filter((r) => r.resource_type === "pool");
  const consumables = resources.filter((r) => r.resource_type === "consumable");
  const totalCapacity = pools.reduce((s, r) => s + r.capacity, 0);
  const totalUsed = pools.reduce((s, r) => s + r.used, 0);

  return (
    <div className="space-y-5">
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <StatCard value={resources.length} label="Total Resources" />
        <StatCard
          value={pools.length}
          label="Pool Resources"
          variant={totalUsed >= totalCapacity && totalCapacity > 0 ? "warning" : "default"}
        />
        <StatCard value={consumables.length} label="Consumable Resources" />
      </div>

      {/* Pool resources */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
        <div className="px-4 py-2.5 border-b border-[var(--border)]">
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">
            Pool Resources
          </span>
          <span className="text-[11px] text-[var(--text-muted)] ml-2">
            ({pools.length})
          </span>
        </div>

        {pools.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13px] text-[var(--text-muted)]">
            No pool resources
          </div>
        ) : (
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Name
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Usage
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Description
                </th>
              </tr>
            </thead>
            <tbody>
              {pools.map((r) => (
                <tr
                  key={r.name}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-[var(--text-secondary)]">
                    {r.name}
                  </td>
                  <td className="px-3 py-2">
                    <UsageBar used={r.used} capacity={r.capacity} type="pool" />
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)]">
                    {(r.metadata as Record<string, string>)?.description ?? "--"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Consumable resources */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
        <div className="px-4 py-2.5 border-b border-[var(--border)]">
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">
            Consumable Resources
          </span>
          <span className="text-[11px] text-[var(--text-muted)] ml-2">
            ({consumables.length})
          </span>
        </div>

        {consumables.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13px] text-[var(--text-muted)]">
            No consumable resources
          </div>
        ) : (
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Name
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Usage
                </th>
                <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                  Description
                </th>
              </tr>
            </thead>
            <tbody>
              {consumables.map((r) => (
                <tr
                  key={r.name}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-[var(--text-secondary)]">
                    {r.name}
                  </td>
                  <td className="px-3 py-2">
                    <UsageBar used={r.used} capacity={r.capacity} type="consumable" />
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)]">
                    {(r.metadata as Record<string, string>)?.description ?? "--"}
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
