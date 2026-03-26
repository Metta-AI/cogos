"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Sidebar, type TabId, VALID_TABS } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { useCogentData } from "@/hooks/useCogentData";
import * as api from "@/lib/api";
import { OverviewPanel } from "@/components/overview/OverviewPanel";
import { ProcessesView } from "@/components/processes/ProcessesView";
import { FilesPanel } from "@/components/files/FilesPanel";
import { ConfigurePanel } from "@/components/configure/ConfigurePanel";
import { EventsPanel } from "@/components/events/EventsPanel";
import { DiagnosticsPanel } from "@/components/diagnostics/DiagnosticsPanel";
import { ChatPanel } from "@/components/chat/ChatPanel";

function getTabFromHash(): TabId {
  if (typeof window === "undefined") return "overview";
  const hash = window.location.hash.replace("#", "").split(":")[0];
  if (hash === "handlers" || hash === "cron") return "events" as TabId;
  if (hash === "runs" || hash === "executors" || hash === "resources") return "processes" as TabId;
  if (hash === "trace" || hash === "trace-viewer") return "events" as TabId;
  if (hash === "setup" || hash === "integrations" || hash === "capabilities") return "configure" as TabId;
  return VALID_TABS.has(hash as TabId) ? (hash as TabId) : "overview";
}

function getSubTabFromHash(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const hash = window.location.hash.replace("#", "");
  const parts = hash.split(":");
  if (parts.length > 1) return parts[1];
  // Direct subtab aliases: #executors → subtab=executors, #runs → subtab=runs, etc.
  const subtabAliases: Record<string, string> = {
    runs: "runs", executors: "executors", resources: "resources", capabilities: "capabilities",
  };
  return subtabAliases[hash];
}

function getTraceIdFromHash(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const hash = window.location.hash.replace("#", "");
  if (hash.startsWith("trace-viewer:")) {
    return hash.slice("trace-viewer:".length);
  }
  return undefined;
}

function useCogentName(): string | null {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    const hostname = window.location.hostname;
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      // Check query param first (for cogent switching in local dev)
      const params = new URLSearchParams(window.location.search);
      const fromParam = params.get("cogent");
      if (fromParam) {
        setName(fromParam);
        return;
      }
      if (process.env.NEXT_PUBLIC_COGENT) {
        setName(process.env.NEXT_PUBLIC_COGENT);
        return;
      }
      // Resolve from API
      api.listCogents().then((r) => {
        setName(r.current || r.cogents[0] || "localhost");
      }).catch(() => setName("localhost"));
    } else {
      setName(hostname.split(".")[0].replace(/-/g, "."));
    }
  }, []);
  return name;
}

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>(getTabFromHash);
  const [initialTraceId, setInitialTraceId] = useState<string | undefined>(getTraceIdFromHash);
  const [initialSubTab] = useState<string | undefined>(getSubTabFromHash);

  const handleTabChange = useCallback((tab: TabId) => {
    setActiveTab(tab);
    setInitialTraceId(undefined);
    window.location.hash = tab === "overview" ? "" : tab;
  }, []);

  useEffect(() => {
    const onPopState = () => {
      setActiveTab(getTabFromHash());
      setInitialTraceId(getTraceIdFromHash());
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const cogentName = useCogentName();

  if (!cogentName) {
    return <div className="h-screen overflow-hidden" />;
  }

  return <Dashboard cogentName={cogentName} activeTab={activeTab} onTabChange={handleTabChange} initialTraceId={initialTraceId} initialSubTab={initialSubTab} />;
}

function Dashboard({ cogentName, activeTab, onTabChange, initialTraceId, initialSubTab }: { cogentName: string; activeTab: TabId; onTabChange: (tab: TabId) => void; initialTraceId?: string; initialSubTab?: string }) {
  const { data, loading, error, refresh, ensureLoaded, timeRange, setTimeRange, connected, showHistory, setShowHistory } = useCogentData(cogentName);

  // Lazy-load data when switching tabs
  useEffect(() => {
    switch (activeTab) {
      case "processes":
        ensureLoaded("runs", "files", "capabilities", "resources", "executors");
        break;
      case "files":
        ensureLoaded("files");
        break;
      case "events":
        ensureLoaded("handlers", "crons", "traces");
        break;
      case "overview":
        ensureLoaded("runs");
        break;
    }
  }, [activeTab, ensureLoaded]);

  const STUCK_THRESHOLD_MS = 10 * 60 * 1000;
  const stuckProcessCount = useMemo(() => {
    const activeRunProcessIds = new Set(
      data.runs.filter((r) => r.status === "running").map((r) => r.process),
    );
    return data.processes.filter(
      (p) => activeRunProcessIds.has(p.id) && p.updated_at &&
        Date.now() - new Date(p.updated_at).getTime() > STUCK_THRESHOLD_MS,
    ).length;
  }, [data.processes, data.runs]);

  const cs = data.cogosStatus;
  const currentEpoch = cs?.reboot_epoch ?? 0;
  const statusText = loading && !data.status && !cs
    ? "connecting..."
    : error
      ? error
      : cs
        ? `${cs.processes.total} processes · ${cs.files} files · ${cs.capabilities} capabilities`
        : data.status
          ? `${data.status.active_sessions} active · ${data.status.trigger_count} triggers · ${data.status.unresolved_alerts} alerts`
          : "no data";

  return (
    <div className="h-screen overflow-hidden">
      <Sidebar
        activeTab={activeTab}
        onTabChange={onTabChange}
        stuckProcessCount={stuckProcessCount}
      />
      <Header
        cogentName={cogentName}
        statusText={statusText}
        timeRange={timeRange}
        onTimeRangeChange={setTimeRange}
        onRefresh={refresh}
        loading={loading}
        error={error}
        wsConnected={connected}
        schedulerLastTick={cs?.scheduler_last_tick ?? null}
        ages={cs?.ages ?? null}
        showHistory={showHistory}
        onShowHistoryChange={setShowHistory}
        alerts={data.alerts}
        alertCount={data.status?.unresolved_alerts ?? data.alerts.length}
      />
      <main
        className="fixed overflow-y-auto p-5 pb-16"
        style={{
          top: "var(--header-h)",
          left: "var(--sidebar-w)",
          right: 0,
          bottom: 0,
        }}
      >
        {activeTab === "overview" && <OverviewPanel data={data} />}
        {activeTab === "chat" && <ChatPanel cogentName={cogentName} />}
        {activeTab === "processes" && (
          <ProcessesView
            processes={data.processes}
            cogentName={cogentName}
            onRefresh={refresh}
            resources={data.resources}
            runs={data.runs}
            files={data.files}
            capabilities={data.capabilities}
            eventTypes={data.eventTypes}
            currentEpoch={currentEpoch}
            executors={data.executors}
            initialSubTab={initialSubTab}
          />
        )}
        {activeTab === "files" && (
          <FilesPanel files={data.files} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "events" && (
          <EventsPanel handlers={data.handlers} crons={data.crons} traces={data.traces} channels={data.channels} cogentName={cogentName} timeRange={timeRange} onRefresh={refresh} initialTraceId={initialTraceId} />
        )}
        {activeTab === "diagnostics" && (
          <DiagnosticsPanel cogentName={cogentName} />
        )}
        {activeTab === "configure" && (
          <ConfigurePanel cogentName={cogentName} />
        )}
      </main>
    </div>
  );
}
