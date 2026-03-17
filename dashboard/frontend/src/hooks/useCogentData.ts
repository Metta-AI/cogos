"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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
      api.getEventTypes(cogentName),
      api.getResources(cogentName),
      api.getAlerts(cogentName),
    ]);
    // Only count core endpoints (exclude optional ones like eventTypes, resources, alerts)
    const coreResults = results.slice(0, -3);
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
      eventTypes: results[8].status === "fulfilled" ? results[8].value : [],
      resources: results[9].status === "fulfilled" ? results[9].value : [],
      alerts: results[10].status === "fulfilled" ? results[10].value : [],
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

  // Fallback polling: if WS not connected after 5s, poll every 30s
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const connectedRef = useRef(connected);
  connectedRef.current = connected;

  useEffect(() => {
    const timeout = setTimeout(() => {
      if (!connectedRef.current) {
        pollingRef.current = setInterval(() => {
          if (!connectedRef.current) {
            refresh();
          }
        }, 30000);
      }
    }, 5000);

    return () => {
      clearTimeout(timeout);
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [refresh]);

  // Stop polling once WS connects
  useEffect(() => {
    if (connected && pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, [connected]);

  return { data, loading, error, refresh, timeRange, setTimeRange, connected, showHistory, setShowHistory };
}
