"use client";

import React from "react";

const TABS = [
  {
    id: "overview",
    label: "Overview",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ),
  },
  {
    id: "tasks",
    label: "Tasks",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    ),
  },
  {
    id: "memory",
    label: "Memory",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
      </svg>
    ),
  },
  {
    id: "cron",
    label: "Cron",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
  },
  {
    id: "programs",
    label: "Programs",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
  },
  {
    id: "channels",
    label: "Channels",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="2 12 6 8 10 16 14 4 18 14 22 12" />
      </svg>
    ),
  },
  {
    id: "tools",
    label: "Tools",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
      </svg>
    ),
  },
  {
    id: "events",
    label: "Events",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="2 12 5 12 7 4 10 20 13 12 15 16 17 8 19 12 22 12" />
      </svg>
    ),
  },
  {
    id: "triggers",
    label: "Triggers",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 01-3.46 0" />
      </svg>
    ),
  },
  {
    id: "resources",
    label: "Resources",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="12" width="4" height="9" rx="0.5" />
        <rect x="10" y="7" width="4" height="14" rx="0.5" />
        <rect x="17" y="3" width="4" height="18" rx="0.5" />
      </svg>
    ),
  },
  {
    id: "alerts",
    label: "Alerts",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
  },
] as const;

export type TabId = (typeof TABS)[number]["id"];
export const VALID_TABS = new Set<string>(TABS.map((t) => t.id));

interface SidebarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  alertCount?: number;
  stuckTaskCount?: number;
}

export function Sidebar({ activeTab, onTabChange, alertCount, stuckTaskCount }: SidebarProps) {
  return (
    <nav
      className="fixed top-0 left-0 bottom-0 flex flex-col items-center py-2 z-50"
      style={{
        width: "var(--sidebar-w)",
        background: "var(--bg-base)",
        borderRight: "1px solid var(--border)",
      }}
    >
      {TABS.map((tab) => {
        const isActive = activeTab === tab.id;
        const badgeCount =
          tab.id === "alerts" ? alertCount :
          tab.id === "tasks" ? stuckTaskCount :
          undefined;

        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            title={tab.label}
            className="sidebar-btn relative flex flex-col items-center justify-center gap-0.5 w-full cursor-pointer border-0 bg-transparent transition-colors duration-150"
            style={{
              width: "var(--sidebar-w)",
              height: "var(--sidebar-w)",
              color: isActive ? "var(--accent)" : "var(--text-muted)",
              background: isActive ? "var(--accent-glow)" : "transparent",
              borderLeft: isActive ? "2px solid var(--accent)" : "2px solid transparent",
            }}
            onMouseEnter={(e) => {
              if (!isActive) {
                e.currentTarget.style.color = "var(--text-secondary)";
                e.currentTarget.style.background = "var(--bg-hover)";
              }
            }}
            onMouseLeave={(e) => {
              if (!isActive) {
                e.currentTarget.style.color = "var(--text-muted)";
                e.currentTarget.style.background = "transparent";
              }
            }}
          >
            {tab.icon}
            <span
              style={{
                fontSize: "9px",
                lineHeight: 1,
                fontWeight: 500,
                marginTop: "2px",
                maxWidth: "calc(var(--sidebar-w) - 8px)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {tab.label}
            </span>
            {badgeCount != null && badgeCount > 0 && (
              <span
                className="absolute flex items-center justify-center rounded-full text-white font-bold"
                style={{
                  top: "4px",
                  right: "6px",
                  minWidth: "14px",
                  height: "14px",
                  fontSize: "8px",
                  padding: "0 3px",
                  background: tab.id === "alerts" ? "var(--error)" : tab.id === "tasks" ? "var(--warning)" : "var(--warning)",
                }}
              >
                {badgeCount > 99 ? "99+" : badgeCount}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
