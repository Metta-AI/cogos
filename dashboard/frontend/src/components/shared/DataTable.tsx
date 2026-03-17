"use client";

import { Fragment, useCallback, useState } from "react";

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => React.ReactNode;
  sortable?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
  getRowId?: (row: T, index: number) => string;
  expandedRowIds?: Set<string>;
  renderExpandedRow?: (row: T) => React.ReactNode;
  getRowStyle?: (row: T) => React.CSSProperties | undefined;
}

type SortDir = "asc" | "desc";

export function DataTable<T extends Record<string, unknown>>({
  columns,
  rows,
  onRowClick,
  emptyMessage = "No data",
  getRowId,
  expandedRowIds,
  renderExpandedRow,
  getRowStyle,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const handleSort = useCallback(
    (key: string) => {
      if (sortKey === key) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir("asc");
      }
    },
    [sortKey],
  );

  const sorted = sortKey
    ? [...rows].sort((a, b) => {
        const av = a[sortKey];
        const bv = b[sortKey];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        if (typeof av === "number" && typeof bv === "number") {
          return sortDir === "asc" ? av - bv : bv - av;
        }
        const sa = String(av);
        const sb = String(bv);
        return sortDir === "asc"
          ? sa.localeCompare(sb)
          : sb.localeCompare(sa);
      })
    : rows;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-3 py-2 text-[11px] text-[var(--text-muted)] uppercase tracking-wide font-medium cursor-pointer select-none hover:text-[var(--text-secondary)]"
                onClick={() => handleSort(col.key)}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {sortKey === col.key && (
                    <span className="text-[var(--accent)] text-[10px]">
                      {sortDir === "asc" ? "\u25B2" : "\u25BC"}
                    </span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-8 text-center text-[var(--text-muted)]"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            sorted.map((row, i) => {
              const rowId = getRowId ? getRowId(row, i) : String(i);
              const isExpanded = Boolean(renderExpandedRow && expandedRowIds?.has(rowId));

              return (
                <Fragment key={rowId}>
                  <tr
                    className={`border-b border-[var(--border)] hover:bg-[var(--bg-hover)] transition-colors ${
                      onRowClick ? "cursor-pointer" : ""
                    }`}
                    style={getRowStyle?.(row)}
                    onClick={() => onRowClick?.(row)}
                  >
                    {columns.map((col) => (
                      <td
                        key={col.key}
                        className="px-3 py-2 font-mono text-[var(--text-secondary)]"
                      >
                        {col.render
                          ? col.render(row)
                          : (row[col.key] as React.ReactNode) ?? (
                              <span className="text-[var(--text-muted)]">--</span>
                            )}
                      </td>
                    ))}
                  </tr>
                  {isExpanded && (
                    <tr className="border-b border-[var(--border)] bg-[var(--bg-deep)]">
                      <td colSpan={columns.length} className="px-3 py-3">
                        {renderExpandedRow?.(row)}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
