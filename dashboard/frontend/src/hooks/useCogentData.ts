"use client";

import { useState, useEffect, useCallback } from "react";
import * as api from "@/lib/api";
import type { DashboardData, TimeRange } from "@/lib/types";

export function useCogentData(cogentName: string) {
  const [data, setData] = useState<DashboardData>({
    status: null,
    programs: [],
    sessions: [],
    events: [],
    triggers: [],
    memory: [],
    tasks: [],
    channels: [],
    alerts: [],
  });
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState<TimeRange>("1h");

  const refresh = useCallback(async () => {
    setLoading(true);
    const results = await Promise.allSettled([
      api.getStatus(cogentName, timeRange),
      api.getPrograms(cogentName),
      api.getSessions(cogentName),
      api.getEvents(cogentName, timeRange),
      api.getTriggers(cogentName),
      api.getMemory(cogentName),
      api.getTasks(cogentName),
      api.getChannels(cogentName),
      api.getAlerts(cogentName),
    ]);
    setData({
      status: results[0].status === "fulfilled" ? results[0].value : null,
      programs: results[1].status === "fulfilled" ? results[1].value : [],
      sessions: results[2].status === "fulfilled" ? results[2].value : [],
      events: results[3].status === "fulfilled" ? results[3].value : [],
      triggers: results[4].status === "fulfilled" ? results[4].value : [],
      memory: results[5].status === "fulfilled" ? results[5].value : [],
      tasks: results[6].status === "fulfilled" ? results[6].value : [],
      channels: results[7].status === "fulfilled" ? results[7].value : [],
      alerts: results[8].status === "fulfilled" ? results[8].value : [],
    });
    setLoading(false);
  }, [cogentName, timeRange]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, refresh, timeRange, setTimeRange };
}
