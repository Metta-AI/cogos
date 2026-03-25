"use client";

import React, { useState, useCallback, useEffect, useRef } from "react";
import type { TimeRange, AgeInfo, Alert } from "@/lib/types";
import * as api from "@/lib/api";
import { fmtTimestamp } from "@/lib/format";

const TIME_RANGES: { value: TimeRange; label: string }[] = [
  { value: "1m", label: "1m" },
  { value: "10m", label: "10m" },
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "1w", label: "1w" },
];

interface HeaderProps {
  cogentName: string;
  statusText: string;
  timeRange: TimeRange;
  onTimeRangeChange: (range: TimeRange) => void;
  onRefresh: () => void;
  loading: boolean;
  error: string | null;
  wsConnected: boolean;
  schedulerLastTick: string | null;
  ages: AgeInfo | null;
  showHistory: boolean;
  onShowHistoryChange: (show: boolean) => void;
  alerts: Alert[];
  alertCount: number;
}

function useTickAgo(schedulerLastTick: string | null): { text: string; ms: number } | null {
  const [state, setState] = useState<{ text: string; ms: number } | null>(null);
  useEffect(() => {
    if (!schedulerLastTick) { setState(null); return; }
    const update = () => {
      const ms = Date.now() - new Date(schedulerLastTick).getTime();
      if (ms < 0) { setState(null); return; }
      let text: string;
      if (ms < 1000) text = "<1s";
      else if (ms < 60_000) text = `${Math.floor(ms / 1000)}s`;
      else if (ms < 3_600_000) text = `${Math.floor(ms / 60_000)}m`;
      else text = `${Math.floor(ms / 3_600_000)}h`;
      setState({ text, ms });
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [schedulerLastTick]);
  return state;
}

function tickColor(ms: number): string {
  if (ms < 60_000) return "var(--success)";
  if (ms < 90_000) return "var(--warning)";
  return "var(--error)";
}

function fmtAge(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return null;
  if (ms < 60_000) return "<1m";
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h`;
  return `${Math.floor(ms / 86_400_000)}d`;
}

function ageColor(iso: string | null | undefined): string {
  if (!iso) return "var(--text-muted)";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 3_600_000) return "var(--success)";   // < 1h
  if (ms < 86_400_000) return "var(--warning)";   // < 1d
  return "var(--error)";
}

function CogentSwitcher({ cogentName }: { cogentName: string }) {
  const [open, setOpen] = useState(false);
  const [cogents, setCogents] = useState<string[] | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleOpen = useCallback(() => {
    setOpen((v) => !v);
    if (cogents === null) {
      api.listCogents().then((r) => setCogents(r.cogents)).catch(() => setCogents([]));
    }
  }, [cogents]);

  const navigate = useCallback((name: string) => {
    setOpen(false);
    const hostname = window.location.hostname;
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      // Local dev: reload with different NEXT_PUBLIC_COGENT isn't possible,
      // so just navigate with a query param hint
      window.location.href = `${window.location.origin}?cogent=${name}`;
    } else {
      // Production: swap the subdomain
      const parts = hostname.split(".");
      parts[0] = name.replace(/\./g, "-");
      window.location.href = `${window.location.protocol}//${parts.join(".")}`;
    }
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={handleOpen}
        className="border-0 bg-transparent cursor-pointer flex items-center gap-1 p-0"
        style={{
          color: "var(--accent)",
          fontSize: "15px",
          fontWeight: 700,
        }}
      >
        {cogentName}
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 150ms",
            opacity: 0.6,
          }}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-50"
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "8px",
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
            minWidth: "180px",
            maxHeight: "300px",
            overflowY: "auto",
            padding: "4px 0",
          }}
        >
          {cogents === null ? (
            <div className="px-3 py-2" style={{ fontSize: "11px", color: "var(--text-muted)" }}>
              loading...
            </div>
          ) : cogents.length === 0 ? (
            <div className="px-3 py-2" style={{ fontSize: "11px", color: "var(--text-muted)" }}>
              no cogents found
            </div>
          ) : (
            cogents.map((name) => (
              <button
                key={name}
                onClick={() => navigate(name)}
                className="w-full text-left border-0 cursor-pointer block transition-colors duration-100"
                style={{
                  padding: "6px 12px",
                  fontSize: "13px",
                  fontFamily: "var(--font-mono)",
                  fontWeight: name === cogentName ? 700 : 400,
                  color: name === cogentName ? "var(--accent)" : "var(--text-primary)",
                  background: name === cogentName ? "rgba(59,130,246,0.1)" : "transparent",
                }}
                onMouseEnter={(e) => {
                  if (name !== cogentName) e.currentTarget.style.background = "var(--bg-hover)";
                }}
                onMouseLeave={(e) => {
                  if (name !== cogentName) e.currentTarget.style.background = "transparent";
                }}
              >
                {name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function RebootButton({ cogentName, onRefresh }: { cogentName: string; onRefresh: () => void }) {
  const [state, setState] = useState<"idle" | "confirm" | "rebooting">("idle");

  const handleClick = useCallback(() => {
    if (state === "idle") {
      setState("confirm");
      setTimeout(() => setState((s) => (s === "confirm" ? "idle" : s)), 3000);
    } else if (state === "confirm") {
      setState("rebooting");
      api.reboot(cogentName).then(() => {
        setState("idle");
        onRefresh();
      }).catch(() => {
        setState("idle");
      });
    }
  }, [state, cogentName, onRefresh]);

  const label = state === "confirm" ? "confirm?" : state === "rebooting" ? "..." : "reboot";
  const color = state === "confirm" ? "var(--error)" : "var(--text-muted)";

  return (
    <button
      onClick={handleClick}
      disabled={state === "rebooting"}
      className="border-0 rounded-md cursor-pointer transition-colors duration-150"
      style={{
        padding: "4px 8px",
        fontSize: "10px",
        fontFamily: "var(--font-mono)",
        fontWeight: 500,
        background: state === "confirm" ? "rgba(239,68,68,0.15)" : "var(--bg-surface)",
        border: "1px solid var(--border)",
        color,
      }}
      title="Kill all processes, clear state, re-create init"
    >
      {label}
    </button>
  );
}

function AlertsBadge({ alerts, alertCount, cogentName, onRefresh }: {
  alerts: Alert[];
  alertCount: number;
  cogentName: string;
  onRefresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [resolving, setResolving] = useState<Set<string>>(new Set());
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleResolve = useCallback(async (alertId: string) => {
    setResolving((s) => new Set(s).add(alertId));
    try {
      await api.resolveAlert(cogentName, alertId);
      onRefresh();
    } finally {
      setResolving((s) => { const n = new Set(s); n.delete(alertId); return n; });
    }
  }, [cogentName, onRefresh]);

  const handleResolveAll = useCallback(async () => {
    await api.resolveAllAlerts(cogentName);
    onRefresh();
  }, [cogentName, onRefresh]);

  const hasAlerts = alertCount > 0;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex items-center justify-center border-0 rounded-md cursor-pointer transition-colors duration-150"
        style={{
          width: "32px",
          height: "32px",
          background: open ? "var(--bg-hover)" : "var(--bg-surface)",
          border: "1px solid var(--border)",
          color: hasAlerts ? "var(--error)" : "var(--text-muted)",
        }}
        title={hasAlerts ? `${alertCount} unresolved alert${alertCount !== 1 ? "s" : ""}` : "No alerts"}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        {hasAlerts && (
          <span
            className="absolute flex items-center justify-center rounded-full text-white font-bold"
            style={{
              top: "-4px",
              right: "-4px",
              minWidth: "16px",
              height: "16px",
              fontSize: "9px",
              padding: "0 4px",
              background: "var(--error)",
            }}
          >
            {alertCount > 99 ? "99+" : alertCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50"
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "8px",
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
            width: "380px",
            maxHeight: "400px",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div className="flex items-center justify-between px-3 py-2" style={{ borderBottom: "1px solid var(--border)" }}>
            <span style={{ fontSize: "11px", fontWeight: 600, color: "var(--text-primary)" }}>
              Alerts ({alertCount})
            </span>
            {hasAlerts && (
              <button
                onClick={handleResolveAll}
                className="text-[10px] px-2 py-0.5 rounded border-0 cursor-pointer"
                style={{ background: "var(--accent)", color: "white" }}
              >
                Resolve All
              </button>
            )}
          </div>
          <div style={{ overflowY: "auto", flex: 1 }}>
            {alerts.length === 0 ? (
              <div className="text-center py-6" style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                No unresolved alerts
              </div>
            ) : (
              alerts.map((a) => {
                const sevColor = a.severity === "critical" || a.severity === "emergency"
                  ? "var(--error)" : a.severity === "warning" ? "var(--warning)" : "var(--text-muted)";
                return (
                  <div
                    key={a.id}
                    className="flex items-start gap-2 px-3 py-2 hover:bg-[var(--bg-hover)] transition-colors"
                    style={{ borderBottom: "1px solid var(--border)" }}
                  >
                    <span style={{
                      fontSize: "9px",
                      fontFamily: "var(--font-mono)",
                      fontWeight: 600,
                      color: sevColor,
                      textTransform: "uppercase",
                      minWidth: "48px",
                      paddingTop: "2px",
                    }}>
                      {a.severity ?? "info"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div style={{ fontSize: "11px", color: "var(--text-primary)", lineHeight: 1.4 }}>
                        {(a.message ?? "--").length > 80
                          ? (a.message ?? "--").slice(0, 80) + "..."
                          : (a.message ?? "--")}
                      </div>
                      <div style={{ fontSize: "9px", color: "var(--text-muted)", marginTop: "2px" }}>
                        {a.source ? `${a.source} · ` : ""}{fmtTimestamp(a.created_at)}
                      </div>
                    </div>
                    <button
                      onClick={() => handleResolve(a.id)}
                      disabled={resolving.has(a.id)}
                      className="text-[9px] px-1.5 py-0.5 rounded border-0 cursor-pointer shrink-0 disabled:opacity-40"
                      style={{ background: "var(--accent)", color: "white" }}
                    >
                      {resolving.has(a.id) ? "..." : "Resolve"}
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function Header({
  cogentName,
  statusText,
  timeRange,
  onTimeRangeChange,
  onRefresh,
  loading,
  error,
  wsConnected,
  schedulerLastTick,
  ages,
  showHistory,
  onShowHistoryChange,
  alerts,
  alertCount,
}: HeaderProps) {
  // Show spin for at least 400ms so the user sees feedback
  const [spinning, setSpinning] = useState(false);
  const handleRefresh = useCallback(() => {
    setSpinning(true);
    onRefresh();
    setTimeout(() => setSpinning(false), 400);
  }, [onRefresh]);
  const showSpin = loading || spinning;
  const tick = useTickAgo(schedulerLastTick);

  // Debounce WS connected state to avoid rapid flickering
  const [stableConnected, setStableConnected] = useState(false);
  useEffect(() => {
    if (wsConnected) {
      const timer = setTimeout(() => setStableConnected(true), 2000);
      return () => clearTimeout(timer);
    } else {
      setStableConnected(false);
    }
  }, [wsConnected]);

  const wsColor = stableConnected ? "var(--success)" : "var(--warning)";

  const rowLabel: React.CSSProperties = {
    fontSize: "10px",
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    paddingRight: "12px",
    paddingTop: "2px",
    paddingBottom: "2px",
    whiteSpace: "nowrap",
    verticalAlign: "top",
  };
  const rowValue: React.CSSProperties = {
    fontSize: "10px",
    fontFamily: "var(--font-mono)",
    textAlign: "right",
    paddingTop: "2px",
    paddingBottom: "2px",
    whiteSpace: "nowrap",
  };

  return (
    <header
      className="fixed top-0 right-0 flex items-center justify-between px-4 z-40"
      style={{
        left: "var(--sidebar-w)",
        height: "var(--header-h)",
        background: "var(--bg-base)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      {/* Left: cogent name + status badges + tick */}
      <div className="flex items-center gap-3">
        <CogentSwitcher cogentName={cogentName} />

        {/* API badge with tooltip */}
        <div className="relative group/api">
          <span
            style={{
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              fontWeight: 600,
              color: error ? "var(--error)" : "var(--success)",
              background: error ? "rgba(239,68,68,0.15)" : "rgba(52,211,153,0.15)",
              padding: "2px 6px",
              borderRadius: "4px",
              cursor: "default",
            }}
          >
            API
          </span>
          <div
            className="absolute left-0 top-full mt-1 hidden group-hover/api:block z-50"
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "8px 12px",
              minWidth: "200px",
              maxWidth: "500px",
              boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              color: error ? "var(--error)" : "var(--text-muted)",
              whiteSpace: error ? "pre-wrap" : "nowrap",
              wordBreak: error ? "break-word" : undefined,
            }}
          >
            {statusText}
          </div>
        </div>

        {/* WS badge with tooltip */}
        <div className="relative group/ws">
          <span
            style={{
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              fontWeight: 600,
              color: wsColor,
              background: stableConnected ? "rgba(52,211,153,0.15)" : "rgba(234,179,8,0.15)",
              padding: "2px 6px",
              borderRadius: "4px",
              cursor: "default",
            }}
          >
            WS
          </span>
          <div
            className="absolute left-0 top-full mt-1 hidden group-hover/ws:block z-50"
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "8px 12px",
              boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              color: wsColor,
              whiteSpace: "nowrap",
            }}
          >
            {stableConnected ? "connected" : "disconnected"}
          </div>
        </div>

        {/* Scheduler heartbeat — always visible */}
        {tick != null && (
          <span
            title={`Last scheduler tick: ${schedulerLastTick}`}
            style={{
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              color: tickColor(tick.ms),
              opacity: 0.7,
            }}
          >
            tick {tick.text}
          </span>
        )}
      </div>

      {/* Right: reboot + refresh */}
      <div className="flex items-center gap-3">
        {/* Reboot button */}
        <RebootButton cogentName={cogentName} onRefresh={onRefresh} />

        {/* Alerts badge */}
        <AlertsBadge alerts={alerts} alertCount={alertCount} cogentName={cogentName} onRefresh={onRefresh} />

        {/* Refresh button with ages hover panel */}
        <div className="relative group/refresh">
          <button
            onClick={handleRefresh}
            disabled={showSpin}
            className="flex items-center justify-center border-0 rounded-md cursor-pointer transition-colors duration-150"
            style={{
              width: "32px",
              height: "32px",
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              color: showSpin ? "var(--accent)" : wsColor,
            }}
            title={stableConnected ? "Real-time connected · Refresh" : "Real-time disconnected · Refresh"}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--bg-hover)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "var(--bg-surface)";
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={showSpin ? "header-spin" : ""}
            >
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
            </svg>
          </button>
          {/* Ages hover panel */}
          {ages && (
            <div
              className="absolute right-0 top-full mt-1 hidden group-hover/refresh:block z-50"
              style={{
                background: "var(--bg-surface)",
                border: "1px solid var(--border)",
                borderRadius: "6px",
                padding: "10px 14px",
                minWidth: "160px",
                boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
              }}
            >
              <table style={{ borderCollapse: "collapse", width: "100%" }}>
                <tbody>
                  {(
                    [
                      ["image", ages.image],
                      ["content", ages.content],
                      ["stack", ages.stack],
                      ["schema", ages.schema],
                      ["state", ages.state],
                    ] as const
                  ).map(([label, ts]) => {
                    const age = fmtAge(ts);
                    return (
                      <tr key={label}>
                        <td style={rowLabel}>{label}</td>
                        <td
                          style={{ ...rowValue, color: ageColor(ts), opacity: age ? 1 : 0.4 }}
                          title={ts ? new Date(ts).toLocaleString() : "unknown"}
                        >
                          {age ?? "?"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
