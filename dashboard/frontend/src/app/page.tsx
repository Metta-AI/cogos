"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Sidebar, type TabId, VALID_TABS } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { useCogentData } from "@/hooks/useCogentData";
import { OverviewPanel } from "@/components/overview/OverviewPanel";
import { ProgramsPanel } from "@/components/programs/ProgramsPanel";
import { ChannelsPanel } from "@/components/channels/ChannelsPanel";
import { EventsPanel } from "@/components/events/EventsPanel";
import { TriggersPanel } from "@/components/triggers/TriggersPanel";
import { MemoryPanel } from "@/components/memory/MemoryPanel";
import { ResourcesPanel } from "@/components/resources/ResourcesPanel";
import { TasksPanel } from "@/components/tasks/TasksPanel";
import { AlertsPanel } from "@/components/alerts/AlertsPanel";
import { CronPanel } from "@/components/cron/CronPanel";
import { ToolsPanel } from "@/components/tools/ToolsPanel";

function getTabFromHash(): TabId {
  if (typeof window === "undefined") return "overview";
  const hash = window.location.hash.replace("#", "");
  return VALID_TABS.has(hash as TabId) ? (hash as TabId) : "overview";
}

function useCogentName(): string | null {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    setName(window.location.hostname.split(".")[0].replace(/-/g, "."));
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
  const stuckTaskCount = useMemo(() => {
    return data.tasks.filter(
      (t) => t.status === "running" && t.updated_at &&
        Date.now() - new Date(t.updated_at).getTime() > STUCK_THRESHOLD_MS,
    ).length;
  }, [data.tasks]);

  const statusText = loading && !data.status
    ? "connecting..."
    : error
      ? error
      : data.status
        ? `${data.status.active_sessions} active · ${data.status.trigger_count} triggers · ${data.status.unresolved_alerts} alerts`
        : "no data";

  return (
    <div className="h-screen overflow-hidden">
      <Sidebar
        activeTab={activeTab}
        onTabChange={onTabChange}
        alertCount={data.status?.unresolved_alerts}
        stuckTaskCount={stuckTaskCount}
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
        {activeTab === "programs" && (
          <ProgramsPanel programs={data.programs} cogentName={cogentName} />
        )}
        {activeTab === "channels" && (
          <ChannelsPanel channels={data.channels} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "tools" && (
          <ToolsPanel tools={data.tools} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "events" && (
          <EventsPanel events={data.events} cogentName={cogentName} triggers={data.triggers} timeRange={timeRange} onTabChange={onTabChange as (tab: string) => void} />
        )}
        {activeTab === "triggers" && (
          <TriggersPanel triggers={data.triggers} cogentName={cogentName} programs={data.programs.map(p => p.name)} onRefresh={refresh} />
        )}
        {activeTab === "memory" && (
          <MemoryPanel memory={data.memory} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "resources" && (
          <ResourcesPanel resources={data.resources} />
        )}
        {activeTab === "tasks" && (
          <TasksPanel tasks={data.tasks} cogentName={cogentName} onRefresh={refresh} memory={data.memory} programs={data.programs} timeRange={timeRange} />
        )}
        {activeTab === "cron" && (
          <CronPanel crons={data.crons} cogentName={cogentName} onRefresh={refresh} />
        )}
        {activeTab === "alerts" && (
          <AlertsPanel alerts={data.alerts} cogentName={cogentName} onRefresh={refresh} />
        )}
      </main>
    </div>
  );
}
