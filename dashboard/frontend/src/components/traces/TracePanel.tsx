"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { buildCogentRunLogsUrl } from "@/lib/cloudwatch";
import { fmtCost, fmtMs, fmtNum, fmtTimestamp } from "@/lib/format";
import type { CogosChannel, MessageTrace, TimeRange, TraceDelivery, TraceMessage } from "@/lib/types";
import * as api from "@/lib/api";

interface TracePanelProps {
  traces: MessageTrace[];
  cogentName: string;
  timeRange: TimeRange;
  onRefresh?: () => Promise<void> | void;
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const DELIVERY_STATUS_VARIANT: Record<string, BadgeVariant> = {
  pending: "warning",
  queued: "info",
  delivered: "success",
  skipped: "neutral",
};

const RUN_STATUS_VARIANT: Record<string, BadgeVariant> = {
  running: "accent",
  completed: "success",
  failed: "error",
  timeout: "warning",
  suspended: "neutral",
};

const UNTYPED_FILTER_VALUE = "__untyped__";
const FILTER_FETCH_LIMIT = 100;
const TRACE_FILTERS_STORAGE_PREFIX = "cogent.trace-panel.filters:";

const MESSAGE_CATEGORIES = ["system", "io", "other"] as const;
type MessageCategory = (typeof MESSAGE_CATEGORIES)[number];

interface PersistedTraceFilters {
  searchQuery?: string;
  hiddenCategories?: MessageCategory[];
}

function shortId(value: string | null | undefined): string {
  if (!value) return "--";
  return value.length > 12 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

function payloadPreview(payload: Record<string, unknown>): string {
  const entries = Object.entries(payload);
  if (entries.length === 0) return "{}";

  return entries
    .slice(0, 3)
    .map(([key, value]) => {
      if (typeof value === "string") return `${key}=${value}`;
      if (typeof value === "number" || typeof value === "boolean") return `${key}=${String(value)}`;
      return `${key}=${JSON.stringify(value)}`;
    })
    .join(" · ");
}

function emittedCount(deliveries: TraceDelivery[]): number {
  return deliveries.reduce((count, delivery) => count + delivery.emitted_messages.length, 0);
}

function normalizeMessageType(messageType: string | null | undefined): string {
  return messageType?.trim() ? messageType : UNTYPED_FILTER_VALUE;
}

function displayMessageType(messageType: string | null | undefined): string {
  return normalizeMessageType(messageType) === UNTYPED_FILTER_VALUE ? "untyped" : String(messageType);
}

function displayTraceId(traceId: string | null | undefined): string | null {
  return traceId?.trim() ? traceId : null;
}

function isMessageCategory(value: string): value is MessageCategory {
  return (MESSAGE_CATEGORIES as readonly string[]).includes(value);
}

function traceFiltersStorageKey(cogentName: string): string {
  return `${TRACE_FILTERS_STORAGE_PREFIX}${cogentName}`;
}

function loadPersistedTraceFilters(cogentName: string): PersistedTraceFilters | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(traceFiltersStorageKey(cogentName));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedTraceFilters;
    return {
      searchQuery: typeof parsed.searchQuery === "string" ? parsed.searchQuery : "",
      hiddenCategories: Array.isArray(parsed.hiddenCategories)
        ? parsed.hiddenCategories.filter((value): value is MessageCategory => typeof value === "string" && isMessageCategory(value))
        : [],
    };
  } catch {
    return null;
  }
}

function persistTraceFilters(cogentName: string, filters: PersistedTraceFilters) {
  if (typeof window === "undefined") return;
  const next: PersistedTraceFilters = {
    searchQuery: filters.searchQuery?.trim() ? filters.searchQuery : "",
    hiddenCategories: filters.hiddenCategories?.filter(isMessageCategory) ?? [],
  };
  if (!next.searchQuery && (next.hiddenCategories?.length ?? 0) === 0) {
    window.localStorage.removeItem(traceFiltersStorageKey(cogentName));
    return;
  }
  window.localStorage.setItem(traceFiltersStorageKey(cogentName), JSON.stringify(next));
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value) ?? "";
  } catch {
    return "";
  }
}

function prettyJson(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "{}";
  }
}

function buildPayloadTemplateValue(typeSpec: unknown): unknown {
  if (typeSpec && typeof typeSpec === "object" && !Array.isArray(typeSpec)) {
    return Object.fromEntries(
      Object.entries(typeSpec as Record<string, unknown>).map(([key, value]) => [
        key,
        buildPayloadTemplateValue(value),
      ]),
    );
  }

  if (typeof typeSpec !== "string") {
    return {};
  }

  if (typeSpec === "string") return "";
  if (typeSpec === "number") return 0;
  if (typeSpec === "bool") return false;
  if (typeSpec === "dict") return {};
  if (typeSpec === "list" || typeSpec.startsWith("list[")) return [];
  return {};
}

function buildPayloadTemplate(channel: CogosChannel | null): Record<string, unknown> {
  const schema = channel?.schema_definition;
  if (!schema || typeof schema !== "object") {
    return {};
  }
  const rawFields = "fields" in schema
    ? (schema.fields as Record<string, unknown> | undefined)
    : (schema as Record<string, unknown>);
  if (!rawFields || typeof rawFields !== "object" || Array.isArray(rawFields)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(rawFields).map(([key, value]) => [key, buildPayloadTemplateValue(value)]),
  );
}

function traceSearchBlob(trace: MessageTrace): string {
  const parts: string[] = [
    trace.message.channel_name,
    trace.message.message_type ?? "",
    trace.message.request_id ?? "",
    trace.message.trace_id ?? "",
    trace.message.sender_process_name ?? "",
    trace.message.sender_process ?? "",
    payloadPreview(trace.message.payload),
    safeJson(trace.message.payload),
  ];

  for (const delivery of trace.deliveries) {
    parts.push(
      delivery.status,
      delivery.handler_id,
      delivery.process_name ?? "",
      delivery.process_id ?? "",
      delivery.run?.id ?? "",
      delivery.run?.status ?? "",
    );

    for (const emitted of delivery.emitted_messages) {
      parts.push(
        emitted.channel_name,
        emitted.message_type ?? "",
        emitted.request_id ?? "",
        emitted.trace_id ?? "",
        payloadPreview(emitted.payload),
        safeJson(emitted.payload),
      );
    }
  }

  return parts.join(" ").toLowerCase();
}

function MessageTypeBadge({
  messageType,
  variant = "accent",
}: {
  messageType: string | null | undefined;
  variant?: BadgeVariant;
}) {
  const normalized = normalizeMessageType(messageType);
  return (
    <Badge variant={normalized === UNTYPED_FILTER_VALUE ? "neutral" : variant}>
      {displayMessageType(messageType)}
    </Badge>
  );
}

function TraceMessageCard({
  message,
  onPrefill,
}: {
  message: TraceMessage;
  onPrefill?: (message: TraceMessage) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
          <Badge variant="info">{message.channel_name}</Badge>
          <MessageTypeBadge messageType={message.message_type} />
          <span>message {shortId(message.id)}</span>
          {displayTraceId(message.trace_id) && <span>trace {shortId(message.trace_id)}</span>}
          <span>sender {message.sender_process_name ?? message.sender_process ?? "external"}</span>
          <span>{fmtTimestamp(message.created_at)}</span>
        </div>
        {onPrefill && (
          <button
            type="button"
            onClick={() => onPrefill(message)}
            className="rounded-md border px-2 py-1 text-[10px] font-medium uppercase tracking-wide transition-colors"
            style={{
              background: "transparent",
              borderColor: "var(--border)",
              color: "var(--text-muted)",
            }}
          >
            Prefill Composer
          </button>
        )}
      </div>
      <div className="text-[12px] text-[var(--text-secondary)] font-mono">
        {payloadPreview(message.payload)}
      </div>
      <JsonViewer data={message.payload} />
    </div>
  );
}

function LoadingSpinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
      <span
        aria-hidden="true"
        className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--accent)]"
      />
      <span>{label}</span>
    </span>
  );
}

export function TracePanel({ traces, cogentName, timeRange, onRefresh }: TracePanelProps) {
  const [expandedMessageIds, setExpandedMessageIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [hiddenCategories, setHiddenCategories] = useState<Set<MessageCategory>>(new Set());
  const [filteredTraceResults, setFilteredTraceResults] = useState<MessageTrace[] | null>(null);
  const [filterLoading, setFilterLoading] = useState(false);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [channels, setChannels] = useState<CogosChannel[]>([]);
  const [channelsLoading, setChannelsLoading] = useState(false);
  const [channelsError, setChannelsError] = useState<string | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [payloadDraft, setPayloadDraft] = useState("{}");
  const [composerError, setComposerError] = useState<string | null>(null);
  const [composerSuccess, setComposerSuccess] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const skipNextChannelAutofill = useRef(false);
  const skipNextFilterPersist = useRef(true);
  const hasServerFilters = hiddenCategories.size > 0;

  useEffect(() => {
    skipNextFilterPersist.current = true;
    const persisted = loadPersistedTraceFilters(cogentName);
    setSearchQuery(persisted?.searchQuery ?? "");
    setHiddenCategories(new Set(persisted?.hiddenCategories ?? []));
  }, [cogentName]);

  useEffect(() => {
    if (skipNextFilterPersist.current) {
      skipNextFilterPersist.current = false;
      return;
    }
    persistTraceFilters(cogentName, {
      searchQuery,
      hiddenCategories: Array.from(hiddenCategories),
    });
  }, [cogentName, hiddenCategories, searchQuery]);

  useEffect(() => {
    let cancelled = false;

    const loadChannels = async () => {
      setChannelsLoading(true);
      setChannelsError(null);
      try {
        const next = await api.getChannels(cogentName, "named");
        if (cancelled) return;
        setChannels(
          [...next].sort((left, right) => left.name.localeCompare(right.name)),
        );
      } catch (error) {
        if (cancelled) return;
        setChannels([]);
        setChannelsError(error instanceof Error ? error.message : "Could not load named channels.");
      } finally {
        if (!cancelled) {
          setChannelsLoading(false);
        }
      }
    };

    void loadChannels();

    return () => {
      cancelled = true;
    };
  }, [cogentName]);

  useEffect(() => {
    let cancelled = false;

    if (!hasServerFilters) {
      setFilteredTraceResults(null);
      setFilterLoading(false);
      setFilterError(null);
      return;
    }

    const loadFilteredTraces = async () => {
      setFilterLoading(true);
      setFilterError(null);
      try {
        const next = await api.getMessageTraces(cogentName, timeRange, {
          categories: MESSAGE_CATEGORIES.filter((c) => !hiddenCategories.has(c)),
          limit: FILTER_FETCH_LIMIT,
        });
        if (!cancelled) {
          setFilteredTraceResults(next);
        }
      } catch (error) {
        if (!cancelled) {
          setFilterError(error instanceof Error ? error.message : "Could not load filtered traces.");
        }
      } finally {
        if (!cancelled) {
          setFilterLoading(false);
        }
      }
    };

    void loadFilteredTraces();

    return () => {
      cancelled = true;
    };
  }, [cogentName, hasServerFilters, hiddenCategories, timeRange, traces]);

  const traceSource = hasServerFilters ? (filteredTraceResults ?? traces) : traces;
  const sendableChannels = useMemo(
    () => channels.filter((channel) => channel.channel_type === "named" && !channel.closed_at),
    [channels],
  );
  const selectedChannel = useMemo(
    () => sendableChannels.find((channel) => channel.id === selectedChannelId) ?? null,
    [sendableChannels, selectedChannelId],
  );
  const selectedChannelTemplate = useMemo(
    () => prettyJson(buildPayloadTemplate(selectedChannel)),
    [selectedChannel],
  );
  const payloadValidation = useMemo(() => {
    const trimmed = payloadDraft.trim();
    if (!trimmed) {
      return { payload: null, error: "Payload is required." };
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { payload: null, error: "Payload must be a JSON object." };
      }
      return { payload: parsed as Record<string, unknown>, error: null };
    } catch (error) {
      return {
        payload: null,
        error: error instanceof Error ? error.message : "Invalid JSON payload.",
      };
    }
  }, [payloadDraft]);
  const visibleTraces = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    if (!normalizedQuery) return traceSource;
    return traceSource.filter((trace) => traceSearchBlob(trace).includes(normalizedQuery));
  }, [searchQuery, traceSource]);

  useEffect(() => {
    setSelectedChannelId((prev) => {
      if (prev && sendableChannels.some((channel) => channel.id === prev)) {
        return prev;
      }
      return sendableChannels[0]?.id ?? "";
    });
  }, [sendableChannels]);

  useEffect(() => {
    if (!selectedChannel) {
      return;
    }
    if (skipNextChannelAutofill.current) {
      skipNextChannelAutofill.current = false;
      return;
    }
    setPayloadDraft(selectedChannelTemplate);
    setComposerError(null);
    setComposerSuccess(null);
  }, [selectedChannel, selectedChannelTemplate]);

  useEffect(() => {
    const visibleIds = new Set(visibleTraces.map((trace) => trace.message.id));
    setExpandedMessageIds((prev) => new Set(Array.from(prev).filter((id) => visibleIds.has(id))));
  }, [visibleTraces]);

  const summary = useMemo(() => {
    return visibleTraces.reduce(
      (acc, trace) => {
        acc.deliveries += trace.deliveries.length;
        acc.runs += trace.deliveries.filter((delivery) => delivery.run).length;
        acc.emitted += emittedCount(trace.deliveries);
        return acc;
      },
      { deliveries: 0, runs: 0, emitted: 0 },
    );
  }, [visibleTraces]);

  const toggleExpanded = (messageId: string) => {
    setExpandedMessageIds((prev) => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  };

  const clearFilters = () => {
    setSearchQuery("");
    setHiddenCategories(new Set());
  };

  const toggleCategory = (category: MessageCategory) => {
    setHiddenCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  const clearComposer = () => {
    setPayloadDraft("{}");
    setComposerError(null);
    setComposerSuccess(null);
  };

  const prefillComposer = (message: TraceMessage) => {
    setPayloadDraft(prettyJson(message.payload));
    setComposerSuccess(null);
    const matchingChannel = sendableChannels.find((channel) => channel.id === message.channel_id);
    if (matchingChannel) {
      skipNextChannelAutofill.current = true;
      setSelectedChannelId(matchingChannel.id);
      setComposerError(null);
      return;
    }
    setComposerError(
      `Prefilled payload from ${message.channel_name}. Select a named channel to send it.`,
    );
  };

  const sendMessage = async () => {
    if (!selectedChannelId || !payloadValidation.payload || sending) {
      return;
    }
    setSending(true);
    setComposerError(null);
    setComposerSuccess(null);
    try {
      const result = await api.sendChannelMessage(
        cogentName,
        selectedChannelId,
        payloadValidation.payload,
      );
      setComposerSuccess(`Sent ${shortId(result.id)} to ${result.channel_name}.`);
      if (onRefresh) {
        try {
          await onRefresh();
        } catch {
          // Preserve the send success state even if the follow-up refresh fails.
        }
      }
    } catch (error) {
      setComposerError(error instanceof Error ? error.message : "Could not send message.");
    } finally {
      setSending(false);
    }
  };

  const hasClientFilters = searchQuery.trim().length > 0;
  const hasAnyFilters = hasServerFilters || hasClientFilters;
  const emptyMessage = hasAnyFilters
    ? "No channel message traces matched the current filters."
    : "No channel message traces in this time window.";
  const showLoadingState = hasServerFilters && filterLoading && traceSource.length === 0;
  const canSend = !!selectedChannelId && payloadValidation.error === null && !sending && !channelsLoading;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Message Trace
          <span className="ml-2 text-[var(--text-muted)] font-normal">({visibleTraces.length})</span>
        </h2>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="info">{summary.deliveries} deliveries</Badge>
          <Badge variant="accent">{summary.runs} runs</Badge>
          <Badge variant="success">{summary.emitted} emitted</Badge>
        </div>
      </div>

      <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Compose Message</h3>
            <div className="text-[11px] text-[var(--text-muted)]">
              Send test traffic to named channels and replay payloads from traces.
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="neutral">named channels only</Badge>
            {selectedChannel && <Badge variant="info">{selectedChannel.subscriber_count} subscribers</Badge>}
          </div>
        </div>

        <div className="grid gap-3 xl:grid-cols-[280px_minmax(0,1fr)]">
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="block text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                Channel
              </label>
              <select
                value={selectedChannelId}
                onChange={(event) => setSelectedChannelId(event.target.value)}
                disabled={channelsLoading || sendableChannels.length === 0}
                className="w-full rounded-md border px-3 py-2 text-[12px] font-mono disabled:opacity-60"
                style={{
                  background: "var(--bg-base)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              >
                {sendableChannels.length === 0 && (
                  <option value="">
                    {channelsLoading ? "loading channels..." : "no named channels"}
                  </option>
                )}
                {sendableChannels.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="rounded-md border border-[var(--border)] bg-[var(--bg-deep)] px-3 py-3 text-[11px] text-[var(--text-muted)] space-y-1">
              {selectedChannel ? (
                <>
                  <div>{selectedChannel.message_count} messages so far</div>
                  <div>
                    {selectedChannel.schema_definition
                      ? `Schema: ${selectedChannel.schema_name ?? "inline"}`
                      : "Schema: none, any JSON object is allowed"}
                  </div>
                  <div>
                    {selectedChannel.schema_definition
                      ? "Payload will be checked against the schema when you click Send."
                      : "No channel schema is attached, so only JSON-object shape is checked locally."}
                  </div>
                </>
              ) : (
                <div>Select a named channel to send a message.</div>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <label className="block text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
              Payload JSON
            </label>
            <textarea
              value={payloadDraft}
              onChange={(event) => setPayloadDraft(event.target.value)}
              spellCheck={false}
              rows={10}
              placeholder='{"message_type":"example:request"}'
              className="w-full rounded-md border px-3 py-2 text-[12px] font-mono"
              style={{
                background: "var(--bg-base)",
                borderColor: "var(--border)",
                color: "var(--text-primary)",
              }}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-[11px] text-[var(--text-muted)]">
                Prefill from any expanded trace message or emitted message below.
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={clearComposer}
                  className="rounded-md border px-3 py-2 text-[11px] font-medium uppercase tracking-wide transition-colors"
                  style={{
                    background: "transparent",
                    borderColor: "var(--border)",
                    color: "var(--text-muted)",
                  }}
                >
                  Clear
                </button>
                <button
                  type="button"
                  onClick={() => void sendMessage()}
                  disabled={!canSend}
                  className="rounded-md border px-3 py-2 text-[11px] font-medium uppercase tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                  style={{
                    background: "var(--accent)",
                    borderColor: "var(--accent)",
                    color: "var(--bg-base)",
                  }}
                >
                  {sending ? "Sending..." : "Send"}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
          {channelsLoading && <span>Loading named channels...</span>}
          {channelsError && <span className="text-red-400">{channelsError}</span>}
          {payloadValidation.error && <span className="text-red-400">{payloadValidation.error}</span>}
          {composerError && <span className="text-red-400">{composerError}</span>}
          {composerSuccess && <span className="text-emerald-300">{composerSuccess}</span>}
        </div>
      </div>

      <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[200px]">
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="search channel, sender, type, payload..."
              className="w-full rounded-md border px-3 py-2 text-[12px] font-mono"
              style={{
                background: "var(--bg-base)",
                borderColor: "var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>

          <div className="flex items-center gap-1.5">
            {MESSAGE_CATEGORIES.map((cat) => {
              const hidden = hiddenCategories.has(cat);
              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => toggleCategory(cat)}
                  className="rounded-full border px-3 py-1.5 text-[11px] font-medium font-mono transition-colors"
                  style={{
                    background: hidden ? "transparent" : "var(--bg-deep)",
                    borderColor: "var(--border)",
                    color: hidden ? "var(--text-muted)" : "var(--text-primary)",
                    opacity: hidden ? 0.4 : 1,
                    textDecoration: hidden ? "line-through" : "none",
                  }}
                >
                  {cat}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={clearFilters}
            disabled={!hasAnyFilters}
            className="rounded-md border px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              background: "transparent",
              borderColor: "var(--border)",
              color: "var(--text-muted)",
            }}
          >
            Clear
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
          <span>{visibleTraces.length} trace{visibleTraces.length === 1 ? "" : "s"} in view</span>
          {hiddenCategories.size > 0 && <Badge variant="accent">hiding {Array.from(hiddenCategories).join(", ")}</Badge>}
          {hasClientFilters && <Badge variant="info">search filtered</Badge>}
          {filterLoading && <LoadingSpinner label="Updating results..." />}
          {filterError && <span className="text-red-400">{filterError}</span>}
        </div>
      </div>

      {showLoadingState && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-8 text-center text-[12px] text-[var(--text-muted)]">
          <div className="flex items-center justify-center">
            <LoadingSpinner label="Loading filtered traces..." />
          </div>
        </div>
      )}

      {!showLoadingState && visibleTraces.length === 0 && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-8 text-center text-[12px] text-[var(--text-muted)]">
          {emptyMessage}
        </div>
      )}

      {visibleTraces.map((trace) => {
        const { message, deliveries } = trace;
        const isExpanded = expandedMessageIds.has(message.id);
        const targetNames = Array.from(
          new Set(deliveries.map((delivery) => delivery.process_name ?? delivery.process_id ?? "unknown")),
        );

        return (
          <div
            key={message.id}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] overflow-hidden"
          >
            <button
              type="button"
              className="w-full border-0 bg-transparent px-4 py-3 text-left cursor-pointer"
              onClick={() => toggleExpanded(message.id)}
            >
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="info">{message.channel_name}</Badge>
                    <MessageTypeBadge messageType={message.message_type} />
                    {displayTraceId(message.trace_id) && (
                      <Badge variant="neutral">trace {shortId(message.trace_id)}</Badge>
                    )}
                    <span className="text-[11px] text-[var(--text-muted)] font-mono">{shortId(message.id)}</span>
                    <span className="text-[11px] text-[var(--text-muted)]">
                      {message.sender_process_name ?? message.sender_process ?? "external sender"}
                    </span>
                  </div>
                  <div className="text-[12px] text-[var(--text-secondary)] font-mono truncate">
                    {payloadPreview(message.payload)}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {targetNames.map((target) => (
                      <Badge key={target} variant="neutral">{target}</Badge>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1 text-[11px] text-[var(--text-muted)]">
                  <span>{deliveries.length} delivery{deliveries.length === 1 ? "" : "ies"}</span>
                  <span>{deliveries.filter((delivery) => delivery.run).length} run{deliveries.filter((delivery) => delivery.run).length === 1 ? "" : "s"}</span>
                  <span>{emittedCount(deliveries)} emitted</span>
                  <span>{fmtTimestamp(message.created_at)}</span>
                </div>
              </div>
            </button>

            {isExpanded && (
              <div className="border-t border-[var(--border)] bg-[var(--bg-deep)] px-4 py-4 space-y-4">
                <TraceMessageCard message={message} onPrefill={prefillComposer} />

                {deliveries.length === 0 ? (
                  <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-3 text-[12px] text-[var(--text-muted)]">
                    No deliveries were created for this message.
                  </div>
                ) : (
                  deliveries.map((delivery) => {
                    const run = delivery.run;
                    return (
                      <div
                        key={delivery.id}
                        className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3 space-y-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={DELIVERY_STATUS_VARIANT[delivery.status] || "neutral"}>
                              {delivery.status}
                            </Badge>
                            <span className="text-[12px] text-[var(--text-primary)] font-medium">
                              {delivery.process_name ?? delivery.process_id ?? "Unknown process"}
                            </span>
                            <span className="text-[11px] text-[var(--text-muted)] font-mono">
                              handler {shortId(delivery.handler_id)}
                            </span>
                          </div>
                          <span className="text-[11px] text-[var(--text-muted)]">
                            {fmtTimestamp(delivery.created_at)}
                          </span>
                        </div>

                        {run ? (
                          <div className="space-y-3">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex flex-wrap items-center gap-2 text-[12px] text-[var(--text-secondary)]">
                                <Badge variant={RUN_STATUS_VARIANT[run.status] || "neutral"}>
                                  {run.status}
                                </Badge>
                                <span className="font-mono">run {shortId(run.id)}</span>
                                <span>{run.process_name ?? run.process}</span>
                              </div>
                              <a
                                href={buildCogentRunLogsUrl(cogentName, run.id, run.created_at, run.runner)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[12px] text-[var(--accent)] hover:underline"
                              >
                                CloudWatch logs
                              </a>
                            </div>

                            <div className="grid gap-2 text-[11px] text-[var(--text-muted)] md:grid-cols-4">
                              <span>created {fmtTimestamp(run.created_at)}</span>
                              <span>duration {fmtMs(run.duration_ms)}</span>
                              <span>tokens {fmtNum(run.tokens_in)} in / {fmtNum(run.tokens_out)} out</span>
                              <span>cost {fmtCost(run.cost_usd)}</span>
                            </div>

                            {run.error && (
                              <div className="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-[12px] text-red-200 font-mono">
                                {run.error}
                              </div>
                            )}

                            {run.result && (
                              <div className="space-y-2">
                                <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">Run Result</div>
                                <JsonViewer data={run.result} />
                              </div>
                            )}

                            {delivery.emitted_messages.length > 0 && (
                              <div className="space-y-2">
                                <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">
                                  Emitted Messages ({delivery.emitted_messages.length})
                                </div>
                                {delivery.emitted_messages.map((emitted) => (
                                  <div
                                    key={emitted.id}
                                    className="rounded-md border border-[var(--border)] bg-[var(--bg-deep)] px-3 py-3 space-y-2"
                                  >
                                    <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
                                      <Badge variant="accent">{emitted.channel_name}</Badge>
                                      <MessageTypeBadge messageType={emitted.message_type} variant="warning" />
                                      <span className="font-mono">{shortId(emitted.id)}</span>
                                      <span>{fmtTimestamp(emitted.created_at)}</span>
                                      <button
                                        type="button"
                                        onClick={() => prefillComposer(emitted)}
                                        className="ml-auto rounded-md border px-2 py-1 text-[10px] font-medium uppercase tracking-wide transition-colors"
                                        style={{
                                          background: "transparent",
                                          borderColor: "var(--border)",
                                          color: "var(--text-muted)",
                                        }}
                                      >
                                        Prefill Composer
                                      </button>
                                    </div>
                                    <div className="text-[12px] text-[var(--text-secondary)] font-mono">
                                      {payloadPreview(emitted.payload)}
                                    </div>
                                    <JsonViewer data={emitted.payload} />
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        ) : (
                          <div className="text-[12px] text-[var(--text-muted)]">
                            No run has been dispatched for this delivery yet.
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
