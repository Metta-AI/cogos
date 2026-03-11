"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Sidebar, type TabId, VALID_TABS } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { useCogentData } from "@/hooks/useCogentData";
import { OverviewPanel } from "@/components/overview/OverviewPanel";
import { ProcessesPanel } from "@/components/processes/ProcessesPanel";
import { FilesPanel } from "@/components/files/FilesPanel";
import { CapabilitiesPanel } from "@/components/capabilities/CapabilitiesPanel";
import { HandlersPanel } from "@/components/handlers/HandlersPanel";
import { RunsPanel } from "@/components/runs/RunsPanel";
import { EventsPanel } from "@/components/events/EventsPanel";
import { ResourcesPanel } from "@/components/resources/ResourcesPanel";
import { AlertsPanel } from "@/components/alerts/AlertsPanel";
import { CronPanel } from "@/components/cron/CronPanel";
import { SetupPanel } from "@/components/setup/SetupPanel";

function getTabFromHash(): TabId {
  if (typeof window === "undefined") return "overview";
  const hash = window.location.hash.replace("#", "");
  return VALID_TABS.has(hash as TabId) ? (hash as TabId) : "overview";
}

function resolveCogentName(hostname: string): string | null {
  const explicit = process.env.NEXT_PUBLIC_DASHBOARD_COGENT_NAME?.trim();
  if (explicit) return explicit;
  if (hostname === "localhost" || hostname === "127.0.0.1") return hostname;
  if (hostname.endsWith(".localhost")) return hostname.slice(0, -".localhost".length);
  const firstLabel = hostname.split(".")[0];
  if (!firstLabel) return null;
  if (hostname.endsWith(".softmax-cogents.com")) return firstLabel.replace(/-/g, ".");
  return firstLabel;
}

function useCogentName(): string | null {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    setName(resolveCogentName(window.location.hostname));
  }, []);
  return name;
}

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>(getTabFromHash);

  const handleTabChange = useCallback((tab: TabId) => {
    setActiveTab(tab);
    window.location.hash = tab === "overview" ? "" : tab;
  }, []);

  useEffect(() => {
    const onPopState = () => setActiveTab(getTabFromHash());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const cogentName = useCogentName();

  if (!cogentName) {
    return <div className="h-screen overflow-hidden" />;
  }

  return <Dashboard cogentName={cogentName} activeTab={activeTab} onTabChange={handleTabChange} />;
}

function Dashboard({ cogentName, activeTab, onTabChange }: { cogentName: string; activeTab: TabId; onTabChange: (tab: TabId) => void }) {
  const { data, loading, error, refresh, timeRange, setTimeRange, connected } = useCogentData(cogentName);

  const STUCK_THRESHOLD_MS = 10 * 60 * 1000;
  const stuckProcessCount = useMemo(() => {
    return data.processes.filter(
      (p) => p.status === "running" && p.updated_at &&
        Date.now() - new Date(p.updated_at).getTime() > STUCK_THRESHOLD_MS,
    ).length;
  }, [data.processes]);

  const cs = data.cogosStatus;
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
        alertCount={data.status?.unresolved_alerts}
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
        {activeTab === "processes" && (
          <ProcessesPanel
            processes={data.processes}
            cogentName={cogentName}
            onRefresh={refresh}
            resources={data.resources}
            runs={data.runs}
            files={data.files}
            capabilities={data.capabilities}
            eventTypes={data.eventTypes}
          />
        )}
        {activeTab === "files" && (
          <FilesPanel files={data.files} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "capabilities" && (
          <CapabilitiesPanel capabilities={data.capabilities} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "handlers" && (
          <HandlersPanel handlers={data.handlers} />
        )}
        {activeTab === "runs" && (
          <RunsPanel runs={data.runs} cogentName={cogentName} />
        )}
        {activeTab === "events" && (
          <EventsPanel events={data.events} cogentName={cogentName} triggers={data.triggers} timeRange={timeRange} onTabChange={onTabChange as (tab: string) => void} eventTypes={data.eventTypes} onRefresh={refresh} />
        )}
        {activeTab === "cron" && (
          <CronPanel crons={data.crons} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "resources" && (
          <ResourcesPanel resources={data.resources} />
        )}
        {activeTab === "alerts" && (
          <AlertsPanel alerts={data.alerts} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "setup" && (
          <SetupPanel cogentName={cogentName} />
        )}
      </main>
    </div>
  );
}
