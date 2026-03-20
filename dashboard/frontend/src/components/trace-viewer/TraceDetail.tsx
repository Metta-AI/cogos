"use client";

import React, { useState, useMemo } from "react";
import { TimelineView } from "./TimelineView";
import { GraphView } from "./GraphView";
import { SpanDetail } from "./SpanDetail";
import type { SpanData } from "./SpanDetail";

export interface TraceData {
  id: string;
  cogent_id: string;
  source: string;
  source_ref: string | null;
  created_at: string | null;
  spans: SpanData[];
  summary: {
    total_duration_ms: number | null;
    total_spans: number;
    error_count: number;
    total_tokens_in: number;
    total_tokens_out: number;
    total_cost_usd: number;
  };
}

type ViewMode = "timeline" | "graph";

interface TraceDetailProps {
  trace: TraceData;
  compact?: boolean;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function TraceDetail({ trace, compact }: TraceDetailProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("timeline");
  const [selectedSpan, setSelectedSpan] = useState<SpanData | null>(null);

  const traceStartMs = useMemo(
    () =>
      trace.spans
        .filter((s) => s.started_at)
        .reduce((min, s) => Math.min(min, new Date(s.started_at!).getTime()), Infinity),
    [trace.spans],
  );

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Summary bar */}
        <div
          className={`flex items-center gap-${compact ? "4" : "6"} mb-3 px-3 py-2 bg-white/5 border border-white/10 rounded text-xs`}
        >
          <SummaryItem label="Duration" value={formatDuration(trace.summary.total_duration_ms)} />
          <SummaryItem label="Spans" value={String(trace.summary.total_spans)} />
          <SummaryItem
            label="Errors"
            value={String(trace.summary.error_count)}
            highlight={trace.summary.error_count > 0}
          />
          {!compact && (
            <>
              <SummaryItem
                label="Tokens"
                value={`${trace.summary.total_tokens_in} in / ${trace.summary.total_tokens_out} out`}
              />
              <SummaryItem
                label="Cost"
                value={`$${trace.summary.total_cost_usd.toFixed(4)}`}
              />
            </>
          )}
          <div className="flex-1" />
          <span className="text-white/30 font-mono text-[10px] truncate max-w-48" title={trace.id}>
            {trace.id}
          </span>
        </div>

        {/* View toggle */}
        <div className="flex items-center gap-1 mb-3">
          <ToggleButton active={viewMode === "timeline"} onClick={() => setViewMode("timeline")} label="Timeline" />
          <ToggleButton active={viewMode === "graph"} onClick={() => setViewMode("graph")} label="Graph" />
        </div>

        {/* View */}
        <div className="flex-1 overflow-auto border border-white/10 rounded bg-[#050505]">
          {viewMode === "timeline" ? (
            <TimelineView
              spans={trace.spans}
              traceStartMs={traceStartMs}
              totalDurationMs={trace.summary.total_duration_ms ?? 0}
              selectedSpanId={selectedSpan?.id ?? null}
              onSelectSpan={setSelectedSpan}
            />
          ) : (
            <GraphView
              spans={trace.spans}
              selectedSpanId={selectedSpan?.id ?? null}
              onSelectSpan={setSelectedSpan}
            />
          )}
        </div>
      </div>

      {selectedSpan && <SpanDetail span={selectedSpan} onClose={() => setSelectedSpan(null)} />}
    </div>
  );
}

function SummaryItem({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-white/40">{label}:</span>
      <span className={highlight ? "text-red-400 font-medium" : "text-white/70"}>{value}</span>
    </div>
  );
}

function ToggleButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 text-xs rounded transition-colors cursor-pointer ${
        active
          ? "bg-white/15 text-white border border-white/20"
          : "bg-transparent text-white/40 border border-transparent hover:text-white/60"
      }`}
    >
      {label}
    </button>
  );
}
