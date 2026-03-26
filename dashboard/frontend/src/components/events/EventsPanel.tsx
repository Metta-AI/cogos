"use client";

import { useState } from "react";
import type { CogosChannel, CogosHandler, CronItem, MessageTrace, TimeRange } from "@/lib/types";
import { HandlersTab } from "./HandlersTab";
import { CronTab } from "./CronTab";
import { TracePanel } from "@/components/traces/TracePanel";
import { TraceViewerPanel } from "@/components/trace-viewer/TraceViewerPanel";

interface EventsPanelProps {
  handlers: CogosHandler[];
  crons: CronItem[];
  traces: MessageTrace[];
  channels: CogosChannel[];
  cogentName: string;
  timeRange: TimeRange;
  onRefresh: () => void;
  initialTraceId?: string;
}

type SubTab = "handlers" | "cron" | "trace" | "viewer";

export function EventsPanel({ handlers, crons, traces, channels, cogentName, timeRange, onRefresh, initialTraceId }: EventsPanelProps) {
  const [subTab, setSubTab] = useState<SubTab>(initialTraceId ? "viewer" : "handlers");

  const tabStyle = (active: boolean): React.CSSProperties => ({
    fontSize: "11px",
    fontFamily: "var(--font-mono)",
    fontWeight: active ? 600 : 400,
    padding: "4px 12px",
    background: "transparent",
    border: "none",
    borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
    color: active ? "var(--accent)" : "var(--text-muted)",
    cursor: "pointer",
  });

  return (
    <div>
      <div className="flex items-center gap-0 mb-4" style={{ borderBottom: "1px solid var(--border)" }}>
        <button style={tabStyle(subTab === "handlers")} onClick={() => setSubTab("handlers")}>
          Handlers ({handlers.length})
        </button>
        <button style={tabStyle(subTab === "cron")} onClick={() => setSubTab("cron")}>
          Cron ({crons.length})
        </button>
        <button style={tabStyle(subTab === "trace")} onClick={() => setSubTab("trace")}>
          Trace ({traces.length})
        </button>
        <button style={tabStyle(subTab === "viewer")} onClick={() => setSubTab("viewer")}>
          Trace Viewer
        </button>
      </div>
      {subTab === "handlers" && <HandlersTab handlers={handlers} />}
      {subTab === "cron" && <CronTab crons={crons} cogentName={cogentName} onRefresh={onRefresh} />}
      {subTab === "trace" && <TracePanel traces={traces} cogentName={cogentName} timeRange={timeRange} onRefresh={onRefresh} preloadedChannels={channels} />}
      {subTab === "viewer" && <TraceViewerPanel cogentName={cogentName} initialTraceId={initialTraceId} />}
    </div>
  );
}
