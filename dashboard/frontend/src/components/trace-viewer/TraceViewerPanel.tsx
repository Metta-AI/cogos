"use client";

import React, { useState, useCallback, useEffect } from "react";
import { getTraceViewer } from "@/lib/api";
import { TraceDetail } from "./TraceDetail";
import type { TraceData } from "./TraceDetail";

interface TraceViewerPanelProps {
  cogentName: string;
  initialTraceId?: string;
}

export function TraceViewerPanel({ cogentName, initialTraceId }: TraceViewerPanelProps) {
  const [traceIdInput, setTraceIdInput] = useState(initialTraceId ?? "");
  const [trace, setTrace] = useState<TraceData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTrace = useCallback(async (traceId: string) => {
    if (!traceId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getTraceViewer(cogentName, traceId.trim());
      setTrace(data);
    } catch (err: any) {
      setError(err.message ?? "Failed to load trace");
      setTrace(null);
    } finally {
      setLoading(false);
    }
  }, [cogentName]);

  useEffect(() => {
    if (initialTraceId) {
      loadTrace(initialTraceId);
    }
  }, [initialTraceId, loadTrace]);

  return (
    <div className="flex flex-col h-full" style={{ minHeight: "calc(100vh - var(--header-h) - 40px)" }}>
      {/* Input bar */}
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Enter trace ID..."
          value={traceIdInput}
          onChange={(e) => setTraceIdInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") loadTrace(traceIdInput);
          }}
          className="flex-1 bg-white/5 border border-white/10 rounded px-3 py-1.5 text-sm text-white placeholder-white/30 outline-none focus:border-white/30 font-mono"
        />
        <button
          onClick={() => loadTrace(traceIdInput)}
          disabled={loading || !traceIdInput.trim()}
          className="px-4 py-1.5 bg-white/10 hover:bg-white/15 border border-white/10 rounded text-sm text-white/80 transition-colors disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
        >
          {loading ? "Loading..." : "Load"}
        </button>
      </div>

      {error && (
        <div className="mb-4 px-3 py-2 bg-red-900/20 border border-red-500/30 rounded text-sm text-red-400">
          {error}
        </div>
      )}

      {trace && (
        <div className="flex-1">
          <TraceDetail trace={trace} />
        </div>
      )}

      {!trace && !loading && !error && (
        <div className="flex-1 flex items-center justify-center text-white/20 text-sm">
          Enter a trace ID to view span details
        </div>
      )}
    </div>
  );
}
