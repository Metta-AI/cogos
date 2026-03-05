"use client";

import { useState, useMemo, useCallback } from "react";
import type { MemoryItem } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { fmtRelative } from "@/lib/format";

interface MemoryPanelProps {
  memory: MemoryItem[];
}

interface GroupedMemory {
  [scope: string]: {
    [group: string]: MemoryItem[];
  };
}

function groupMemory(items: MemoryItem[]): GroupedMemory {
  const result: GroupedMemory = {};
  for (const item of items) {
    const scope = item.scope ?? "unknown";
    const group = item.group || "default";
    if (!result[scope]) result[scope] = {};
    if (!result[scope][group]) result[scope][group] = [];
    result[scope][group].push(item);
  }
  return result;
}

function tryParseJSON(str: string): unknown | null {
  try {
    const parsed = JSON.parse(str);
    if (typeof parsed === "object" && parsed !== null) return parsed;
    return null;
  } catch {
    return null;
  }
}

function MemoryContent({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);
  const parsed = useMemo(() => tryParseJSON(content), [content]);

  if (parsed) {
    if (!expanded) {
      return (
        <button
          onClick={() => setExpanded(true)}
          className="text-[11px] text-[var(--accent)] hover:underline bg-transparent border-0 cursor-pointer p-0"
        >
          Show JSON
        </button>
      );
    }
    return (
      <div className="mt-1">
        <button
          onClick={() => setExpanded(false)}
          className="text-[11px] text-[var(--accent)] hover:underline bg-transparent border-0 cursor-pointer p-0 mb-1"
        >
          Hide JSON
        </button>
        <JsonViewer data={parsed} />
      </div>
    );
  }

  const truncated = content.length > 200;
  if (!truncated || expanded) {
    return (
      <div className="text-[12px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap break-all">
        {content}
        {truncated && (
          <button
            onClick={() => setExpanded(false)}
            className="ml-1 text-[11px] text-[var(--accent)] hover:underline bg-transparent border-0 cursor-pointer p-0"
          >
            less
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="text-[12px] text-[var(--text-secondary)] font-mono">
      {content.slice(0, 200)}...
      <button
        onClick={() => setExpanded(true)}
        className="ml-1 text-[11px] text-[var(--accent)] hover:underline bg-transparent border-0 cursor-pointer p-0"
      >
        more
      </button>
    </div>
  );
}

export function MemoryPanel({ memory }: MemoryPanelProps) {
  const grouped = useMemo(() => groupMemory(memory), [memory]);
  const [collapsedScopes, setCollapsedScopes] = useState<Record<string, boolean>>({});
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});

  const toggleScope = useCallback((scope: string) => {
    setCollapsedScopes((c) => ({ ...c, [scope]: !c[scope] }));
  }, []);

  const toggleGroup = useCallback((key: string) => {
    setCollapsedGroups((c) => ({ ...c, [key]: !c[key] }));
  }, []);

  if (memory.length === 0) {
    return (
      <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
        No memory items
      </div>
    );
  }

  const sortedScopes = Object.keys(grouped).sort();

  return (
    <div className="space-y-3">
      {sortedScopes.map((scope) => {
        const scopeGroups = grouped[scope];
        const isScopeCollapsed = collapsedScopes[scope] ?? false;
        const totalItems = Object.values(scopeGroups).reduce(
          (sum, items) => sum + items.length,
          0,
        );

        return (
          <div
            key={scope}
            className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden"
          >
            {/* Scope header */}
            <div
              className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
              onClick={() => toggleScope(scope)}
            >
              <span className="text-[var(--text-muted)] text-[10px]">
                {isScopeCollapsed ? "\u25B6" : "\u25BC"}
              </span>
              <Badge variant="accent">{scope}</Badge>
              <span className="text-[11px] text-[var(--text-muted)]">
                {totalItems} item{totalItems !== 1 ? "s" : ""}
              </span>
            </div>

            {!isScopeCollapsed && (
              <div className="border-t border-[var(--border)]">
                {Object.keys(scopeGroups)
                  .sort()
                  .map((group) => {
                    const items = scopeGroups[group];
                    const groupKey = `${scope}:${group}`;
                    const isGroupCollapsed = collapsedGroups[groupKey] ?? false;

                    return (
                      <div key={group} className="border-b border-[var(--border)] last:border-0">
                        {/* Group header */}
                        <div
                          className="flex items-center gap-2 px-6 py-2 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
                          onClick={() => toggleGroup(groupKey)}
                        >
                          <span className="text-[var(--text-muted)] text-[9px]">
                            {isGroupCollapsed ? "\u25B6" : "\u25BC"}
                          </span>
                          <span className="text-[12px] text-[var(--text-secondary)] font-medium">
                            {group}
                          </span>
                          <span className="text-[10px] text-[var(--text-muted)]">
                            ({items.length})
                          </span>
                        </div>

                        {/* Items */}
                        {!isGroupCollapsed &&
                          items.map((item) => (
                            <div
                              key={item.id}
                              className="px-8 py-2 border-t border-[var(--border)] hover:bg-[var(--bg-hover)] transition-colors"
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <span className="text-[12px] font-mono text-[var(--text-primary)]">
                                  {item.name}
                                </span>
                                {item.type && (
                                  <Badge variant="neutral">{item.type}</Badge>
                                )}
                                <span className="text-[10px] text-[var(--text-muted)] ml-auto">
                                  {fmtRelative(item.updated_at)}
                                </span>
                              </div>
                              <MemoryContent content={item.content} />
                            </div>
                          ))}
                      </div>
                    );
                  })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
