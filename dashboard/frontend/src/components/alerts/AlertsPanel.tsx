"use client";

import { useMemo } from "react";
import type { Alert } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { fmtRelative } from "@/lib/format";

interface AlertsPanelProps {
  alerts: Alert[];
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const SEVERITY_VARIANT: Record<string, BadgeVariant> = {
  critical: "error",
  warning: "warning",
  info: "info",
};

export function AlertsPanel({ alerts }: AlertsPanelProps) {
  const columns: Column<Record<string, unknown>>[] = useMemo(
    () => [
      {
        key: "severity",
        label: "Severity",
        render: (row) => {
          const severity = (row.severity as string) ?? "info";
          return (
            <Badge variant={SEVERITY_VARIANT[severity] ?? "neutral"}>
              {severity}
            </Badge>
          );
        },
      },
      {
        key: "alert_type",
        label: "Type",
        render: (row) => (
          <span className="text-[var(--text-secondary)]">
            {(row.alert_type as string) ?? "--"}
          </span>
        ),
      },
      {
        key: "source",
        label: "Source",
        render: (row) => (
          <span className="text-[var(--text-muted)]">
            {(row.source as string) ?? "--"}
          </span>
        ),
      },
      {
        key: "message",
        label: "Message",
        render: (row) => {
          const msg = (row.message as string) ?? "--";
          const truncated = msg.length > 100 ? msg.slice(0, 100) + "..." : msg;
          return (
            <span
              className="text-[var(--text-secondary)]"
              title={msg}
            >
              {truncated}
            </span>
          );
        },
      },
      {
        key: "created_at",
        label: "Created",
        render: (row) => (
          <span className="text-[var(--text-muted)] text-[11px]">
            {fmtRelative(row.created_at as string | null)}
          </span>
        ),
      },
    ],
    [],
  );

  const rows = useMemo(
    () => alerts.map((a) => ({ ...a })) as unknown as Record<string, unknown>[],
    [alerts],
  );

  return (
    <DataTable
      columns={columns}
      rows={rows}
      emptyMessage="No alerts"
    />
  );
}
