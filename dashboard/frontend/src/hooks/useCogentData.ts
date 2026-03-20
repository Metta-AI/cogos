"use client";

import { useState, useEffect, useCallback } from "react";
import * as api from "@/lib/api";
import type {
  DashboardData,
  TimeRange,
  Alert,
  StatusResponse,
  CogosProcess,
} from "@/lib/types";
import { useWebSocket } from "./useWebSocket";

export function useCogentData(cogentName: string) {
  const [data, setData] = useState<DashboardData>({
    status: null,
    cogosStatus: null,
    programs: [],
    sessions: [],
    traces: [],
    triggers: [],
    memory: [],
    tasks: [],
    alerts: [],
    crons: [],
    resources: [],
    tools: [],
    processes: [],
    files: [],
    capabilities: [],
    handlers: [],
    runs: [],
    eventTypes: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("1h");
  const [showHistory, setShowHistory] = useState(false);

  const { connected, lastMessage } = useWebSocket(cogentName);

  const refresh = useCallback(async () => {
    if (!cogentName) return;
    const epochParam = showHistory ? "all" : undefined;
    setLoading(true);
    const results = await Promise.allSettled([
      api.getCogosStatus(cogentName, epochParam),
      api.getProcesses(cogentName, epochParam),
      api.getFiles(cogentName),
      api.getCapabilities(cogentName),
      api.getHandlers(cogentName),
      api.getRuns(cogentName, epochParam),
      api.getMessageTraces(cogentName, timeRange, { limit: 100 }),
      api.getCrons(cogentName),
      api.getResources(cogentName),
      api.getAlerts(cogentName),
    ]);
    // Only count core endpoints (exclude optional ones like resources, alerts)
    const coreResults = results.slice(0, -2);
    const failCount = coreResults.filter((r) => r.status === "rejected").length;
    if (failCount === coreResults.length) {
      setError("All API requests failed — is the backend running?");
    } else if (failCount > 0) {
      setError(`${failCount} of ${coreResults.length} API requests failed`);
    } else {
      setError(null);
    }
    setData((prev) => ({
      ...prev,
      cogosStatus: results[0].status === "fulfilled" ? results[0].value : null,
      processes: results[1].status === "fulfilled" ? results[1].value : [],
      files: results[2].status === "fulfilled" ? results[2].value : [],
      capabilities: results[3].status === "fulfilled" ? results[3].value : [],
      handlers: results[4].status === "fulfilled" ? results[4].value : [],
      runs: results[5].status === "fulfilled" ? results[5].value : [],
      traces: results[6].status === "fulfilled" ? results[6].value : [],
      crons: results[7].status === "fulfilled" ? results[7].value : [],
      eventTypes: [],
      resources: results[8].status === "fulfilled" ? results[8].value : [],
      alerts: results[9].status === "fulfilled" ? results[9].value : [],
    }));
    setLoading(false);
  }, [cogentName, timeRange, showHistory]);

  // Initial fetch
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Merge real-time WebSocket messages into data
  useEffect(() => {
    if (!lastMessage) return;

    const { type, data: payload } = lastMessage;

    if (type === "event") {
      void refresh();
      return;
    }

    setData((prev) => {
      switch (type) {
        case "alert":
          return {
            ...prev,
            alerts: [payload as Alert, ...prev.alerts],
          };

        case "status":
          return {
            ...prev,
            status: payload as StatusResponse,
          };

        case "process_update": {
          const process = payload as CogosProcess;
          const idx = prev.processes.findIndex((p) => p.id === process.id);
          if (idx >= 0) {
            const updated = [...prev.processes];
            updated[idx] = process;
            return { ...prev, processes: updated };
          }
          return { ...prev, processes: [process, ...prev.processes] };
        }

        default:
          return prev;
      }
    });
  }, [lastMessage, refresh]);

  // Poll cogos-status every 5s to keep scheduler tick fresh
  useEffect(() => {
    const epochParam = showHistory ? "all" : undefined;
    const id = setInterval(async () => {
      try {
        const cs = await api.getCogosStatus(cogentName, epochParam);
        setData((prev) => ({ ...prev, cogosStatus: cs }));
      } catch { /* ignore */ }
    }, 5_000);
    return () => clearInterval(id);
  }, [cogentName, showHistory]);

  // Auto-refresh every 30s — workaround until WS broadcast is wired up (#90)
  useEffect(() => {
    const id = setInterval(() => { refresh(); }, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  return { data, loading, error, refresh, timeRange, setTimeRange, connected, showHistory, setShowHistory };
}
