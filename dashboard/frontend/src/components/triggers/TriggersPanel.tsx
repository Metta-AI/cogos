"use client";

import { useState, useCallback, useMemo } from "react";
import type { Trigger } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { toggleTriggers } from "@/lib/api";
import { fmtNum } from "@/lib/format";

interface TriggersPanelProps {
  triggers: Trigger[];
  cogentName: string;
}

function groupByPrefix(triggers: Trigger[]): Record<string, Trigger[]> {
  const groups: Record<string, Trigger[]> = {};
  for (const t of triggers) {
    const dotIdx = t.name.indexOf(".");
    const prefix = dotIdx > 0 ? t.name.slice(0, dotIdx) : "other";
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push(t);
  }
  return groups;
}

export function TriggersPanel({ triggers, cogentName }: TriggersPanelProps) {
  const groups = useMemo(() => groupByPrefix(triggers), [triggers]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [toggling, setToggling] = useState<Set<string>>(new Set());

  const toggleCollapse = useCallback((group: string) => {
    setCollapsed((c) => ({ ...c, [group]: !c[group] }));
  }, []);

  const handleBulkToggle = useCallback(
    async (groupTriggers: Trigger[], enabled: boolean) => {
      const ids = groupTriggers.map((t) => t.id);
      setToggling((s) => {
        const next = new Set(s);
        ids.forEach((id) => next.add(id));
        return next;
      });
      try {
        await toggleTriggers(cogentName, ids, enabled);
      } finally {
        setToggling((s) => {
          const next = new Set(s);
          ids.forEach((id) => next.delete(id));
          return next;
        });
      }
    },
    [cogentName],
  );

  const handleSingleToggle = useCallback(
    async (trigger: Trigger) => {
      setToggling((s) => new Set(s).add(trigger.id));
      try {
        await toggleTriggers(cogentName, [trigger.id], !trigger.enabled);
      } finally {
        setToggling((s) => {
          const next = new Set(s);
          next.delete(trigger.id);
          return next;
        });
      }
    },
    [cogentName],
  );

  if (triggers.length === 0) {
    return (
      <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
        No triggers configured
      </div>
    );
  }

  const sortedGroups = Object.keys(groups).sort();

  return (
    <div className="space-y-3">
      {sortedGroups.map((group) => {
        const items = groups[group];
        const isCollapsed = collapsed[group] ?? false;
        const allEnabled = items.every((t) => t.enabled);
        const anyToggling = items.some((t) => toggling.has(t.id));

        return (
          <div
            key={group}
            className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden"
          >
            {/* Group header */}
            <div
              className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
              onClick={() => toggleCollapse(group)}
            >
              <span className="text-[var(--text-muted)] text-[10px]">
                {isCollapsed ? "\u25B6" : "\u25BC"}
              </span>
              <span className="text-[13px] font-semibold text-[var(--text-primary)] flex-1">
                {group}
                <span className="text-[var(--text-muted)] font-normal ml-2 text-[11px]">
                  ({items.length})
                </span>
              </span>
              <label
                className="flex items-center gap-2"
                onClick={(e) => e.stopPropagation()}
              >
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">
                  All
                </span>
                <ToggleSwitch
                  checked={allEnabled}
                  disabled={anyToggling}
                  onChange={() => handleBulkToggle(items, !allEnabled)}
                />
              </label>
            </div>

            {/* Trigger rows */}
            {!isCollapsed && (
              <div className="border-t border-[var(--border)]">
                <table className="w-full text-left text-[12px]">
                  <thead>
                    <tr className="border-b border-[var(--border)]">
                      <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                        Name
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                        Type
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                        Pattern / Cron
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        Priority
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-center">
                        Enabled
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        1m
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        5m
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        1h
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        24h
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((t) => (
                      <tr
                        key={t.id}
                        className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                      >
                        <td className="px-4 py-2 font-mono text-[var(--text-secondary)]">
                          {t.name}
                        </td>
                        <td className="px-3 py-2">
                          <Badge variant="info">{t.trigger_type ?? "unknown"}</Badge>
                        </td>
                        <td className="px-3 py-2 font-mono text-[var(--text-muted)] max-w-[200px] truncate">
                          {t.event_pattern ?? t.cron_expression ?? "--"}
                        </td>
                        <td className="px-3 py-2 font-mono text-[var(--text-secondary)] text-right">
                          {t.priority ?? "--"}
                        </td>
                        <td className="px-3 py-2 text-center">
                          <ToggleSwitch
                            checked={t.enabled}
                            disabled={toggling.has(t.id)}
                            onChange={() => handleSingleToggle(t)}
                          />
                        </td>
                        <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                          {fmtNum(t.fired_1m)}
                        </td>
                        <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                          {fmtNum(t.fired_5m)}
                        </td>
                        <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                          {fmtNum(t.fired_1h)}
                        </td>
                        <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                          {fmtNum(t.fired_24h)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- Toggle switch ---------- */

function ToggleSwitch({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className="relative inline-flex items-center h-[18px] w-[32px] rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-40"
      style={{
        background: checked ? "var(--accent)" : "var(--bg-elevated)",
        border: "1px solid var(--border)",
      }}
    >
      <span
        className="inline-block h-[14px] w-[14px] rounded-full bg-white transition-transform duration-200"
        style={{
          transform: checked ? "translateX(14px)" : "translateX(1px)",
        }}
      />
    </button>
  );
}
