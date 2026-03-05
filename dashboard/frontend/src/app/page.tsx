"use client";

import { useState } from "react";
import { Sidebar, type TabId } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { useCogentData } from "@/hooks/useCogentData";

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  // For now, hardcode cogent name. Will come from URL/config later.
  const cogentName = "cogent";
  const { data, loading, refresh, timeRange, setTimeRange } = useCogentData(cogentName);

  const statusText = data.status
    ? `${data.status.active_sessions} active · ${data.status.trigger_count} triggers · ${data.status.unresolved_alerts} alerts`
    : "loading...";

  return (
    <div className="h-screen overflow-hidden">
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        alertCount={data.status?.unresolved_alerts}
        triggerCount={data.status?.trigger_count}
      />
      <Header
        cogentName={cogentName}
        statusText={statusText}
        timeRange={timeRange}
        onTimeRangeChange={setTimeRange}
        onRefresh={refresh}
        loading={loading}
      />
      <main
        className="fixed overflow-y-auto p-5"
        style={{
          top: "var(--header-h)",
          left: "var(--sidebar-w)",
          right: 0,
          bottom: 0,
        }}
      >
        {/* Panel placeholders — will be replaced by actual panel components */}
        <div
          style={{
            color: "var(--text-muted)",
            fontSize: "13px",
          }}
        >
          {activeTab} panel (coming soon)
        </div>
      </main>
    </div>
  );
}
