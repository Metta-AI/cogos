"use client";

import type { CogosHandler } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";

interface Props {
  handlers: CogosHandler[];
}

function FiredCell({ count }: { count: number }) {
  if (count === 0) return <span className="text-[var(--text-muted)]">0</span>;
  return <span className="text-[var(--text-primary)]">{count}</span>;
}

const columns: Column<CogosHandler & Record<string, unknown>>[] = [
  {
    key: "event_pattern",
    label: "Event Pattern",
    render: (row) => (
      <span
        className={`font-mono text-xs ${row.enabled ? "text-[var(--text-secondary)]" : "text-red-400"}`}
      >
        {row.event_pattern}{!row.enabled && " (disabled)"}
      </span>
    ),
  },
  {
    key: "process_name",
    label: "Process",
    render: (row) => (
      <span className="text-[var(--text-secondary)] text-xs">
        {row.process_name || row.process}
      </span>
    ),
  },
  {
    key: "fired_1m",
    label: "1m",
    render: (row) => <FiredCell count={row.fired_1m} />,
  },
  {
    key: "fired_5m",
    label: "5m",
    render: (row) => <FiredCell count={row.fired_5m} />,
  },
  {
    key: "fired_1h",
    label: "1h",
    render: (row) => <FiredCell count={row.fired_1h} />,
  },
  {
    key: "fired_24h",
    label: "24h",
    render: (row) => <FiredCell count={row.fired_24h} />,
  },
];

export function HandlersPanel({ handlers }: Props) {
  const rows = handlers.map((h) => ({ ...h } as CogosHandler & Record<string, unknown>));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Handlers
          <span className="ml-2 text-[var(--text-muted)] font-normal">({handlers.length})</span>
        </h2>
      </div>
      <DataTable columns={columns} rows={rows} emptyMessage="No handlers" />
    </div>
  );
}
