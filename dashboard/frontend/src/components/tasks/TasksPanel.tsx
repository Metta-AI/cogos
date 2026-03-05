"use client";

import { useState, useCallback, useMemo } from "react";
import type { Task } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { fmtRelative } from "@/lib/format";

interface TasksPanelProps {
  tasks: Task[];
  cogentName: string;
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  pending: "info",
  running: "accent",
  completed: "success",
  failed: "error",
};

export function TasksPanel({ tasks }: TasksPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleRowClick = useCallback((row: Record<string, unknown>) => {
    const id = row.id as string;
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  const columns: Column<Record<string, unknown>>[] = useMemo(
    () => [
      {
        key: "title",
        label: "Title",
        render: (row) => (
          <span className="text-[var(--text-primary)]">
            {(row.title as string) ?? "--"}
          </span>
        ),
      },
      {
        key: "status",
        label: "Status",
        render: (row) => {
          const status = (row.status as string) ?? "unknown";
          return (
            <Badge variant={STATUS_VARIANT[status] ?? "neutral"}>
              {status}
            </Badge>
          );
        },
      },
      {
        key: "priority",
        label: "Priority",
        render: (row) => (
          <span className="font-mono">
            {(row.priority as number) ?? "--"}
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
        key: "created_at",
        label: "Created",
        render: (row) => (
          <span className="text-[var(--text-muted)] text-[11px]">
            {fmtRelative(row.created_at as string | null)}
          </span>
        ),
      },
      {
        key: "updated_at",
        label: "Updated",
        render: (row) => (
          <span className="text-[var(--text-muted)] text-[11px]">
            {fmtRelative(row.updated_at as string | null)}
          </span>
        ),
      },
    ],
    [],
  );

  const rows = useMemo(
    () =>
      tasks.map((t) => ({
        ...t,
      })) as unknown as Record<string, unknown>[],
    [tasks],
  );

  const expandedTask = expandedId
    ? tasks.find((t) => t.id === expandedId)
    : null;

  return (
    <div>
      <DataTable
        columns={columns}
        rows={rows}
        onRowClick={handleRowClick}
        emptyMessage="No tasks"
      />

      {/* Expanded detail */}
      {expandedTask && (
        <div className="mt-1 mx-3 mb-3 bg-[var(--bg-deep)] border border-[var(--border)] rounded-md p-4 space-y-3">
          {expandedTask.description && (
            <div>
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium mb-1">
                Description
              </div>
              <div className="text-[12px] text-[var(--text-secondary)] whitespace-pre-wrap">
                {expandedTask.description}
              </div>
            </div>
          )}

          {expandedTask.error && (
            <div>
              <div className="text-[10px] text-red-400 uppercase tracking-wide font-medium mb-1">
                Error
              </div>
              <div className="text-[12px] text-red-300 font-mono whitespace-pre-wrap">
                {expandedTask.error}
              </div>
            </div>
          )}

          {expandedTask.metadata &&
            Object.keys(expandedTask.metadata).length > 0 && (
              <div>
                <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium mb-1">
                  Metadata
                </div>
                <JsonViewer data={expandedTask.metadata} />
              </div>
            )}
        </div>
      )}
    </div>
  );
}
