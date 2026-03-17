"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { fmtCost, fmtMs, fmtNum, fmtTimestamp } from "@/lib/format";
import type {
  RequestFlow,
  RequestFlowEdge,
  RequestFlowNode,
  TimeRange,
} from "@/lib/types";
import * as api from "@/lib/api";

interface RequestFlowsPanelProps {
  cogentName: string;
  timeRange: TimeRange;
  refreshNonce: number;
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  completed: "success",
  delivered: "success",
  running: "accent",
  received: "info",
  queued: "info",
  pending: "warning",
  orphaned: "warning",
  failed: "error",
  timeout: "error",
};

const ALL_STATUS = "__all__";

function shortId(value: string | null | undefined): string {
  if (!value) return "--";
  return value.length > 12 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

function statusVariant(status: string | null | undefined): BadgeVariant {
  return STATUS_VARIANT[status ?? ""] ?? "neutral";
}

function flowSearchBlob(flow: RequestFlow): string {
  const parts = [
    flow.request_id,
    flow.status,
    flow.method ?? "",
    flow.path ?? "",
    flow.root_message.channel_name,
    flow.root_message.message_type ?? "",
    JSON.stringify(flow.root_message.payload),
  ];

  for (const node of flow.nodes) {
    parts.push(
      node.label,
      node.status,
      node.process_name ?? "",
      node.process_id ?? "",
      node.run_id ?? "",
      node.channel_name ?? "",
      node.message_type ?? "",
      node.error ?? "",
    );
  }

  for (const edge of flow.edges) {
    parts.push(
      edge.channel_name,
      edge.message_type ?? "",
      edge.handler_id ?? "",
      edge.message_id,
      edge.status ?? "",
    );
  }

  return parts.join(" ").toLowerCase();
}

function FlowNodeCard({ flow, node }: { flow: RequestFlow; node: RequestFlowNode }) {
  if (node.kind === "request") {
    return (
      <div
        className="rounded-xl border p-4"
        style={{
          background: "linear-gradient(135deg, rgba(37,99,235,0.12), rgba(15,23,42,0.5))",
          borderColor: "rgba(59,130,246,0.25)",
        }}
      >
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
          <Badge variant="info">Request</Badge>
          <Badge variant={statusVariant(flow.status)}>{flow.status}</Badge>
          <span>{fmtTimestamp(flow.started_at)}</span>
        </div>
        <div className="mt-2 text-[15px] font-semibold text-[var(--text-primary)]">
          {flow.method ?? "REQUEST"} {flow.path ?? flow.request_id}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-[var(--text-secondary)]">
          <span>request_id {flow.request_id}</span>
          <span>{flow.root_message.channel_name}</span>
          {flow.root_message.message_type && <span>{flow.root_message.message_type}</span>}
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-xl border p-4"
      style={{
        background: "var(--bg-elevated)",
        borderColor: "var(--border)",
      }}
    >
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
        <Badge variant={statusVariant(node.status)}>{node.status}</Badge>
        {node.runner && <Badge variant="neutral">{node.runner}</Badge>}
        <span>run {shortId(node.run_id)}</span>
      </div>
      <div className="mt-2 text-[14px] font-semibold text-[var(--text-primary)]">
        {node.process_name ?? node.label}
      </div>
      <div className="mt-2 grid gap-1 text-[12px] text-[var(--text-secondary)] md:grid-cols-2">
        <span>started {fmtTimestamp(node.created_at)}</span>
        <span>finished {fmtTimestamp(node.completed_at)}</span>
        <span>duration {fmtMs(node.duration_ms)}</span>
        <span>tokens {fmtNum(node.tokens_in)} in / {fmtNum(node.tokens_out)} out</span>
        <span>cost {fmtCost(node.cost_usd)}</span>
        {node.handler_id && <span>handler {shortId(node.handler_id)}</span>}
      </div>
      {node.error && (
        <div
          className="mt-3 rounded-lg border px-3 py-2 text-[12px]"
          style={{
            background: "rgba(239,68,68,0.08)",
            borderColor: "rgba(239,68,68,0.18)",
            color: "var(--text-secondary)",
          }}
        >
          {node.error}
        </div>
      )}
    </div>
  );
}

function EdgeCard({ edge }: { edge: RequestFlowEdge }) {
  return (
    <div
      className="rounded-lg border px-3 py-3 text-[12px]"
      style={{
        background: "var(--bg-base)",
        borderColor: "var(--border)",
      }}
    >
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
        <Badge variant="accent">{edge.channel_name}</Badge>
        {edge.message_type && <Badge variant="neutral">{edge.message_type}</Badge>}
        {edge.status && <Badge variant={statusVariant(edge.status)}>{edge.status}</Badge>}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[12px] text-[var(--text-secondary)]">
        <span>message {shortId(edge.message_id)}</span>
        <span>handler {shortId(edge.handler_id)}</span>
        <span>emitted {fmtTimestamp(edge.created_at)}</span>
        <span>matched {fmtTimestamp(edge.delivered_at)}</span>
      </div>
    </div>
  );
}

function FlowBranch({
  flow,
  nodeId,
  nodesById,
  childrenBySource,
  seen,
}: {
  flow: RequestFlow;
  nodeId: string;
  nodesById: Map<string, RequestFlowNode>;
  childrenBySource: Map<string, RequestFlowEdge[]>;
  seen: Set<string>;
}) {
  const node = nodesById.get(nodeId);
  if (!node) return null;

  const childEdges = childrenBySource.get(nodeId) ?? [];

  return (
    <div className="space-y-3">
      <FlowNodeCard flow={flow} node={node} />
      {childEdges.length > 0 && (
        <div className="ml-5 space-y-4 border-l pl-4" style={{ borderColor: "var(--border)" }}>
          {childEdges.map((edge) => {
            const target = nodesById.get(edge.target);
            const nextSeen = new Set(seen);
            nextSeen.add(nodeId);

            return (
              <div key={edge.id} className="space-y-2">
                <EdgeCard edge={edge} />
                {target && !seen.has(edge.target) ? (
                  <FlowBranch
                    flow={flow}
                    nodeId={edge.target}
                    nodesById={nodesById}
                    childrenBySource={childrenBySource}
                    seen={nextSeen}
                  />
                ) : target ? (
                  <div className="rounded-lg border px-3 py-2 text-[12px] text-[var(--text-muted)]" style={{ borderColor: "var(--border)" }}>
                    Cycle elided at {target.process_name ?? target.label}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function RequestFlowsPanel({ cogentName, timeRange, refreshNonce }: RequestFlowsPanelProps) {
  const [flows, setFlows] = useState<RequestFlow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState(ALL_STATUS);
  const [expandedRequestIds, setExpandedRequestIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const loadFlows = async (background = false) => {
      if (!background) {
        setLoading(true);
      }
      try {
        const nextFlows = await api.getRequestFlows(cogentName, timeRange, 30);
        if (cancelled) return;
        setFlows(nextFlows);
        setError(null);
        setExpandedRequestIds((current) => {
          if (current.size > 0) return current;
          return nextFlows.length > 0 ? new Set([nextFlows[0].request_id]) : new Set();
        });
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "Could not load request flows.");
      } finally {
        if (!cancelled && !background) {
          setLoading(false);
        }
      }
    };

    void loadFlows();
    intervalId = setInterval(() => {
      void loadFlows(true);
    }, 5000);

    return () => {
      cancelled = true;
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [cogentName, refreshNonce, timeRange]);

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const visibleFlows = flows.filter((flow) => {
    if (statusFilter !== ALL_STATUS && flow.status !== statusFilter) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return flowSearchBlob(flow).includes(normalizedQuery);
  });

  const summary = visibleFlows.reduce(
    (acc, flow) => {
      acc.total += 1;
      if (flow.status === "completed") acc.completed += 1;
      if (flow.status === "running") acc.running += 1;
      if (flow.status === "failed") acc.failed += 1;
      if (flow.status === "orphaned") acc.orphaned += 1;
      return acc;
    },
    { total: 0, completed: 0, running: 0, failed: 0, orphaned: 0 },
  );

  return (
    <div className="space-y-5">
      <section
        className="rounded-2xl border p-5"
        style={{
          background: "linear-gradient(135deg, rgba(15,23,42,0.96), rgba(20,30,48,0.82))",
          borderColor: "var(--border)",
        }}
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-muted)]">
              Request Flows
            </div>
            <div className="max-w-3xl text-[14px] text-[var(--text-secondary)]">
              Follow each `request_id` from the incoming request message through handler matches, process runs,
              downstream channel hops, and terminal completion.
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-[var(--text-secondary)]">
            <Badge variant="info">{summary.total} visible</Badge>
            <Badge variant="success">{summary.completed} completed</Badge>
            <Badge variant="accent">{summary.running} running</Badge>
            <Badge variant="error">{summary.failed} failed</Badge>
            {summary.orphaned > 0 && <Badge variant="warning">{summary.orphaned} orphaned</Badge>}
          </div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px]">
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search request_id, path, process, channel, or message type"
            className="rounded-xl border px-4 py-3 text-[14px] outline-none transition-colors"
            style={{
              background: "var(--bg-base)",
              borderColor: "var(--border)",
              color: "var(--text-primary)",
            }}
          />
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="rounded-xl border px-4 py-3 text-[14px] outline-none transition-colors"
            style={{
              background: "var(--bg-base)",
              borderColor: "var(--border)",
              color: "var(--text-primary)",
            }}
          >
            <option value={ALL_STATUS}>All statuses</option>
            <option value="completed">Completed</option>
            <option value="running">Running</option>
            <option value="failed">Failed</option>
            <option value="orphaned">Orphaned</option>
          </select>
        </div>
      </section>

      {loading && (
        <div className="rounded-xl border px-4 py-6 text-[13px] text-[var(--text-muted)]" style={{ borderColor: "var(--border)" }}>
          Loading request flows...
        </div>
      )}

      {!loading && error && (
        <div
          className="rounded-xl border px-4 py-6 text-[13px]"
          style={{
            background: "rgba(239,68,68,0.08)",
            borderColor: "rgba(239,68,68,0.18)",
            color: "var(--text-secondary)",
          }}
        >
          {error}
        </div>
      )}

      {!loading && !error && visibleFlows.length === 0 && (
        <div className="rounded-xl border px-4 py-6 text-[13px] text-[var(--text-muted)]" style={{ borderColor: "var(--border)" }}>
          No request flows matched the current filters.
        </div>
      )}

      {!loading && !error && visibleFlows.map((flow) => {
        const expanded = expandedRequestIds.has(flow.request_id);
        const nodesById = new Map(flow.nodes.map((node) => [node.id, node]));
        const childrenBySource = new Map<string, RequestFlowEdge[]>();
        for (const edge of flow.edges) {
          const current = childrenBySource.get(edge.source) ?? [];
          current.push(edge);
          current.sort((left, right) => (left.created_at ?? "").localeCompare(right.created_at ?? ""));
          childrenBySource.set(edge.source, current);
        }

        return (
          <section
            key={flow.request_id}
            className="overflow-hidden rounded-2xl border"
            style={{
              background: "var(--bg-elevated)",
              borderColor: "var(--border)",
            }}
          >
            <button
              type="button"
              onClick={() => setExpandedRequestIds((current) => {
                const next = new Set(current);
                if (next.has(flow.request_id)) {
                  next.delete(flow.request_id);
                } else {
                  next.add(flow.request_id);
                }
                return next;
              })}
              className="w-full px-5 py-4 text-left"
            >
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="info">{flow.request_id}</Badge>
                    <Badge variant={statusVariant(flow.status)}>{flow.status}</Badge>
                    {flow.method && <Badge variant="neutral">{flow.method}</Badge>}
                  </div>
                  <div className="text-[15px] font-semibold text-[var(--text-primary)]">
                    {flow.path ?? flow.root_message.channel_name}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-4 text-[12px] text-[var(--text-secondary)]">
                  <span>started {fmtTimestamp(flow.started_at)}</span>
                  <span>duration {fmtMs(flow.duration_ms)}</span>
                  <span>{flow.total_runs} runs</span>
                  <span>{flow.total_edges} bridges</span>
                  <span>{flow.total_messages} messages</span>
                </div>
              </div>
            </button>

            {expanded && (
              <div className="border-t px-5 py-5" style={{ borderColor: "var(--border)" }}>
                <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(360px,0.9fr)]">
                  <div className="space-y-5">
                    <div className="space-y-2">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-muted)]">
                        Process Graph
                      </div>
                      <FlowBranch
                        flow={flow}
                        nodeId={`request:${flow.request_id}`}
                        nodesById={nodesById}
                        childrenBySource={childrenBySource}
                        seen={new Set()}
                      />
                    </div>

                    <div className="space-y-2">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-muted)]">
                        Root Payload
                      </div>
                      <JsonViewer data={flow.root_message.payload} />
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-muted)]">
                      Timeline
                    </div>
                    <div className="space-y-2">
                      {flow.timeline.map((entry) => (
                        <div
                          key={entry.id}
                          className="rounded-xl border px-4 py-3"
                          style={{
                            background: "var(--bg-base)",
                            borderColor: "var(--border)",
                          }}
                        >
                          <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
                            <Badge variant={statusVariant(entry.status ?? entry.kind)}>{entry.kind.replaceAll("_", " ")}</Badge>
                            {entry.status && <Badge variant={statusVariant(entry.status)}>{entry.status}</Badge>}
                            <span>{fmtTimestamp(entry.timestamp)}</span>
                          </div>
                          <div className="mt-2 text-[13px] font-medium text-[var(--text-primary)]">
                            {entry.title}
                          </div>
                          {entry.detail && (
                            <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                              {entry.detail}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
