"use client";

import React, { useState, useCallback, useEffect } from "react";
import type { TimeRange, AgeInfo } from "@/lib/types";
import * as api from "@/lib/api";

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
      {/* Left: cogent name (with hover panel) + tick */}
      <div className="flex items-center gap-3">
        <div className="relative group">
          <span
            style={{
              color: "var(--accent)",
              fontSize: "15px",
              fontWeight: 700,
              cursor: "default",
            }}
          >
            {cogentName}
          </span>
          {/* Status hover panel */}
          <div
            className="absolute left-0 top-full mt-1 hidden group-hover:block z-50"
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "10px 14px",
              minWidth: "180px",
              boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
            }}
          >
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <tbody>
                <tr>
                  <td style={rowLabel}>status</td>
                  <td style={{ ...rowValue, color: error ? "var(--error)" : "var(--text-muted)" }}>
                    {statusText}
                  </td>
                </tr>
                {tick != null && (
                  <tr>
                    <td style={rowLabel}>tick</td>
                    <td style={{ ...rowValue, color: tickColor(tick.ms) }}>{tick.text}</td>
                  </tr>
                )}
                <tr>
                  <td style={rowLabel}>ws</td>
                  <td style={{ ...rowValue, color: wsColor }}>
                    {stableConnected ? "connected" : "disconnected"}
                  </td>
                </tr>
              </tbody>
            </table>
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

      {/* Right: time range picker + refresh */}
      <div className="flex items-center gap-3">
        {/* Time range picker */}
        <div
          className="flex items-center rounded-md overflow-hidden"
          style={{
            border: "1px solid var(--border)",
            gap: "1px",
            background: "var(--border)",
          }}
        >
          {TIME_RANGES.map((tr) => (
            <button
              key={tr.value}
              onClick={() => onTimeRangeChange(tr.value)}
              className="border-0 cursor-pointer transition-colors duration-100"
              style={{
                padding: "4px 10px",
                fontSize: "11px",
                fontFamily: "var(--font-mono)",
                fontWeight: 500,
                color: timeRange === tr.value ? "var(--bg-deep)" : "var(--text-secondary)",
                background: timeRange === tr.value ? "var(--accent)" : "var(--bg-surface)",
              }}
              onMouseEnter={(e) => {
                if (timeRange !== tr.value) {
                  e.currentTarget.style.background = "var(--bg-hover)";
                }
              }}
              onMouseLeave={(e) => {
                if (timeRange !== tr.value) {
                  e.currentTarget.style.background = "var(--bg-surface)";
                }
              }}
            >
              {tr.label}
            </button>
          ))}
        </div>

        {/* Reboot button */}
        <RebootButton cogentName={cogentName} onRefresh={onRefresh} />

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
