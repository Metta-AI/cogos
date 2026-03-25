"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { CogosRun, CogosRunLogsResponse, RunOutputsResponse } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { PrettyLogView } from "@/components/runs/PrettyLogView";
import { fmtTimestamp, fmtMs, fmtCost, fmtNum, fmtTime } from "@/lib/format";
import { buildCogentRunLogsUrl } from "@/lib/cloudwatch";
import * as api from "@/lib/api";

interface Props {
  runs: CogosRun[];
  cogentName?: string;
  currentEpoch?: number;
}

type RunRow = CogosRun & Record<string, unknown>;

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

type RunTab = "logs" | "files" | "messages" | "children";

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

function TabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-mono transition-colors border ${
        active
          ? "border-[var(--accent-dim)] bg-[var(--accent-glow)] text-[var(--accent)]"
          : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
      }`}
    >
      {label}
      {count != null && count > 0 && (
        <span className={`text-[9px] ${active ? "text-[var(--accent)]" : "text-[var(--text-muted)]"}`}>
          {count}
        </span>
      )}
    </button>
  );
}

function DiffLine({ line }: { line: string }) {
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return <span className="text-emerald-400">{line}</span>;
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return <span className="text-red-400">{line}</span>;
  }
  if (line.startsWith("@@")) {
    return <span className="text-[var(--accent)]">{line}</span>;
  }
  return <span className="text-[var(--text-muted)]">{line}</span>;
}

function DiffView({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return (
    <pre className="whitespace-pre-wrap break-words text-[10px] font-mono m-0 px-3 py-2 bg-[var(--bg-deep)] rounded">
      {lines.map((line, i) => (
        <div key={i}>
          <DiffLine line={line} />
        </div>
      ))}
    </pre>
  );
}

function FilesTab({ files }: { files: RunOutputsResponse["files"] }) {
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());

  if (files.length === 0) {
    return <div className="text-[11px] text-[var(--text-muted)]">No files touched.</div>;
  }

  const toggleFile = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="rounded border border-[var(--border)] bg-[var(--bg-surface)]">
      {files.map((f, i) => {
        const rowKey = `${f.key}-v${f.version}`;
        const expanded = expandedKeys.has(rowKey);
        return (
          <div
            key={rowKey}
            className={i < files.length - 1 ? "border-b border-[var(--border)]" : ""}
          >
            <div
              className="flex items-center gap-3 px-3 py-1.5 text-[11px] font-mono cursor-pointer hover:bg-[var(--bg-deep)]"
              onClick={() => f.diff && toggleFile(rowKey)}
            >
              {f.diff ? (
                <span className="text-[var(--text-muted)] text-[9px] w-3">{expanded ? "\u25BC" : "\u25B6"}</span>
              ) : (
                <span className="w-3" />
              )}
              <span className="text-[var(--text-primary)] flex-1 truncate" title={f.key}>{f.key}</span>
              <span className="text-[var(--text-muted)]">v{f.version}</span>
              {f.created_at && <span className="text-[var(--text-muted)]">{fmtTime(f.created_at)}</span>}
            </div>
            {expanded && f.diff && <DiffView diff={f.diff} />}
          </div>
        );
      })}
    </div>
  );
}

function MessagesTab({ messages }: { messages: RunOutputsResponse["messages"] }) {
  if (messages.length === 0) {
    return <div className="text-[11px] text-[var(--text-muted)]">No messages sent.</div>;
  }
  return (
    <div className="rounded border border-[var(--border)] bg-[var(--bg-surface)]">
      {messages.map((m, i) => (
        <div
          key={m.id}
          className={`px-3 py-2 text-[11px] ${i < messages.length - 1 ? "border-b border-[var(--border)]" : ""}`}
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-[var(--accent)]">{m.channel_name}</span>
            {m.created_at && <span className="text-[var(--text-muted)]">{fmtTime(m.created_at)}</span>}
          </div>
          <pre className="whitespace-pre-wrap break-words text-[var(--text-secondary)] m-0 text-[10px]">
            {JSON.stringify(m.payload, null, 2)}
          </pre>
        </div>
      ))}
    </div>
  );
}

function ChildrenTab({ children }: { children: RunOutputsResponse["children"] }) {
  if (children.length === 0) {
    return <div className="text-[11px] text-[var(--text-muted)]">No children spawned.</div>;
  }
  return (
    <div className="rounded border border-[var(--border)] bg-[var(--bg-surface)]">
      {children.map((c, i) => (
        <div
          key={c.id}
          className={`flex items-center gap-3 px-3 py-1.5 text-[11px] ${i < children.length - 1 ? "border-b border-[var(--border)]" : ""}`}
        >
          <Badge variant={STATUS_VARIANT[c.status] || "neutral"}>
            {STATUS_ABBREV[c.status] || c.status.charAt(0).toUpperCase()}
          </Badge>
          <span className="text-[var(--text-primary)] font-medium">{c.process_name || c.process}</span>
          <span className="text-[var(--text-muted)]">{fmtMs(c.duration_ms)}</span>
          {c.created_at && <span className="text-[var(--text-muted)] ml-auto">{fmtTime(c.created_at)}</span>}
        </div>
      ))}
    </div>
  );
}

function renderLogPreview(
  run: CogosRun,
  state: CogosRunLogsResponse | undefined,
  loading: boolean,
  copiedRunId: string | null,
  copyRunId: (runId: string) => void,
  prettyMode: boolean,
  togglePrettyMode: () => void,
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
          <button
            type="button"
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] transition-colors ${
              copiedRunId === run.id
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                : "border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:border-[var(--border-active)] hover:text-[var(--text-primary)]"
            }`}
            onClick={() => copyRunId(run.id)}
            title={copiedRunId === run.id ? "Run ID copied" : "Copy run ID"}
          >
            <code>{run.id}</code>
            {copiedRunId === run.id ? <span className="font-sans uppercase tracking-wide">copied</span> : null}
          </button>
        </span>
        <span>group: {state.log_group}</span>
        {state.log_stream ? <span>stream: {state.log_stream}</span> : null}
        {cogentName ? (
          <a
            href={buildCogentRunLogsUrl(cogentName, run.id, run.created_at)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--accent)] hover:underline"
          >
            Open in CloudWatch
          </a>
        ) : null}
        <button
          type="button"
          onClick={togglePrettyMode}
          className={`ml-auto inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] transition-colors ${
            prettyMode
              ? "border-[var(--accent-dim)] bg-[var(--accent-glow)] text-[var(--accent)]"
              : "border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
          }`}
        >
          {prettyMode ? "pretty" : "raw"}
        </button>
      </div>
      {state.error ? (
        <div className="text-[11px] text-red-400">{state.error}</div>
      ) : state.entries.length === 0 ? (
        <div className="text-[11px] text-[var(--text-muted)]">No run logs found for this run.</div>
      ) : prettyMode ? (
        <PrettyLogView entries={state.entries} />
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

function ExpandedRunView({
  run,
  logState,
  logLoading,
  outputs,
  outputsLoading,
  copiedRunId,
  copyRunId,
  prettyMode,
  togglePrettyMode,
  cogentName,
}: {
  run: CogosRun;
  logState: CogosRunLogsResponse | undefined;
  logLoading: boolean;
  outputs: RunOutputsResponse | undefined;
  outputsLoading: boolean;
  copiedRunId: string | null;
  copyRunId: (runId: string) => void;
  prettyMode: boolean;
  togglePrettyMode: () => void;
  cogentName?: string;
}) {
  const [tab, setTab] = useState<RunTab>("logs");

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        <TabButton label="Logs" active={tab === "logs"} onClick={() => setTab("logs")} />
        <TabButton
          label="Files"
          count={outputs?.files.length}
          active={tab === "files"}
          onClick={() => setTab("files")}
        />
        <TabButton
          label="Messages"
          count={outputs?.messages.length}
          active={tab === "messages"}
          onClick={() => setTab("messages")}
        />
        <TabButton
          label="Children"
          count={outputs?.children.length}
          active={tab === "children"}
          onClick={() => setTab("children")}
        />
      </div>
      {tab === "logs" &&
        renderLogPreview(run, logState, logLoading, copiedRunId, copyRunId, prettyMode, togglePrettyMode, cogentName)}
      {tab === "files" && (
        outputsLoading
          ? <div className="text-[11px] text-[var(--text-muted)]">Loading...</div>
          : outputs ? <FilesTab files={outputs.files} /> : null
      )}
      {tab === "messages" && (
        outputsLoading
          ? <div className="text-[11px] text-[var(--text-muted)]">Loading...</div>
          : outputs ? <MessagesTab messages={outputs.messages} /> : null
      )}
      {tab === "children" && (
        outputsLoading
          ? <div className="text-[11px] text-[var(--text-muted)]">Loading...</div>
          : outputs ? <ChildrenTab children={outputs.children} /> : null
      )}
    </div>
  );
}

function makeColumns(
  cogentName: string | undefined,
  toggleRunLogs: (runId: string) => void,
): Column<RunRow>[] {
  return [
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
          {row.executor && row.executor !== "llm" && (
            <span className="text-[9px] px-1 py-0 rounded font-mono" style={{ background: "var(--bg-deep)", color: "var(--text-muted)" }}>{row.executor}</span>
          )}
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
    {
      key: "_links",
      label: "",
      render: (row) => (
        <span className="inline-flex items-center gap-1">
          {cogentName && (
            <a
              href={buildCogentRunLogsUrl(cogentName, row.id, row.created_at)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[10px] font-mono px-1 py-0 rounded hover:underline"
              style={{ background: "rgba(234,179,8,0.12)", color: "#facc15" }}
              title="CloudWatch logs"
              onClick={(e) => e.stopPropagation()}
            >
              CW
            </a>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); toggleRunLogs(row.id); }}
            className="text-[10px] font-mono px-1 py-0 rounded hover:underline bg-transparent border-0 cursor-pointer"
            style={{ background: "rgba(59,130,246,0.12)", color: "#60a5fa" }}
            title="Session log (inline)"
          >
            L
          </button>
        </span>
      ),
    },
  ];
}

export function RunsPanel({ runs, cogentName, currentEpoch }: Props) {
  const [expandedRunIds, setExpandedRunIds] = useState<Set<string>>(new Set());
  const [logPreviewByRun, setLogPreviewByRun] = useState<Record<string, CogosRunLogsResponse>>({});
  const [outputsByRun, setOutputsByRun] = useState<Record<string, RunOutputsResponse>>({});
  const [loadingRunIds, setLoadingRunIds] = useState<Set<string>>(new Set());
  const [loadingOutputIds, setLoadingOutputIds] = useState<Set<string>>(new Set());
  const [copiedRunId, setCopiedRunId] = useState<string | null>(null);
  const [prettyMode, setPrettyMode] = useState(true);
  const copiedResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copiedResetTimeoutRef.current) {
        clearTimeout(copiedResetTimeoutRef.current);
      }
    };
  }, []);

  const copyRunId = useCallback(async (runId: string) => {
    try {
      await navigator.clipboard.writeText(runId);
      setCopiedRunId(runId);
      if (copiedResetTimeoutRef.current) {
        clearTimeout(copiedResetTimeoutRef.current);
      }
      copiedResetTimeoutRef.current = setTimeout(() => {
        setCopiedRunId((current) => (current === runId ? null : current));
        copiedResetTimeoutRef.current = null;
      }, 1500);
    } catch {
      setCopiedRunId(null);
    }
  }, []);

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

    if (!loadingRunIds.has(runId) && !logPreviewByRun[runId]) {
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
    }

    if (!loadingOutputIds.has(runId) && !outputsByRun[runId]) {
      setLoadingOutputIds((prev) => new Set(prev).add(runId));
      try {
        const outputs = await api.getRunOutputs(cogentName, runId);
        setOutputsByRun((prev) => ({ ...prev, [runId]: outputs }));
      } catch {
        setOutputsByRun((prev) => ({
          ...prev,
          [runId]: { files: [], messages: [], children: [] },
        }));
      } finally {
        setLoadingOutputIds((prev) => {
          const next = new Set(prev);
          next.delete(runId);
          return next;
        });
      }
    }
  }, [cogentName, expandedRunIds, loadingRunIds, loadingOutputIds, logPreviewByRun, outputsByRun]);

  const columns = makeColumns(cogentName, toggleRunLogs);
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
        renderExpandedRow={(row) => (
          <ExpandedRunView
            run={row}
            logState={logPreviewByRun[row.id]}
            logLoading={loadingRunIds.has(row.id)}
            outputs={outputsByRun[row.id]}
            outputsLoading={loadingOutputIds.has(row.id)}
            copiedRunId={copiedRunId}
            copyRunId={copyRunId}
            prettyMode={prettyMode}
            togglePrettyMode={() => setPrettyMode((p) => !p)}
            cogentName={cogentName}
          />
        )}
        getRowStyle={(row) =>
          currentEpoch != null && row.epoch < currentEpoch
            ? { opacity: 0.5 }
            : undefined
        }
      />
    </div>
  );
}
