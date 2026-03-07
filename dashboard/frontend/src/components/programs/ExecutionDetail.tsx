"use client";

import { useState, useEffect } from "react";
import type { Execution } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { fmtCost, fmtMs, fmtNum, fmtTimestamp } from "@/lib/format";

interface ExecutionDetailProps {
  programName: string;
  cogentName: string;
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

function statusVariant(status: string | null): BadgeVariant {
  switch (status) {
    case "success":
    case "completed":
      return "success";
    case "running":
    case "in_progress":
      return "info";
    case "failed":
    case "error":
      return "error";
    case "timeout":
      return "warning";
    default:
      return "neutral";
  }
}

export function ExecutionDetail({
  programName,
  cogentName,
}: ExecutionDetailProps) {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchExecutions() {
      setLoading(true);
      setError(null);
      try {
        const resp = await fetch(
          `/api/cogents/${cogentName}/programs/${programName}/executions`,
        );
        if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
        const data = await resp.json();
        if (!cancelled) {
          setExecutions((data.executions ?? []).slice(0, 10));
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchExecutions();
    return () => {
      cancelled = true;
    };
  }, [cogentName, programName]);

  if (loading) {
    return (
      <div className="px-4 py-3 text-[12px] text-[var(--text-muted)]" style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}>
        Loading executions...
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-4 py-3 text-[12px] text-red-400" style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}>
        Error: {error}
      </div>
    );
  }

  return (
    <div className="px-4 py-3 space-y-0.5" style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}>
      <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium mb-1">
        Runs ({executions.length})
      </div>
      {executions.length === 0 && (
        <div className="text-[11px] text-[var(--text-muted)] py-2">No executions found</div>
      )}
      {executions.map((exec) => {
        const statusChar = exec.status?.[0]?.toUpperCase() ?? "?";
        const totalTokens = (exec.tokens_input ?? 0) + (exec.tokens_output ?? 0);
        return (
          <div
            key={exec.id}
            className="flex items-center gap-2 px-2 py-0.5 rounded text-[10px]"
            style={{ background: "var(--bg-surface)" }}
          >
            <Badge variant={statusVariant(exec.status)}>
              <span title={exec.status ?? "unknown"}>{statusChar}</span>
            </Badge>
            <span className="text-[var(--text-muted)]">{fmtMs(exec.duration_ms)}</span>
            {totalTokens > 0 && (
              <span className="text-[var(--text-muted)]" title={`in: ${fmtNum(exec.tokens_input)} out: ${fmtNum(exec.tokens_output)}`}>
                {totalTokens >= 1000 ? `${(totalTokens / 1000).toFixed(1)}k` : totalTokens} tok
              </span>
            )}
            {exec.cost_usd > 0 && (
              <span className="text-[var(--text-muted)]">{fmtCost(exec.cost_usd)}</span>
            )}
            <div className="flex-1" />
            <span className="text-[var(--text-muted)]">{fmtTimestamp(exec.started_at)}</span>
            {exec.error && (
              <span className="text-red-400 truncate max-w-[200px]" title={exec.error}>
                {exec.error}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
