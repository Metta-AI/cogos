"use client";

import type { CogosRun } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { fmtTimestamp, fmtMs, fmtCost, fmtNum } from "@/lib/format";
import { buildCogentRunLogsUrl } from "@/lib/cloudwatch";

interface Props {
  runs: CogosRun[];
  cogentName?: string;
}

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

function makeColumns(cogentName?: string): Column<CogosRun & Record<string, unknown>>[] {
  const cols: Column<CogosRun & Record<string, unknown>>[] = [
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
      key: "id" as keyof (CogosRun & Record<string, unknown>),
      label: "Logs",
      render: (row) => (
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
      ),
    });
  }

  return cols;
}

export function RunsPanel({ runs, cogentName }: Props) {
  const columns = makeColumns(cogentName);
  const rows = runs.map((r) => ({ ...r } as CogosRun & Record<string, unknown>));

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
      <DataTable columns={columns} rows={rows} emptyMessage="No runs" />
    </div>
  );
}
