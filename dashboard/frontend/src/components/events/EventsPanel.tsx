"use client";

import { useState, useMemo, useCallback } from "react";
import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { fmtRelative, timeRangeToMs } from "@/lib/format";
import type { DashboardEvent, Trigger, TimeRange } from "@/lib/types";
import { EventTree } from "./EventTree";

interface EventsPanelProps {
  events: DashboardEvent[];
  cogentName: string;
  triggers: Trigger[];
  timeRange: TimeRange;
  onTabChange?: (tab: string) => void;
}

export function EventsPanel({ events, cogentName, triggers, timeRange, onTabChange }: EventsPanelProps) {
  const [expandedId, setExpandedId] = useState<string | number | null>(null);
  const [treeId, setTreeId] = useState<string | number | null>(null);

  // Filter events by time range
  const filteredEvents = useMemo(() => {
    const cutoff = Date.now() - timeRangeToMs(timeRange);
    return events.filter((e) => {
      if (!e.created_at) return true;
      return new Date(e.created_at).getTime() >= cutoff;
    });
  }, [events, timeRange]);

  // Build trigger lookup: event_pattern -> program_name[]
  const triggerMap = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const t of triggers) {
      if (t.event_pattern && t.program_name && t.enabled) {
        if (!map[t.event_pattern]) map[t.event_pattern] = [];
        map[t.event_pattern].push(t.program_name);
      }
    }
    return map;
  }, [triggers]);

  const getMatchingPrograms = useCallback((eventType: string | null): string[] => {
    if (!eventType) return [];
    const programs: string[] = [];
    for (const [pattern, progs] of Object.entries(triggerMap)) {
      // Simple glob match: pattern may use * as wildcard
      const regex = new RegExp("^" + pattern.replace(/\*/g, ".*") + "$");
      if (regex.test(eventType)) {
        programs.push(...progs);
      }
    }
    return [...new Set(programs)];
  }, [triggerMap]);

  const toggleExpand = useCallback((id: string | number) => {
    setExpandedId((prev) => (prev === id ? null : id));
    setTreeId(null);
  }, []);

  return (
    <div>
      <div className="text-[var(--text-muted)] text-xs mb-3">
        {filteredEvents.length}/{events.length} event{events.length !== 1 ? "s" : ""}
      </div>

      {filteredEvents.length === 0 && (
        <div className="text-[var(--text-muted)] text-xs py-8 text-center">No events</div>
      )}

      <div className="rounded-md overflow-hidden" style={{ border: filteredEvents.length ? "1px solid var(--border)" : "none" }}>
        {filteredEvents.length > 0 && (
          <div
            className="grid items-center px-3 py-1.5 text-[10px] uppercase tracking-wide font-medium text-[var(--text-muted)]"
            style={{ gridTemplateColumns: "minmax(120px, 1fr) minmax(100px, 2fr) minmax(80px, 1fr) 60px", background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}
          >
            <span>Event</span>
            <span>Content</span>
            <span>Triggers</span>
            <span className="text-right">Time</span>
          </div>
        )}
        {filteredEvents.map((evt) => {
          const isExpanded = expandedId === evt.id;
          const matchedPrograms = getMatchingPrograms(evt.event_type);

          return (
            <div key={evt.id}>
              <div
                className="grid items-center px-3 py-2 cursor-pointer transition-colors"
                style={{
                  gridTemplateColumns: "minmax(120px, 1fr) minmax(100px, 2fr) minmax(80px, 1fr) 60px",
                  background: isExpanded ? "var(--bg-hover)" : "var(--bg-surface)",
                  borderBottom: "1px solid var(--border)",
                }}
                onClick={() => toggleExpand(evt.id)}
                onMouseEnter={(e) => {
                  if (!isExpanded) e.currentTarget.style.background = "var(--bg-hover)";
                }}
                onMouseLeave={(e) => {
                  if (!isExpanded) e.currentTarget.style.background = "var(--bg-surface)";
                }}
              >
                <span><Badge variant="accent">{evt.event_type ?? "event"}</Badge></span>
                <span className="text-[11px] text-[var(--text-secondary)] truncate">
                  {evt.source ?? (evt.payload ? JSON.stringify(evt.payload).slice(0, 60) : "--")}
                </span>
                <span className="flex gap-1 flex-wrap">
                  {matchedPrograms.map((p) => (
                    <span
                      key={p}
                      className="font-mono text-[10px] px-1.5 py-0.5 rounded text-[var(--info)] cursor-pointer hover:underline"
                      style={{ background: "rgba(59,130,246,0.1)" }}
                      onClick={(e) => { e.stopPropagation(); onTabChange?.("programs"); }}
                    >
                      {p}
                    </span>
                  ))}
                </span>
                <span className="text-[10px] text-[var(--text-muted)] text-right">{fmtRelative(evt.created_at)}</span>
              </div>

              {isExpanded && (
                <div
                  className="px-4 py-3 space-y-2"
                  style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}
                >
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
                    <span className="text-[var(--text-muted)]">id: <span className="font-mono text-[var(--text-secondary)]">{String(evt.id)}</span></span>
                    <span className="text-[var(--text-muted)]">type: <span className="font-mono text-[var(--text-secondary)]">{evt.event_type ?? "--"}</span></span>
                    {evt.source && <span className="text-[var(--text-muted)]">source: <span className="text-[var(--text-secondary)]">{evt.source}</span></span>}
                    {evt.parent_event_id != null && <span className="text-[var(--text-muted)]">parent: <span className="font-mono text-[var(--text-secondary)]">{evt.parent_event_id}</span></span>}
                    <span className="text-[var(--text-muted)]">created: <span className="text-[var(--text-secondary)]">{fmtRelative(evt.created_at)}</span></span>
                  </div>

                  {matchedPrograms.length > 0 && (
                    <div className="flex items-center gap-1.5 text-[10px]">
                      <span className="text-[var(--text-muted)]">triggers:</span>
                      {matchedPrograms.map((p) => (
                        <span
                          key={p}
                          className="font-mono px-1.5 py-0.5 rounded text-[var(--info)] cursor-pointer hover:underline"
                          style={{ background: "rgba(59,130,246,0.1)" }}
                          onClick={(e) => { e.stopPropagation(); onTabChange?.("programs"); }}
                        >
                          {p}
                        </span>
                      ))}
                    </div>
                  )}

                  <JsonViewer data={evt.payload} />

                  {evt.parent_event_id != null && treeId !== evt.id && (
                    <button
                      onClick={(e) => { e.stopPropagation(); setTreeId(evt.id); }}
                      className="px-3 py-1 text-[12px] rounded bg-[var(--bg-surface)] border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-active)] transition-colors cursor-pointer"
                    >
                      View Tree
                    </button>
                  )}
                  {treeId === evt.id && (
                    <div className="mt-2">
                      <EventTree eventId={evt.id} cogentName={cogentName} />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
