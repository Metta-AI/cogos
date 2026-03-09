"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import type { CogosProcess } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { fmtTimestamp } from "@/lib/format";
import { getProcessDetail, updateProcess, deleteProcess, createProcess, type ProcessDetailRun } from "@/lib/api";

interface Props {
  processes: CogosProcess[];
  cogentName?: string;
  onRefresh?: () => void;
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  waiting: "neutral",
  runnable: "info",
  running: "success",
  completed: "accent",
  disabled: "error",
  blocked: "warning",
  suspended: "warning",
};

const STATUS_ORDER = ["blocked", "running", "runnable", "completed"] as const;

const columns: Column<CogosProcess & Record<string, unknown>>[] = [
  {
    key: "name",
    label: "Name",
    render: (row) => (
      <span className="text-[var(--text-primary)] font-medium">
        <span className="text-[var(--text-muted)] mr-1.5" title={row.mode}>
          {row.mode === "daemon" ? "⟳" : "→"}
        </span>
        {row.name}
      </span>
    ),
  },
  {
    key: "priority",
    label: "Priority",
    sortable: true,
    render: (row) => (
      <span className="text-[var(--text-secondary)] tabular-nums">
        {Number(row.priority).toFixed(2)}
      </span>
    ),
  },
  {
    key: "preemptible",
    label: "Preemptible",
    render: (row) => (
      <span className={row.preemptible ? "text-green-400" : "text-[var(--text-muted)]"}>
        {row.preemptible ? "yes" : "no"}
      </span>
    ),
  },
  {
    key: "updated_at",
    label: "Updated",
    render: (row) => (
      <span className="text-[var(--text-muted)] text-xs">{fmtTimestamp(row.updated_at)}</span>
    ),
  },
];

function groupByStatus(processes: CogosProcess[]) {
  const groups: Record<string, CogosProcess[]> = {};
  for (const p of processes) {
    (groups[p.status] ??= []).push(p);
  }
  const ordered: [string, CogosProcess[]][] = [];
  for (const s of STATUS_ORDER) {
    if (groups[s]) {
      ordered.push([s, groups[s]]);
      delete groups[s];
    }
  }
  for (const [s, procs] of Object.entries(groups)) {
    ordered.push([s, procs]);
  }
  return ordered;
}

const RUN_STATUS_VARIANT: Record<string, BadgeVariant> = {
  completed: "success",
  running: "info",
  failed: "error",
  timeout: "warning",
};

const RUN_STATUS_ABBREV: Record<string, string> = {
  running: "R",
  completed: "C",
  failed: "F",
  error: "E",
  timeout: "T",
  pending: "P",
};

function fmtDuration(ms: number | null): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const btnStyle = { background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" } as const;
const btnAccent = { background: "transparent", borderColor: "var(--accent)", color: "var(--accent)" } as const;
const btnDanger = { background: "transparent", borderColor: "var(--border)", color: "var(--error)" } as const;
const inputStyle = { background: "var(--bg-base)", borderColor: "var(--border)", color: "var(--text-primary)" } as const;

/* ── Detail panel shown below the table when a process is selected ── */

interface ProcessDetailProps {
  process: CogosProcess;
  cogentName?: string;
  onClose: () => void;
  onRefresh?: () => void;
}

function ProcessDetail({ process, cogentName, onClose, onRefresh }: ProcessDetailProps) {
  const [runs, setRuns] = useState<ProcessDetailRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [content, setContent] = useState<string>("");
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [editPriority, setEditPriority] = useState("");
  const [editName, setEditName] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const canMutate = !!cogentName && !!onRefresh;

  const loadDetail = useCallback(async () => {
    if (!cogentName) return;
    setLoading(true);
    try {
      const detail = await getProcessDetail(cogentName, process.id);
      setRuns(detail.runs);
      setContent(detail.process.content || "");
    } finally {
      setLoading(false);
    }
  }, [cogentName, process.id]);

  useEffect(() => {
    setEditing(false);
    setDeleteConfirm(false);
    loadDetail();
  }, [loadDetail]);

  const handleStartEdit = useCallback(() => {
    setEditContent(content);
    setEditPriority(Number(process.priority).toFixed(2));
    setEditName(process.name);
    setEditing(true);
  }, [content, process.priority, process.name]);

  const handleSave = useCallback(async () => {
    if (!cogentName || saving) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {};
      if (editName !== process.name) body.name = editName;
      if (editContent !== content) body.content = editContent;
      const newPri = parseFloat(editPriority);
      if (!isNaN(newPri) && newPri !== process.priority) body.priority = newPri;
      if (Object.keys(body).length > 0) {
        await updateProcess(cogentName, process.id, body);
      }
      setEditing(false);
      onRefresh?.();
      loadDetail();
    } finally {
      setSaving(false);
    }
  }, [cogentName, process, editName, editContent, editPriority, content, saving, onRefresh, loadDetail]);

  const handleDelete = useCallback(async () => {
    if (!cogentName || deleting) return;
    setDeleting(true);
    try {
      await deleteProcess(cogentName, process.id);
      onRefresh?.();
      onClose();
    } finally {
      setDeleting(false);
    }
  }, [cogentName, process.id, deleting, onRefresh, onClose]);

  const handleDuplicate = useCallback(async () => {
    if (!cogentName) return;
    await createProcess(cogentName, {
      name: `${process.name}-copy`,
      mode: process.mode,
      content: content || process.content || "",
      priority: process.priority,
      status: "waiting",
      preemptible: process.preemptible,
    });
    onRefresh?.();
  }, [cogentName, process, content, onRefresh]);

  const handleDisable = useCallback(async () => {
    if (!cogentName) return;
    const newStatus = process.status === "disabled" ? "waiting" : "disabled";
    await updateProcess(cogentName, process.id, { status: newStatus });
    onRefresh?.();
  }, [cogentName, process, onRefresh]);

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ background: "var(--bg-deep)" }}>
      {/* Header */}
      <div
        className="px-4 py-2 flex items-center gap-2 border-b flex-shrink-0"
        style={{ background: "var(--bg-surface)", borderColor: "var(--border)" }}
      >
        <span className="text-[var(--text-muted)] mr-0.5" title={process.mode}>
          {process.mode === "daemon" ? "⟳" : "→"}
        </span>
        <span className="text-[12px] font-mono font-medium text-[var(--accent)] truncate">
          {process.name}
        </span>
        <Badge variant={STATUS_VARIANT[process.status] || "neutral"}>{process.status}</Badge>
        <span className="text-[10px] text-[var(--text-muted)] tabular-nums ml-2">
          pri {Number(process.priority).toFixed(2)}
        </span>
        <span className="text-[10px] text-[var(--text-muted)]">
          {process.mode === "daemon" ? "daemon" : "one-shot"}
          {process.preemptible ? " · preemptible" : ""}
        </span>

        {/* Action buttons */}
        {canMutate && (
          <span className="flex gap-1 ml-auto mr-2">
            {!editing && (
              <button onClick={handleStartEdit} className="text-[10px] px-2 py-0.5 rounded border cursor-pointer" style={btnAccent}>
                Edit
              </button>
            )}
            <button onClick={handleDuplicate} className="text-[10px] px-2 py-0.5 rounded border cursor-pointer" style={btnStyle}>
              Duplicate
            </button>
            <button onClick={handleDisable} className="text-[10px] px-2 py-0.5 rounded border cursor-pointer" style={btnStyle}>
              {process.status === "disabled" ? "Enable" : "Disable"}
            </button>
            {deleteConfirm ? (
              <span className="flex items-center gap-1 text-[11px]">
                <span className="text-[var(--text-muted)]">Delete?</span>
                <button onClick={handleDelete} disabled={deleting} className="text-[var(--error)] border-0 bg-transparent cursor-pointer text-[11px] font-semibold disabled:opacity-40">{deleting ? "..." : "Yes"}</button>
                <button onClick={() => setDeleteConfirm(false)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[11px]">No</button>
              </span>
            ) : (
              <button onClick={() => setDeleteConfirm(true)} className="text-[10px] px-2 py-0.5 rounded border cursor-pointer" style={btnDanger}>
                Delete
              </button>
            )}
          </span>
        )}
        {!canMutate && <span className="ml-auto mr-2 text-[10px] text-[var(--text-muted)]">updated {fmtTimestamp(process.updated_at)}</span>}
        <button
          onClick={onClose}
          className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors"
          style={btnStyle}
          title="Close"
        >
          &times;
        </button>
      </div>

      {/* Content row */}
      <div
        className="px-4 py-2 border-b flex-shrink-0"
        style={{ background: "var(--bg-surface)", borderColor: "var(--border)" }}
      >
        {editing ? (
          <div className="space-y-2">
            <div className="flex gap-3 items-end">
              <div className="flex-1">
                <label className="block text-[10px] text-[var(--text-muted)] mb-0.5">Name</label>
                <input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full px-2 py-1 text-[12px] rounded border font-mono"
                  style={inputStyle}
                />
              </div>
              <div>
                <label className="block text-[10px] text-[var(--text-muted)] mb-0.5">Priority</label>
                <input
                  value={editPriority}
                  onChange={(e) => setEditPriority(e.target.value)}
                  className="w-24 px-2 py-1 text-[12px] rounded border font-mono"
                  style={inputStyle}
                />
              </div>
            </div>
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] mb-0.5">Content</label>
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                rows={3}
                className="w-full px-2 py-1.5 text-[12px] rounded border font-mono resize-y"
                style={inputStyle}
              />
            </div>
            <div className="flex gap-1.5">
              <button
                onClick={handleSave}
                disabled={saving}
                className="text-[10px] px-2 py-0.5 rounded border-0 cursor-pointer disabled:opacity-40"
                style={{ background: "var(--accent)", color: "white" }}
              >
                {saving ? "Saving..." : "Save"}
              </button>
              <button
                onClick={() => setEditing(false)}
                className="text-[10px] px-2 py-0.5 rounded border cursor-pointer"
                style={btnStyle}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-2">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide flex-shrink-0 pt-0.5">Content</span>
            <pre className="text-[12px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap break-all m-0 flex-1">
              {content || process.content || "(empty)"}
            </pre>
          </div>
        )}
      </div>

      {/* Runs table */}
      <div className="flex-1 overflow-y-auto p-3" style={{ background: "var(--bg-base)" }}>
        <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1.5">
          Recent Runs {!loading && <span>({runs.length})</span>}
        </div>
        {loading ? (
          <div className="text-[var(--text-muted)] text-[12px]">Loading...</div>
        ) : runs.length === 0 ? (
          <div className="text-[var(--text-muted)] text-[12px]">No runs</div>
        ) : (
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--border)" }}>
                <th className="px-2 py-1 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Status</th>
                <th className="px-2 py-1 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Started</th>
                <th className="px-2 py-1 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Finished</th>
                <th className="px-2 py-1 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Duration</th>
                <th className="px-2 py-1 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b" style={{ borderColor: "var(--border)" }}>
                  <td className="px-2 py-1">
                    <span title={r.status}>
                      <Badge variant={RUN_STATUS_VARIANT[r.status] || "neutral"}>
                        {RUN_STATUS_ABBREV[r.status] || r.status.charAt(0).toUpperCase()}
                      </Badge>
                    </span>
                  </td>
                  <td className="px-2 py-1 text-[var(--text-muted)] text-[11px]">{fmtTimestamp(r.created_at)}</td>
                  <td className="px-2 py-1 text-[var(--text-muted)] text-[11px]">{fmtTimestamp(r.completed_at)}</td>
                  <td className="px-2 py-1 text-[var(--text-secondary)] tabular-nums font-mono">{fmtDuration(r.duration_ms)}</td>
                  <td className="px-2 py-1 text-[var(--text-secondary)] tabular-nums font-mono">{r.tokens_in + r.tokens_out}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export function ProcessesPanel({ processes, cogentName, onRefresh }: Props) {
  const grouped = groupByStatus(processes);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ completed: true });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selectedProcess = useMemo(
    () => (selectedId ? processes.find((p) => p.id === selectedId) ?? null : null),
    [processes, selectedId],
  );

  const toggle = (status: string) =>
    setCollapsed((prev) => ({ ...prev, [status]: !prev[status] }));

  const handleRowClick = (row: CogosProcess & Record<string, unknown>) => {
    setSelectedId((prev) => (prev === row.id ? null : (row.id as string)));
  };

  return (
    <div style={{ paddingBottom: selectedProcess ? "45vh" : undefined }}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Processes
          <span className="ml-2 text-[var(--text-muted)] font-normal">({processes.length})</span>
        </h2>
        <div className="flex gap-1.5">
          {grouped.map(([status, procs]) => (
            <Badge key={status} variant={STATUS_VARIANT[status] || "neutral"}>
              {procs.length} {status}
            </Badge>
          ))}
        </div>
      </div>
      <div>
        {grouped.map(([status, procs]) => {
          const isCollapsed = !!collapsed[status];
          const rows = procs.map((p) => ({ ...p } as CogosProcess & Record<string, unknown>));
          return (
            <div key={status} className="mb-4">
              <button
                type="button"
                onClick={() => toggle(status)}
                className="flex items-center gap-2 mb-1.5 cursor-pointer select-none bg-transparent border-none p-0"
              >
                <span
                  className="text-[var(--text-muted)] text-xs transition-transform"
                  style={{ display: "inline-block", transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)" }}
                >
                  ▼
                </span>
                <Badge variant={STATUS_VARIANT[status] || "neutral"}>{status}</Badge>
                <span className="text-[var(--text-muted)] text-xs">{procs.length}</span>
              </button>
              {!isCollapsed && (
                <DataTable columns={columns} rows={rows} onRowClick={handleRowClick} emptyMessage="No processes" />
              )}
            </div>
          );
        })}
        {processes.length === 0 && (
          <p className="text-[var(--text-muted)] text-sm">No processes</p>
        )}
      </div>
      {selectedProcess && (
        <div
          className="fixed flex flex-col border-t"
          style={{
            left: "var(--sidebar-w)",
            right: 0,
            bottom: 0,
            height: "40vh",
            borderColor: "var(--border)",
            background: "var(--bg-deep)",
            zIndex: 20,
          }}
        >
          <ProcessDetail process={selectedProcess} cogentName={cogentName} onClose={() => setSelectedId(null)} onRefresh={onRefresh} />
        </div>
      )}
    </div>
  );
}
