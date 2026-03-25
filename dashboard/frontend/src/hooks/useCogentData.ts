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
    executors: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("1h");
  const [showHistory, setShowHistory] = useState(false);

  // Track which data sets have been loaded (for lazy loading)
  const [loaded, setLoaded] = useState<Set<string>>(new Set());

  const { connected, lastMessage } = useWebSocket(cogentName);

  // Core refresh: single combined request for initial render
  const refresh = useCallback(async () => {
    if (!cogentName) return;
    const epochParam = showHistory ? "all" : undefined;
    setLoading(true);
    try {
      const init = await api.getDashboardInit(cogentName, epochParam);
      setData((prev) => ({
        ...prev,
        cogosStatus: init.cogos_status,
        processes: init.processes,
        alerts: init.alerts,
      }));
      setError(null);
    } catch (e) {
      setError(`Dashboard init failed: ${e}`);
    }
    setLoaded((prev) => new Set([...prev, "cogosStatus", "processes", "alerts"]));
    setLoading(false);
  }, [cogentName, showHistory]);

  // Lazy loader: fetch a data set on demand (idempotent — skips if already loaded)
  const ensureLoaded = useCallback(async (...keys: string[]) => {
    const missing = keys.filter((k) => !loaded.has(k));
    if (missing.length === 0) return;

    const epochParam = showHistory ? "all" : undefined;
    const fetchers: Record<string, () => Promise<unknown>> = {
      files: () => api.getFiles(cogentName),
      capabilities: () => api.getCapabilities(cogentName),
      handlers: () => api.getHandlers(cogentName),
      runs: () => api.getRuns(cogentName, epochParam),
      traces: () => api.getMessageTraces(cogentName, timeRange, { limit: 100 }),
      crons: () => api.getCrons(cogentName),
      resources: () => api.getResources(cogentName),
      executors: () => api.getExecutors(cogentName),
    };

    const toFetch = missing.filter((k) => k in fetchers);
    if (toFetch.length === 0) return;

    const results = await Promise.allSettled(
      toFetch.map((k) => fetchers[k]()),
    );

    setData((prev) => {
      const next = { ...prev };
      toFetch.forEach((key, i) => {
        if (results[i].status === "fulfilled") {
          (next as Record<string, unknown>)[key] = (results[i] as PromiseFulfilledResult<unknown>).value;
        }
      });
      return next;
    });
    setLoaded((prev) => new Set([...prev, ...toFetch]));
  }, [cogentName, timeRange, showHistory, loaded]);

  // Initial fetch
  useEffect(() => {
    setLoaded(new Set());
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

  return { data, loading, error, refresh, ensureLoaded, timeRange, setTimeRange, connected, showHistory, setShowHistory };
}
