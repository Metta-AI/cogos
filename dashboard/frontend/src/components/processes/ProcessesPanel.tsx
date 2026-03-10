"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import type { CogosProcess, CogosProcessRun, Resource, CogosRun, CogosFile, CogosCapability } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import * as api from "@/lib/api";
import { fmtTimestamp } from "@/lib/format";

interface Props {
  processes: CogosProcess[];
  cogentName: string;
  onRefresh: () => void;
  resources: Resource[];
  runs: CogosRun[];
  files: CogosFile[];
  capabilities: CogosCapability[];
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

const STATUSES = ["waiting", "runnable", "running", "completed", "disabled", "blocked", "suspended"];
const MODES: ("daemon" | "one_shot")[] = ["one_shot", "daemon"];
const RUNNERS = ["lambda", "ecs"];
const DEFAULT_MODEL = "us.anthropic.claude-opus-4-20250514-v1:0";

const INPUT_CLS = "bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] w-full";

interface CapabilityConfig {
  allowed_methods?: string[];
}

interface ProcessForm {
  name: string;
  mode: "daemon" | "one_shot";
  content: string;
  files: string[]; // file keys
  priority: string;
  runner: string;
  status: string;
  model: string;
  max_duration_val: string;
  max_duration_unit: "ms" | "s" | "m" | "h" | "d";
  max_retries: string;
  preemptible: boolean;
  clear_context: boolean;
  resources: string[];
  capabilities: string[];
  capabilityConfigs: Record<string, CapabilityConfig>;
}

const EMPTY_FORM: ProcessForm = {
  name: "",
  mode: "one_shot",
  content: "",
  files: [],
  priority: "0",
  runner: "lambda",
  status: "runnable",
  model: DEFAULT_MODEL,
  max_duration_val: "",
  max_duration_unit: "m",
  max_retries: "0",
  preemptible: false,
  clear_context: false,
  resources: [],
  capabilities: [],
  capabilityConfigs: {},
};

const DURATION_UNITS = { ms: 1, s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000 } as const;
type DurationUnit = keyof typeof DURATION_UNITS;

function msToFormDuration(ms: number | null): { max_duration_val: string; max_duration_unit: DurationUnit } {
  if (ms == null || ms === 0) return { max_duration_val: "", max_duration_unit: "m" };
  for (const u of ["d", "h", "m", "s", "ms"] as DurationUnit[]) {
    const factor = DURATION_UNITS[u];
    if (ms % factor === 0) return { max_duration_val: String(ms / factor), max_duration_unit: u };
  }
  return { max_duration_val: String(ms), max_duration_unit: "ms" };
}

function formDurationToMs(val: string, unit: DurationUnit): number | null {
  const n = parseFloat(val);
  if (!val || isNaN(n)) return null;
  return Math.round(n * DURATION_UNITS[unit]);
}

function formFromProcess(p: CogosProcess, fileKeys?: string[], capNames?: string[], capConfigs?: Record<string, CapabilityConfig>): ProcessForm {
  return {
    name: p.name,
    mode: p.mode,
    content: p.content,
    files: fileKeys ?? [],
    priority: String(p.priority),
    runner: p.runner,
    status: p.status,
    model: p.model || DEFAULT_MODEL,
    ...msToFormDuration(p.max_duration_ms),
    max_retries: String(p.max_retries),
    preemptible: p.preemptible,
    clear_context: p.clear_context,
    resources: p.resources ?? [],
    capabilities: capNames ?? [],
    capabilityConfigs: capConfigs ?? {},
  };
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return `${m}m${rem}s`;
}

function fmtTokens(n: number): string {
  if (n === 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

const AWS_REGION = "us-east-1";

function buildCloudWatchUrl(cogentName: string, runId: string, createdAt: string | null): string {
  const safeName = cogentName.replace(/\./g, "-");
  const logGroup = `/aws/lambda/cogent-${safeName}-executor`;
  const query = `fields @timestamp, @message | filter @message like "${runId}" | sort @timestamp asc`;
  const encodedQuery = encodeURIComponent(query)
    .replace(/%20/g, "*20")
    .replace(/%22/g, "*22")
    .replace(/%7C/g, "*7c")
    .replace(/%40/g, "*40")
    .replace(/%0A/g, "*0a");
  let startParam = "start~-3600~timeType~'RELATIVE~unit~'seconds";
  if (createdAt) {
    const ts = new Date(createdAt).getTime();
    const start = ts - 60 * 60 * 1000;
    const end = ts + 60 * 60 * 1000;
    startParam = `start~${start}~end~${end}~timeType~'ABSOLUTE`;
  }
  const encodedSource = logGroup.replace(/\//g, "*2f");
  return (
    `https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}` +
    `#logsV2:logs-insights$3FqueryDetail$3D~(` +
    `${startParam}` +
    `~editorString~'${encodedQuery}` +
    `~source~(~'${encodedSource}))`
  );
}

/* ── TagListEditor: editable list with typeahead ── */

function TagListEditor({
  label,
  items,
  onChange,
  suggestions,
}: {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  suggestions: string[];
}) {
  const [query, setQuery] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    if (!query) return suggestions.filter((s) => !items.includes(s)).slice(0, 8);
    const q = query.toLowerCase();
    return suggestions
      .filter((s) => s.toLowerCase().includes(q) && !items.includes(s))
      .slice(0, 8);
  }, [query, suggestions, items]);

  const addItem = useCallback((val: string) => {
    const trimmed = val.trim();
    if (trimmed && !items.includes(trimmed)) {
      onChange([...items, trimmed]);
    }
    setQuery("");
    setShowSuggestions(false);
  }, [items, onChange]);

  const removeItem = useCallback((idx: number) => {
    onChange(items.filter((_, i) => i !== idx));
  }, [items, onChange]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={wrapperRef}>
      {label && <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">{label}</label>}
      {items.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1">
          {items.map((item, idx) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono"
              style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
            >
              {item}
              <button
                onClick={() => removeItem(idx)}
                className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--error)] text-[10px] leading-none p-0"
              >
                x
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setShowSuggestions(true); }}
          onFocus={() => setShowSuggestions(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (filtered.length > 0) addItem(filtered[0]);
              else if (query.trim()) addItem(query);
            }
            if (e.key === "Escape") setShowSuggestions(false);
          }}
          placeholder={`Add ${label.toLowerCase()}...`}
          className={INPUT_CLS}
          style={{ fontSize: "11px" }}
        />
        {showSuggestions && filtered.length > 0 && (
          <div
            className="absolute z-50 left-0 right-0 mt-1 rounded overflow-hidden shadow-lg"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", maxHeight: "160px", overflowY: "auto" }}
          >
            {filtered.map((s) => (
              <button
                key={s}
                onClick={() => addItem(s)}
                className="w-full text-left px-2 py-1 text-[11px] font-mono border-0 cursor-pointer"
                style={{ background: "transparent", color: "var(--text-secondary)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── CapabilityEditor: capability tags with clickable method selection ── */

function CapabilityEditor({
  items,
  configs,
  onChange,
  onConfigChange,
  suggestions,
  cogentName,
}: {
  items: string[];
  configs: Record<string, CapabilityConfig>;
  onChange: (items: string[]) => void;
  onConfigChange: (configs: Record<string, CapabilityConfig>) => void;
  suggestions: string[];
  cogentName: string;
}) {
  const [query, setQuery] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [expandedCap, setExpandedCap] = useState<string | null>(null);
  const [methodsCache, setMethodsCache] = useState<Record<string, api.CapabilityMethod[]>>({});
  const [loadingMethods, setLoadingMethods] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    if (!query) return suggestions.filter((s) => !items.includes(s)).slice(0, 8);
    const q = query.toLowerCase();
    return suggestions.filter((s) => s.toLowerCase().includes(q) && !items.includes(s)).slice(0, 8);
  }, [query, suggestions, items]);

  const addItem = useCallback((val: string) => {
    const trimmed = val.trim();
    if (trimmed && !items.includes(trimmed)) onChange([...items, trimmed]);
    setQuery("");
    setShowSuggestions(false);
  }, [items, onChange]);

  const removeItem = useCallback((idx: number) => {
    const removed = items[idx];
    onChange(items.filter((_, i) => i !== idx));
    const next = { ...configs };
    delete next[removed];
    onConfigChange(next);
    if (expandedCap === removed) setExpandedCap(null);
  }, [items, onChange, configs, onConfigChange, expandedCap]);

  const toggleCapExpand = useCallback(async (capName: string) => {
    if (expandedCap === capName) {
      setExpandedCap(null);
      return;
    }
    setExpandedCap(capName);
    if (!methodsCache[capName]) {
      setLoadingMethods(capName);
      try {
        const methods = await api.getCapabilityMethods(cogentName, capName);
        setMethodsCache((prev) => ({ ...prev, [capName]: methods }));
      } catch {
        setMethodsCache((prev) => ({ ...prev, [capName]: [] }));
      }
      setLoadingMethods(null);
    }
  }, [expandedCap, methodsCache, cogentName]);

  const toggleMethod = useCallback((capName: string, methodName: string) => {
    const current = configs[capName]?.allowed_methods ?? [];
    const allMethods = (methodsCache[capName] ?? []).map((m) => m.name);
    let next: string[];
    if (current.includes(methodName)) {
      next = current.filter((m) => m !== methodName);
    } else {
      next = [...current, methodName];
    }
    // If all methods selected or none, clear the restriction
    const cfg = next.length > 0 && next.length < allMethods.length
      ? { allowed_methods: next }
      : {};
    onConfigChange({ ...configs, [capName]: cfg });
  }, [configs, onConfigChange, methodsCache]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const methodLabel = (capName: string) => {
    const allowed = configs[capName]?.allowed_methods;
    if (!allowed || allowed.length === 0) return null;
    return allowed.join(", ");
  };

  return (
    <div ref={wrapperRef}>
      <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Capabilities</label>
      {items.length > 0 && (
        <div className="space-y-1 mb-1">
          {items.map((item, idx) => {
            const isExpanded = expandedCap === item;
            const methods = methodsCache[item];
            const allowed = configs[item]?.allowed_methods;
            const ml = methodLabel(item);
            return (
              <div key={item}>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => toggleCapExpand(item)}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono border-0 cursor-pointer"
                    style={{
                      background: isExpanded ? "var(--bg-hover)" : "var(--bg-surface)",
                      border: "1px solid var(--border)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    <span style={{ fontSize: "8px", opacity: 0.5 }}>{isExpanded ? "▾" : "▸"}</span>
                    {item}
                    {ml && <span style={{ color: "var(--accent)", fontSize: "10px" }}>({ml})</span>}
                  </button>
                  <button
                    onClick={() => removeItem(idx)}
                    className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--error)] text-[10px] leading-none p-0"
                  >
                    x
                  </button>
                </div>
                {isExpanded && (
                  <div
                    className="ml-4 mt-1 rounded p-2 space-y-1"
                    style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                  >
                    {loadingMethods === item && (
                      <div className="text-[10px] text-[var(--text-muted)]">Loading methods...</div>
                    )}
                    {methods && methods.length === 0 && (
                      <div className="text-[10px] text-[var(--text-muted)]">No methods found</div>
                    )}
                    {methods && methods.map((m) => {
                      const isAllowed = !allowed || allowed.length === 0 || allowed.includes(m.name);
                      const params = m.params.map((p) => {
                        const t = p.type ? `: ${p.type.replace(/[<>]/g, "")}` : "";
                        const d = p.default ? ` = ${p.default}` : "";
                        return `${p.name}${t}${d}`;
                      }).join(", ");
                      const ret = m.return_type ? m.return_type.replace(/[<>]/g, "") : "";
                      return (
                        <button
                          key={m.name}
                          onClick={() => toggleMethod(item, m.name)}
                          className="flex items-center gap-2 w-full text-left border-0 cursor-pointer rounded px-1.5 py-0.5"
                          style={{
                            background: "transparent",
                            color: isAllowed ? "var(--text-primary)" : "var(--text-muted)",
                            opacity: isAllowed ? 1 : 0.5,
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                        >
                          <span style={{
                            width: "14px",
                            textAlign: "center",
                            fontSize: "10px",
                            color: isAllowed ? "var(--success)" : "var(--text-muted)",
                          }}>
                            {isAllowed ? "●" : "○"}
                          </span>
                          <span className="font-mono text-[11px]">
                            {m.name}({params})
                            {ret && <span style={{ color: "var(--text-muted)" }}> → {ret}</span>}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <div className="relative">
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setShowSuggestions(true); }}
          onFocus={() => setShowSuggestions(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (filtered.length > 0) addItem(filtered[0]);
              else if (query.trim()) addItem(query);
            }
            if (e.key === "Escape") setShowSuggestions(false);
          }}
          placeholder="Add capabilities..."
          className={INPUT_CLS}
          style={{ fontSize: "11px" }}
        />
        {showSuggestions && filtered.length > 0 && (
          <div
            className="absolute z-50 left-0 right-0 mt-1 rounded overflow-hidden shadow-lg"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", maxHeight: "160px", overflowY: "auto" }}
          >
            {filtered.map((s) => (
              <button
                key={s}
                onClick={() => addItem(s)}
                className="w-full text-left px-2 py-1 text-[11px] font-mono border-0 cursor-pointer"
                style={{ background: "transparent", color: "var(--text-secondary)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Last Run Display ── */

function LastRunInfo({ run, cogentName }: { run: CogosProcessRun; cogentName?: string }) {
  const [showResult, setShowResult] = useState(false);
  return (
    <div
      className="rounded p-3 space-y-2"
      style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Last Run</span>
        <div className="flex items-center gap-2">
          <Badge variant={run.status === "completed" ? "success" : run.status === "failed" ? "error" : "warning"}>
            {run.status}
          </Badge>
          {cogentName && (
            <a
              href={buildCloudWatchUrl(cogentName, run.id, run.created_at)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--accent)] text-[10px] hover:underline"
              title="View CloudWatch logs"
            >
              CW Logs
            </a>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
        <span className="text-[var(--text-muted)]">
          duration: <span className="text-[var(--text-secondary)]">{fmtDuration(run.duration_ms)}</span>
        </span>
        <span className="text-[var(--text-muted)]">
          tokens: <span className="text-[var(--text-secondary)]">{fmtTokens(run.tokens_in)} in / {fmtTokens(run.tokens_out)} out</span>
        </span>
        <span className="text-[var(--text-muted)]">
          cost: <span className="text-[var(--text-secondary)]">${run.cost_usd.toFixed(4)}</span>
        </span>
        {run.created_at && (
          <span className="text-[var(--text-muted)]">
            at: <span className="text-[var(--text-secondary)]">{fmtTimestamp(run.created_at)}</span>
          </span>
        )}
      </div>
      {run.error && (
        <div className="text-[11px] text-[var(--error)] font-mono whitespace-pre-wrap break-all p-2 rounded" style={{ background: "rgba(239,68,68,0.08)" }}>
          {run.error}
        </div>
      )}
      {run.result && (
        <div>
          <button
            onClick={() => setShowResult(!showResult)}
            className="text-[11px] text-[var(--accent)] bg-transparent border-0 cursor-pointer hover:underline p-0"
          >
            {showResult ? "Hide result" : "Show result"}
          </button>
          {showResult && (
            <div className="mt-1">
              <JsonViewer data={run.result} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Icon Button Group ── */

function IconButtonGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; icon: string; title: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div>
      <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">{label}</label>
      <div className="flex gap-1">
        {options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className="px-2 py-1 text-[12px] rounded border cursor-pointer transition-colors"
            style={{
              background: value === opt.value ? "var(--accent)" : "var(--bg-elevated)",
              color: value === opt.value ? "white" : "var(--text-secondary)",
              borderColor: value === opt.value ? "var(--accent)" : "var(--border)",
            }}
            title={opt.title}
            type="button"
          >
            {opt.icon}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Status Menu Button ── */

function StatusMenu({ value, onChange }: { value: string; onChange: (s: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Status</label>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="px-2 py-1 text-[12px] rounded border cursor-pointer transition-colors flex items-center gap-1"
        style={{
          background: "var(--bg-elevated)",
          color: "var(--text-primary)",
          borderColor: "var(--border)",
        }}
      >
        <Badge variant={STATUS_VARIANT[value] || "neutral"}>{value}</Badge>
        <span className="text-[10px] text-[var(--text-muted)]">▾</span>
      </button>
      {open && (
        <div
          className="absolute z-50 left-0 mt-1 rounded overflow-hidden shadow-lg py-1"
          style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", minWidth: "120px" }}
        >
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => { onChange(s); setOpen(false); }}
              className="w-full text-left px-3 py-1 text-[11px] border-0 cursor-pointer flex items-center gap-2"
              style={{
                background: s === value ? "var(--bg-hover)" : "transparent",
                color: "var(--text-secondary)",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = s === value ? "var(--bg-hover)" : "transparent"; }}
            >
              <Badge variant={STATUS_VARIANT[s] || "neutral"}>{s}</Badge>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Model Menu Button ── */

const MODELS = [
  { value: "us.anthropic.claude-haiku-4-5-20251001-v1:0", label: "haiku" },
  { value: "us.anthropic.claude-sonnet-4-20250514-v1:0", label: "sonnet" },
  { value: "us.anthropic.claude-opus-4-20250514-v1:0", label: "opus" },
];

function modelLabel(value: string): string {
  const m = MODELS.find((m) => m.value === value);
  if (m) return m.label;
  if (value.includes("haiku")) return "haiku";
  if (value.includes("opus")) return "opus";
  if (value.includes("sonnet")) return "sonnet";
  return value || "opus";
}

function ModelMenu({ value, onChange }: { value: string; onChange: (m: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const currentLabel = modelLabel(value);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Model</label>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="px-2 py-1 text-[12px] rounded border cursor-pointer transition-colors flex items-center gap-1"
        style={{
          background: "var(--bg-elevated)",
          color: "var(--text-primary)",
          borderColor: "var(--border)",
        }}
      >
        {currentLabel}
        <span className="text-[10px] text-[var(--text-muted)]">▾</span>
      </button>
      {open && (
        <div
          className="absolute z-50 left-0 mt-1 rounded overflow-hidden shadow-lg py-1"
          style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", minWidth: "100px" }}
        >
          {MODELS.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => { onChange(m.value); setOpen(false); }}
              className="w-full text-left px-3 py-1 text-[11px] border-0 cursor-pointer"
              style={{
                background: m.value === value ? "var(--bg-hover)" : "transparent",
                color: "var(--text-secondary)",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = m.value === value ? "var(--bg-hover)" : "transparent"; }}
            >
              {m.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Duration Unit Menu ── */

const DURATION_UNIT_OPTIONS: DurationUnit[] = ["ms", "s", "m", "h", "d"];

function DurationUnitMenu({ value, onChange }: { value: DurationUnit; onChange: (u: DurationUnit) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="px-2 py-1 text-[12px] rounded border cursor-pointer transition-colors flex items-center gap-0.5"
        style={{
          background: "var(--bg-elevated)",
          color: "var(--text-primary)",
          borderColor: "var(--border)",
        }}
      >
        {value}
        <span className="text-[10px] text-[var(--text-muted)]">▾</span>
      </button>
      {open && (
        <div
          className="absolute z-50 left-0 mt-1 rounded overflow-hidden shadow-lg py-1"
          style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", minWidth: "40px" }}
        >
          {DURATION_UNIT_OPTIONS.map((u) => (
            <button
              key={u}
              type="button"
              onClick={() => { onChange(u); setOpen(false); }}
              className="w-full text-left px-3 py-1 text-[11px] border-0 cursor-pointer"
              style={{
                background: u === value ? "var(--bg-hover)" : "transparent",
                color: "var(--text-secondary)",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = u === value ? "var(--bg-hover)" : "transparent"; }}
            >
              {u}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Process Form ── */

function ProcessFormEditor({
  form,
  onChange,
  onSave,
  onCancel,
  saving,
  isNew,
  resourceSuggestions,
  fileSuggestions,
  capabilitySuggestions,
  cogentName,
}: {
  form: ProcessForm;
  onChange: (form: ProcessForm) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  isNew: boolean;
  resourceSuggestions: string[];
  fileSuggestions: string[];
  capabilitySuggestions: string[];
  cogentName: string;
}) {
  return (
    <div className="space-y-3 p-4 rounded-md" style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[12px] font-semibold text-[var(--text-primary)]">
          {isNew ? "New Process" : "Edit Process"}
        </span>
      </div>

      {/* Name + Priority */}
      <div className="flex gap-3 items-end">
        <div className="flex-1">
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Name</label>
          <input className={INPUT_CLS} value={form.name} onChange={(e) => onChange({ ...form, name: e.target.value })} />
        </div>
        <div style={{ width: "70px" }}>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Priority</label>
          <input
            className={INPUT_CLS}
            value={form.priority}
            onChange={(e) => onChange({ ...form, priority: e.target.value })}
            style={{ MozAppearance: "textfield", WebkitAppearance: "none", appearance: "textfield" } as React.CSSProperties}
          />
        </div>
      </div>

      {/* Toggles row: mode, runner, status, preemptible, clear context */}
      <div className="flex gap-4 items-end flex-wrap">
        <IconButtonGroup
          label="Mode"
          value={form.mode}
          onChange={(mode) => onChange({ ...form, mode })}
          options={[
            { value: "one_shot" as const, icon: "→", title: "One-shot" },
            { value: "daemon" as const, icon: "⟳", title: "Daemon" },
          ]}
        />
        <IconButtonGroup
          label="Runner"
          value={form.runner}
          onChange={(runner) => onChange({ ...form, runner })}
          options={[
            { value: "lambda", icon: "λ", title: "Lambda" },
            { value: "ecs", icon: "🖥", title: "ECS" },
          ]}
        />
        <StatusMenu value={form.status} onChange={(status) => onChange({ ...form, status })} />
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Preempt</label>
          <button
            type="button"
            onClick={() => onChange({ ...form, preemptible: !form.preemptible })}
            className="px-2 py-1 text-[12px] rounded border cursor-pointer transition-colors"
            style={{
              background: form.preemptible ? "var(--accent)" : "var(--bg-elevated)",
              color: form.preemptible ? "white" : "var(--text-muted)",
              borderColor: form.preemptible ? "var(--accent)" : "var(--border)",
            }}
            title="Preemptible"
          >
            {form.preemptible ? "on" : "off"}
          </button>
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Clear Ctx</label>
          <button
            type="button"
            onClick={() => onChange({ ...form, clear_context: !form.clear_context })}
            className="px-2 py-1 text-[12px] rounded border cursor-pointer transition-colors"
            style={{
              background: form.clear_context ? "var(--accent)" : "var(--bg-elevated)",
              color: form.clear_context ? "white" : "var(--text-muted)",
              borderColor: form.clear_context ? "var(--accent)" : "var(--border)",
            }}
            title="Clear Context"
          >
            {form.clear_context ? "on" : "off"}
          </button>
        </div>
        <ModelMenu value={form.model} onChange={(model) => onChange({ ...form, model })} />
        <div>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Duration</label>
          <div className="flex gap-1">
            <input
              className={INPUT_CLS}
              value={form.max_duration_val}
              onChange={(e) => onChange({ ...form, max_duration_val: e.target.value })}
              placeholder="--"
              style={{ width: "45px", MozAppearance: "textfield", WebkitAppearance: "none", appearance: "textfield" } as React.CSSProperties}
            />
            <DurationUnitMenu value={form.max_duration_unit} onChange={(max_duration_unit) => onChange({ ...form, max_duration_unit })} />
          </div>
        </div>
        <div style={{ width: "40px" }}>
          <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Retries</label>
          <input
            className={INPUT_CLS}
            value={form.max_retries}
            onChange={(e) => onChange({ ...form, max_retries: e.target.value })}
            style={{ MozAppearance: "textfield", WebkitAppearance: "none", appearance: "textfield" } as React.CSSProperties}
          />
        </div>
      </div>

      {/* Content */}
      <div>
        <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Content (prompt)</label>
        <textarea
          className={INPUT_CLS}
          rows={4}
          value={form.content}
          onChange={(e) => onChange({ ...form, content: e.target.value })}
          style={{ resize: "vertical" }}
        />
      </div>

      {/* Memory (file) with typeahead + scratch default */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <label className="text-[10px] text-[var(--text-muted)] uppercase">Memory (prompt file)</label>
          {form.name.trim() && (
            <button
              type="button"
              onClick={() => {
                const scratch = `/scratch/process/${form.name.trim()}/index.md`;
                if (!form.files.includes(scratch)) onChange({ ...form, files: [...form.files, scratch] });
              }}
              className="text-[10px] px-1.5 py-0 rounded bg-transparent border border-[var(--border)] text-[var(--accent)] cursor-pointer hover:border-[var(--accent)]"
            >
              + scratch
            </button>
          )}
        </div>
        <TagListEditor
          label=""
          items={form.files}
          onChange={(files) => onChange({ ...form, files })}
          suggestions={fileSuggestions}
        />
      </div>

      {/* Resources with typeahead */}
      <TagListEditor
        label="Resources"
        items={form.resources}
        onChange={(resources) => onChange({ ...form, resources })}
        suggestions={resourceSuggestions}
      />

      {/* Capabilities with clickable methods + templates */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          {[
            { label: "+ all", caps: capabilitySuggestions },
            { label: "+ io", caps: ["files", "events", "secrets"] },
            { label: "+ scratch", caps: ["files"] },
          ].map((tpl) => (
            <button
              key={tpl.label}
              onClick={() => {
                const available = tpl.caps.filter((c) => capabilitySuggestions.includes(c));
                const merged = [...new Set([...form.capabilities, ...available])];
                onChange({ ...form, capabilities: merged });
              }}
              className="text-[10px] px-1.5 py-0 rounded bg-transparent border border-[var(--border)] text-[var(--accent)] cursor-pointer hover:border-[var(--accent)]"
            >
              {tpl.label}
            </button>
          ))}
        </div>
        <CapabilityEditor
          items={form.capabilities}
          configs={form.capabilityConfigs}
          onChange={(capabilities) => onChange({ ...form, capabilities })}
          onConfigChange={(capabilityConfigs) => onChange({ ...form, capabilityConfigs })}
          suggestions={capabilitySuggestions}
          cogentName={cogentName}
        />
      </div>

      {/* Save / Cancel */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={onSave}
          disabled={saving || !form.name.trim()}
          className="px-3 py-1 text-[12px] rounded border-0 cursor-pointer transition-colors"
          style={{
            background: "var(--accent)",
            color: "white",
            opacity: saving || !form.name.trim() ? 0.5 : 1,
          }}
        >
          {saving ? "Saving..." : isNew ? "Create" : "Save"}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1 text-[12px] rounded bg-transparent border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/* ── Main Panel ── */

export function ProcessesPanel({ processes, cogentName, onRefresh, resources, runs, files, capabilities }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null); // "new" for create
  const [form, setForm] = useState<ProcessForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [detailRuns, setDetailRuns] = useState<CogosProcessRun[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [resolvedPrompt, setResolvedPrompt] = useState<string>("");
  const [showResolved, setShowResolved] = useState(false);
  const [detailFileKeys, setDetailFileKeys] = useState<string[]>([]);
  const [detailCapabilities, setDetailCapabilities] = useState<string[]>([]);
  const [detailCapConfigs, setDetailCapConfigs] = useState<Record<string, CapabilityConfig>>({});
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const resourceSuggestions = useMemo(() => resources.map((r) => r.name), [resources]);
  const fileSuggestions = useMemo(() => files.map((f) => f.key), [files]);
  const capabilitySuggestions = useMemo(() => capabilities.map((c) => c.name), [capabilities]);

  // Build map of process_id -> latest run from the runs list
  const lastRunByProcess = useMemo(() => {
    const map: Record<string, CogosRun> = {};
    for (const r of runs) {
      const pid = r.process;
      if (!map[pid] || (r.created_at && (!map[pid].created_at || r.created_at > map[pid].created_at))) {
        map[pid] = r;
      }
    }
    return map;
  }, [runs]);

  const handleSelect = useCallback(async (id: string) => {
    if (selectedId === id) {
      setSelectedId(null);
      setDetailRuns([]);
      setResolvedPrompt("");
      setShowResolved(false);
      return;
    }
    setSelectedId(id);
    setLoadingDetail(true);
    setShowResolved(false);
    try {
      const detail = await api.getProcessDetail(cogentName, id);
      setDetailRuns(detail.runs);
      setResolvedPrompt(detail.resolved_prompt || "");
      setDetailFileKeys(detail.file_keys || []);
      setDetailCapabilities(detail.capabilities || []);
      setDetailCapConfigs((detail.capability_configs as Record<string, CapabilityConfig>) || {});
    } catch {
      setDetailRuns([]);
      setResolvedPrompt("");
      setDetailFileKeys([]);
      setDetailCapabilities([]);
      setDetailCapConfigs({});
    }
    setLoadingDetail(false);
  }, [selectedId, cogentName]);

  const handleNew = useCallback(() => {
    setEditingId("new");
    setForm(EMPTY_FORM);
    setSelectedId(null);
  }, []);

  const handleEdit = useCallback((p: CogosProcess) => {
    setEditingId(p.id);
    setForm(formFromProcess(p, detailFileKeys, detailCapabilities, detailCapConfigs));
  }, [detailFileKeys, detailCapabilities, detailCapConfigs]);

  const handleCancel = useCallback(() => {
    setEditingId(null);
    setForm(EMPTY_FORM);
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        mode: form.mode,
        content: form.content,
        files: form.files.filter((f) => f.trim()),
        priority: parseFloat(form.priority) || 0,
        runner: form.runner,
        status: form.status,
        model: form.model.trim() || null,
        max_duration_ms: formDurationToMs(form.max_duration_val, form.max_duration_unit),
        max_retries: parseInt(form.max_retries) || 0,
        preemptible: form.preemptible,
        clear_context: form.clear_context,
        resources: form.resources,
        capabilities: form.capabilities,
        capability_configs: form.capabilityConfigs,
      };
      if (editingId === "new") {
        await api.createProcess(cogentName, body as Parameters<typeof api.createProcess>[1]);
      } else {
        await api.updateProcess(cogentName, editingId!, body as Parameters<typeof api.updateProcess>[2]);
      }
      setEditingId(null);
      setForm(EMPTY_FORM);
      onRefresh();
    } catch (err) {
      console.error("Failed to save process:", err);
    }
    setSaving(false);
  }, [form, editingId, cogentName, onRefresh]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await api.deleteProcess(cogentName, id);
      setConfirmDeleteId(null);
      setSelectedId(null);
      setEditingId(null);
      onRefresh();
    } catch (err) {
      console.error("Failed to delete process:", err);
    }
  }, [cogentName, onRefresh]);

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          Processes
          <span className="ml-2 text-[var(--text-muted)] font-normal">({processes.length})</span>
        </h2>
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">
            {Object.entries(
              processes.reduce<Record<string, number>>((acc, p) => {
                acc[p.status] = (acc[p.status] || 0) + 1;
                return acc;
              }, {}),
            ).map(([status, count]) => (
              <Badge key={status} variant={STATUS_VARIANT[status] || "neutral"}>
                {count} {status}
              </Badge>
            ))}
          </div>
          <button
            onClick={handleNew}
            className="px-3 py-1 text-[12px] rounded border-0 cursor-pointer transition-colors"
            style={{ background: "var(--accent)", color: "white" }}
          >
            + New
          </button>
        </div>
      </div>

      {/* New process form */}
      {editingId === "new" && (
        <div className="mb-4">
          <ProcessFormEditor
            form={form}
            onChange={setForm}
            onSave={handleSave}
            onCancel={handleCancel}
            saving={saving}
            isNew
            resourceSuggestions={resourceSuggestions}
            fileSuggestions={fileSuggestions}
            capabilitySuggestions={capabilitySuggestions}
            cogentName={cogentName}
          />
        </div>
      )}

      {/* Process list */}
      {processes.length === 0 && editingId !== "new" && (
        <div className="text-[var(--text-muted)] text-xs py-8 text-center">No processes</div>
      )}

      {(() => {
        const STATUS_ORDER = ["running", "runnable", "waiting", "blocked", "suspended", "completed", "disabled"];
        const grouped = STATUS_ORDER
          .map((status) => ({ status, procs: processes.filter((p) => p.status === status) }))
          .filter((g) => g.procs.length > 0);
        // Include any statuses not in the predefined order
        const knownStatuses = new Set(STATUS_ORDER);
        const extra = processes.filter((p) => !knownStatuses.has(p.status));
        if (extra.length > 0) grouped.push({ status: "other", procs: extra });

        return grouped.map((group) => (
      <div key={group.status} className="mb-4 rounded-md overflow-hidden" style={{ border: "1px solid var(--border)" }}>
        <div
          className="flex items-center px-3 py-1.5 text-[10px] uppercase tracking-wide font-medium text-[var(--text-muted)] cursor-pointer select-none"
          style={{
            background: "var(--bg-deep)",
            borderBottom: collapsedGroups.has(group.status) ? "none" : "1px solid var(--border)",
          }}
          onClick={() => setCollapsedGroups((prev) => {
            const next = new Set(prev);
            if (next.has(group.status)) next.delete(group.status);
            else next.add(group.status);
            return next;
          })}
        >
          <span className="mr-2 text-[10px]" style={{ width: "12px", display: "inline-block" }}>
            {collapsedGroups.has(group.status) ? "▸" : "▾"}
          </span>
          <Badge variant={STATUS_VARIANT[group.status] || "neutral"}>{group.status}</Badge>
          <span className="ml-2 text-[var(--text-muted)]">({group.procs.length})</span>
        </div>
        {!collapsedGroups.has(group.status) && group.procs.map((proc) => {
          const isSelected = selectedId === proc.id;
          const isEditing = editingId === proc.id;
          const lastRun = lastRunByProcess[proc.id];

          return (
            <div key={proc.id}>
              {/* Row */}
              <div
                className="grid items-center px-3 py-2 cursor-pointer transition-colors"
                style={{
                  gridTemplateColumns: "1fr 1fr 90px",
                  background: isSelected ? "var(--bg-hover)" : "var(--bg-surface)",
                  borderBottom: "1px solid var(--border)",
                }}
                onClick={() => handleSelect(proc.id)}
                onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = "var(--bg-surface)"; }}
              >
                <span className="inline-flex items-center gap-1.5 text-[var(--text-primary)] font-medium text-[12px] truncate">
                  <span className="text-[var(--text-muted)]" title={proc.mode}>
                    {proc.mode === "daemon" ? "⟳" : "→"}
                  </span>
                  {proc.name}
                </span>
                <span className="text-[11px] text-red-400 truncate" title={lastRun?.error || ""}>
                  {lastRun?.error ? (lastRun.error.length > 40 ? lastRun.error.slice(0, 40) + "…" : lastRun.error) : ""}
                </span>
                <span className="flex items-center justify-end gap-1">
                  <span className="inline-flex items-center justify-center w-[22px] h-[18px]">
                    {lastRun ? (
                      <Badge variant={lastRun.status === "completed" ? "success" : lastRun.status === "failed" || lastRun.status === "error" ? "error" : lastRun.status === "running" ? "accent" : "warning"}>
                        {lastRun.status === "completed" ? "✓" : lastRun.status === "failed" || lastRun.status === "error" ? "✗" : lastRun.status === "running" ? "…" : "?"}
                      </Badge>
                    ) : (
                      <span className="text-[var(--text-muted)] text-[10px]">·</span>
                    )}
                  </span>
                  <span className="inline-flex items-center justify-center w-[22px] h-[18px]">
                    {lastRun ? (
                      <a
                        href={buildCloudWatchUrl(cogentName, lastRun.id, lastRun.created_at)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[10px] font-mono px-1 py-0 rounded hover:underline"
                        style={{ background: "rgba(234,179,8,0.12)", color: "#facc15" }}
                        title="Session logs (CloudWatch)"
                        onClick={(e) => e.stopPropagation()}
                      >
                        SL
                      </a>
                    ) : (
                      <span className="text-[var(--text-muted)] text-[10px]">·</span>
                    )}
                  </span>
                  <span
                    className="inline-flex items-center justify-center w-[22px] h-[18px] text-[10px] font-mono rounded"
                    style={{ background: proc.runner === "ecs" ? "rgba(139,92,246,0.15)" : "rgba(59,130,246,0.15)", color: proc.runner === "ecs" ? "#a78bfa" : "#60a5fa" }}
                    title={proc.runner}
                  >
                    {proc.runner === "ecs" ? "🖥" : "λ"}
                  </span>
                </span>
              </div>

              {/* Expanded detail */}
              {isSelected && !isEditing && (
                <div
                  className="px-4 py-3 space-y-3"
                  style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}
                >
                  {/* Metadata row */}
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
                    <button
                      className="text-[var(--text-muted)] text-[11px] bg-transparent border-0 cursor-pointer hover:text-[var(--accent)] p-0 inline-flex items-center gap-1"
                      title={proc.id}
                      onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(proc.id); }}
                    >
                      id 📋
                    </button>
                    <span className="text-[var(--text-muted)]">retries: <span className="text-[var(--text-secondary)]">{proc.retry_count}/{proc.max_retries}</span></span>
                    {proc.max_duration_ms != null && (
                      <span className="text-[var(--text-muted)]">max duration: <span className="text-[var(--text-secondary)]">{fmtDuration(proc.max_duration_ms)}</span></span>
                    )}
                    <span className="text-[var(--text-muted)]">clear ctx: <span className="text-[var(--text-secondary)]">{proc.clear_context ? "yes" : "no"}</span></span>
                  </div>

                  {/* Content with resolved prompt toggle */}
                  {(proc.content || resolvedPrompt) && (
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] text-[var(--text-muted)] uppercase">
                          {showResolved ? "Full Prompt" : "Content"}
                        </span>
                        {resolvedPrompt && resolvedPrompt !== proc.content && (
                          <button
                            onClick={() => setShowResolved((v) => !v)}
                            className="text-[10px] px-1.5 py-0 rounded bg-transparent border border-[var(--border)] text-[var(--accent)] cursor-pointer hover:border-[var(--accent)]"
                          >
                            {showResolved ? "Show Raw" : "Show Full Prompt"}
                          </button>
                        )}
                      </div>
                      <div className="text-[11px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap p-2 rounded" style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", maxHeight: "200px", overflowY: "auto" }}>
                        {showResolved ? resolvedPrompt : (proc.content || "(empty)")}
                      </div>
                    </div>
                  )}

                  {/* Resources */}
                  {proc.resources && proc.resources.length > 0 && (
                    <div>
                      <div className="text-[10px] text-[var(--text-muted)] uppercase mb-1">Resources</div>
                      <div className="flex flex-wrap gap-1">
                        {proc.resources.map((r) => (
                          <span key={r} className="px-1.5 py-0.5 rounded text-[11px] font-mono" style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
                            {r}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Recent runs */}
                  {loadingDetail ? (
                    <div className="text-[11px] text-[var(--text-muted)]">Loading runs...</div>
                  ) : detailRuns.length > 0 ? (
                    <div>
                      <div className="text-[10px] text-[var(--text-muted)] uppercase mb-1">Recent Runs ({detailRuns.length})</div>
                      <table className="w-full text-[11px]" style={{ borderCollapse: "collapse" }}>
                        <thead>
                          <tr className="text-[9px] uppercase tracking-wide text-[var(--text-muted)]" style={{ background: "var(--bg-surface)" }}>
                            <th className="text-left px-2 py-1 font-medium" style={{ borderBottom: "1px solid var(--border)" }}></th>
                            <th className="text-left px-2 py-1 font-medium" style={{ borderBottom: "1px solid var(--border)" }}>Duration</th>
                            <th className="text-left px-2 py-1 font-medium" style={{ borderBottom: "1px solid var(--border)" }}>Tokens</th>
                            <th className="text-left px-2 py-1 font-medium" style={{ borderBottom: "1px solid var(--border)" }}>Cost</th>
                            <th className="text-left px-2 py-1 font-medium" style={{ borderBottom: "1px solid var(--border)" }}>Created</th>
                            <th className="text-left px-2 py-1 font-medium" style={{ borderBottom: "1px solid var(--border)" }}>Error</th>
                            <th className="text-right px-2 py-1 font-medium" style={{ borderBottom: "1px solid var(--border)" }}>Logs</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detailRuns.slice(0, 10).map((run) => (
                            <tr key={run.id} style={{ borderBottom: "1px solid var(--border)" }}>
                              <td className="px-2 py-1">
                                <Badge variant={run.status === "completed" ? "success" : run.status === "failed" || run.status === "error" ? "error" : run.status === "running" ? "accent" : "warning"}>
                                  {run.status === "completed" ? "✓" : run.status === "failed" || run.status === "error" ? "✗" : run.status === "running" ? "…" : "?"}
                                </Badge>
                              </td>
                              <td className="px-2 py-1 text-[var(--text-secondary)] whitespace-nowrap">{fmtDuration(run.duration_ms)}</td>
                              <td className="px-2 py-1 text-[var(--text-muted)] whitespace-nowrap">{fmtTokens(run.tokens_in)}/{fmtTokens(run.tokens_out)}</td>
                              <td className="px-2 py-1 text-[var(--text-secondary)] whitespace-nowrap">${run.cost_usd.toFixed(3)}</td>
                              <td className="px-2 py-1 text-[var(--text-muted)] text-[10px] whitespace-nowrap">{run.created_at ? fmtTimestamp(run.created_at) : "--"}</td>
                              <td className="px-2 py-1 text-red-400 text-[10px] truncate max-w-[200px]" title={run.error || ""}>{run.error ? (run.error.length > 30 ? run.error.slice(0, 30) + "…" : run.error) : ""}</td>
                              <td className="px-2 py-1 text-right">
                                <a
                                  href={buildCloudWatchUrl(cogentName, run.id, run.created_at)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-[var(--accent)] text-[10px] hover:underline"
                                  title="CloudWatch logs"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  CW
                                </a>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {/* Actions */}
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleEdit(proc); }}
                      className="px-3 py-1 text-[12px] rounded bg-transparent border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-active)] cursor-pointer transition-colors"
                    >
                      Edit
                    </button>
                    {confirmDeleteId === proc.id ? (
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-[var(--error)]">Delete?</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDelete(proc.id); }}
                          className="px-2 py-0.5 text-[11px] rounded border-0 cursor-pointer"
                          style={{ background: "var(--error)", color: "white" }}
                        >
                          Yes
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(null); }}
                          className="px-2 py-0.5 text-[11px] rounded bg-transparent border border-[var(--border)] text-[var(--text-secondary)] cursor-pointer"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(proc.id); }}
                        className="px-3 py-1 text-[12px] rounded bg-transparent border border-[var(--border)] text-[var(--error)] hover:border-[var(--error)] cursor-pointer transition-colors"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Inline edit form */}
              {isEditing && (
                <div className="px-4 py-3" style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}>
                  <ProcessFormEditor
                    form={form}
                    onChange={setForm}
                    onSave={handleSave}
                    onCancel={handleCancel}
                    saving={saving}
                    isNew={false}
                    resourceSuggestions={resourceSuggestions}
                    fileSuggestions={fileSuggestions}
                    capabilitySuggestions={capabilitySuggestions}
                    cogentName={cogentName}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
        ));
      })()}
    </div>
  );
}
