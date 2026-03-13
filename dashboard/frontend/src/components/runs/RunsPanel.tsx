"use client";

import { useCallback, useState } from "react";

import type { CogosRun, CogosRunLogsResponse } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { fmtTimestamp, fmtMs, fmtCost, fmtNum } from "@/lib/format";
import { buildCogentRunLogsUrl } from "@/lib/cloudwatch";
import * as api from "@/lib/api";

interface Props {
  runs: CogosRun[];
  cogentName?: string;
}

type RunRow = CogosRun & Record<string, unknown>;

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  running: "accent",
  completed: "success",
  failed: "error",
  error: "error",
  timeout: "warning",
  pending: "info",
};

const STATUS_ABBREV: Record<string, string> = {
  running: "R",
  completed: "C",
  failed: "F",
  error: "E",
  timeout: "T",
  pending: "P",
};

function renderLogPreview(
  run: CogosRun,
  state: CogosRunLogsResponse | undefined,
  loading: boolean,
  cogentName?: string,
) {
  if (loading) {
    return <div className="text-[11px] text-[var(--text-muted)]">Loading run log preview...</div>;
  }
  if (!state) {
    return <div className="text-[11px] text-[var(--text-muted)]">Run logs are not loaded yet.</div>;
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--text-muted)]">
        <span className="inline-flex items-center gap-2">
          <span>run:</span>
          <code className="rounded bg-[var(--bg-surface)] px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)]">
            {run.id}
          </code>
          <button
            type="button"
            className="rounded border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
            onClick={() => navigator.clipboard.writeText(run.id)}
            title="Copy run ID"
          >
            Copy ID
          </button>
        </span>
        <span>group: {state.log_group}</span>
        {state.log_stream ? <span>stream: {state.log_stream}</span> : null}
        {cogentName ? (
          <a
            href={buildCogentRunLogsUrl(cogentName, run.id, run.created_at, run.runner)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--accent)] hover:underline"
          >
            Open in CloudWatch
          </a>
        ) : null}
      </div>
      {state.error ? (
        <div className="text-[11px] text-red-400">{state.error}</div>
      ) : state.entries.length === 0 ? (
        <div className="text-[11px] text-[var(--text-muted)]">No run logs found for this run.</div>
      ) : (
      <div className="rounded border border-[var(--border)] bg-[var(--bg-surface)]">
        {state.entries.map((entry, index) => (
          <div
            key={`${entry.log_stream}-${entry.timestamp}-${index}`}
            className="grid gap-2 px-3 py-2 text-[11px] font-mono border-b border-[var(--border)] last:border-b-0"
            style={{ gridTemplateColumns: "180px 1fr" }}
          >
            <div className="text-[var(--text-muted)]">{fmtTimestamp(entry.timestamp)}</div>
            <pre className="whitespace-pre-wrap break-words text-[var(--text-secondary)] m-0">
              {entry.message}
            </pre>
          </div>
        ))}
      </div>
      )}
    </div>
  );
}

function makeColumns(
  cogentName: string | undefined,
  expandedRunIds: Set<string>,
  toggleRunLogs: (runId: string) => void,
): Column<RunRow>[] {
  const cols: Column<RunRow>[] = [
    {
      key: "process_name",
      label: "Process",
      render: (row) => (
        <span className="inline-flex items-center gap-1.5">
          <span title={row.status}>
            <Badge variant={STATUS_VARIANT[row.status] || "neutral"}>
              {STATUS_ABBREV[row.status] || row.status.charAt(0).toUpperCase()}
            </Badge>
          </span>
          <span className="text-[var(--text-primary)] font-medium">
            {row.process_name || row.process}
          </span>
        </span>
      ),
    },
    {
      key: "duration_ms",
      label: "Duration",
      sortable: true,
      render: (row) => (
        <span className="text-[var(--text-secondary)]">{fmtMs(row.duration_ms)}</span>
      ),
    },
    {
      key: "tokens_in",
      label: "Tokens In",
      sortable: true,
      render: (row) => (
        <span className="text-[var(--text-secondary)]">{fmtNum(row.tokens_in)}</span>
      ),
    },
    {
      key: "tokens_out",
      label: "Tokens Out",
      sortable: true,
      render: (row) => (
        <span className="text-[var(--text-secondary)]">{fmtNum(row.tokens_out)}</span>
      ),
    },
    {
      key: "cost_usd",
      label: "Cost",
      sortable: true,
      render: (row) => (
        <span className="text-[var(--text-secondary)]">{fmtCost(row.cost_usd)}</span>
      ),
    },
    {
      key: "error",
      label: "Error",
      render: (row) =>
        row.error ? (
          <span className="text-red-400 text-xs truncate max-w-[200px] inline-block" title={row.error}>
            {row.error.length > 60 ? row.error.slice(0, 60) + "..." : row.error}
          </span>
        ) : (
          <span className="text-[var(--text-muted)]">--</span>
        ),
    },
    {
      key: "created_at",
      label: "Created",
      render: (row) => (
        <span className="text-[var(--text-muted)] text-xs">{fmtTimestamp(row.created_at)}</span>
      ),
    },
  ];

  if (cogentName) {
    cols.push({
      key: "id" as keyof RunRow,
      label: "Logs",
      render: (row) => (
        <div className="inline-flex items-center gap-2">
          <button
            type="button"
            className="text-[var(--text-muted)] text-xs hover:text-[var(--text-primary)]"
            title={expandedRunIds.has(row.id) ? "Hide inline logs" : "Show inline logs"}
            onClick={(e) => {
              e.stopPropagation();
              toggleRunLogs(row.id);
            }}
          >
            {expandedRunIds.has(row.id) ? "▾" : "▸"}
          </button>
          <a
            href={buildCogentRunLogsUrl(cogentName, row.id, row.created_at, row.runner)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--accent)] text-xs hover:underline"
            title="View CloudWatch logs for this run"
            onClick={(e) => e.stopPropagation()}
          >
            CW
          </a>
        </div>
      ),
    });
  }

  return cols;
}

export function RunsPanel({ runs, cogentName }: Props) {
  const [expandedRunIds, setExpandedRunIds] = useState<Set<string>>(new Set());
  const [logPreviewByRun, setLogPreviewByRun] = useState<Record<string, CogosRunLogsResponse>>({});
  const [loadingRunIds, setLoadingRunIds] = useState<Set<string>>(new Set());
  const toggleRunLogs = useCallback(async (runId: string) => {
    if (!cogentName) return;

    if (expandedRunIds.has(runId)) {
      setExpandedRunIds((prev) => {
        const next = new Set(prev);
        next.delete(runId);
        return next;
      });
      return;
    }

    setExpandedRunIds((prev) => new Set(prev).add(runId));
    if (loadingRunIds.has(runId)) return;

    setLoadingRunIds((prev) => new Set(prev).add(runId));
    try {
      const preview = await api.getRunLogs(cogentName, runId);
      setLogPreviewByRun((prev) => ({ ...prev, [runId]: preview }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not load run log preview.";
      setLogPreviewByRun((prev) => ({
        ...prev,
        [runId]: { log_group: "", log_stream: null, entries: [], error: message },
      }));
    } finally {
      setLoadingRunIds((prev) => {
        const next = new Set(prev);
        next.delete(runId);
        return next;
      });
    }
  }, [cogentName, expandedRunIds, loadingRunIds]);

  const columns = makeColumns(cogentName, expandedRunIds, toggleRunLogs);
  const rows = runs.map((r) => ({ ...r } as RunRow));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Runs
          <span className="ml-2 text-[var(--text-muted)] font-normal">({runs.length})</span>
        </h2>
        <div className="flex gap-1.5">
          {Object.entries(
            runs.reduce<Record<string, number>>((acc, r) => {
              acc[r.status] = (acc[r.status] || 0) + 1;
              return acc;
            }, {}),
          ).map(([status, count]) => (
            <Badge key={status} variant={STATUS_VARIANT[status] || "neutral"}>
              {count} {status}
            </Badge>
          ))}
        </div>
      </div>
      <DataTable
        columns={columns}
        rows={rows}
        emptyMessage="No runs"
        getRowId={(row) => row.id}
        onRowClick={(row) => {
          void toggleRunLogs(row.id);
        }}
        expandedRowIds={expandedRunIds}
        renderExpandedRow={(row) => renderLogPreview(row, logPreviewByRun[row.id], loadingRunIds.has(row.id), cogentName)}
      />
    </div>
  );
}
