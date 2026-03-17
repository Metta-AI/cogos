"use client";

import React, { useState, useCallback, useMemo, useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { CogosProcess, CogosProcessRun, Resource, CogosRun, CogosFile, CogosCapability, EventType } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { FileReferenceTextarea } from "@/components/shared/FileReferenceTextarea";
import { InfoTooltip } from "@/components/shared/InfoTooltip";
import { JsonViewer } from "@/components/shared/JsonViewer";
import type { CogosFileVersion } from "@/lib/types";
import type { CogosRunLogsResponse } from "@/lib/types";
import * as api from "@/lib/api";
import { fmtTimestamp } from "@/lib/format";
import { buildCogentRunLogsUrl } from "@/lib/cloudwatch";

interface Props {
  processes: CogosProcess[];
  cogentName: string;
  onRefresh: () => void;
  resources: Resource[];
  runs: CogosRun[];
  files: CogosFile[];
  capabilities: CogosCapability[];
  eventTypes: EventType[];
  currentEpoch?: number;
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
const EXECUTOR_DEFAULT_MODEL_LABEL = "default (sonnet)";

const INPUT_CLS = "bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] w-full";

interface CapGrant {
  grant_name: string;
  capability_name: string;
  config: Record<string, unknown> | null;
}

interface ProcessForm {
  name: string;
  mode: "daemon" | "one_shot";
  content: string;
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
  grants: CapGrant[];
  handlers: string[];
  output_events: string[];
  metadata: Record<string, unknown>;
  session_resume: boolean;
}

const EMPTY_FORM: ProcessForm = {
  name: "",
  mode: "one_shot",
  content: "",
  priority: "0",
  runner: "lambda",
  status: "runnable",
  model: "",
  max_duration_val: "",
  max_duration_unit: "m",
  max_retries: "0",
  preemptible: false,
  clear_context: false,
  resources: [],
  grants: [],
  handlers: [],
  output_events: [],
  metadata: {},
  session_resume: false,
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

function formFromProcess(
  p: CogosProcess,
  grants?: CapGrant[],
  handlerPatterns?: string[],
): ProcessForm {
  const sessionConfig = readSessionConfig(p.metadata);
  return {
    name: p.name,
    mode: p.mode,
    content: p.content,
    priority: String(p.priority),
    runner: p.runner,
    status: p.status,
    model: p.model ?? "",
    ...msToFormDuration(p.max_duration_ms),
    max_retries: String(p.max_retries),
    preemptible: p.preemptible,
    clear_context: p.clear_context,
    resources: p.resources ?? [],
    grants: grants ?? [],
    handlers: handlerPatterns ?? [],
    output_events: p.output_events ?? [],
    metadata: cloneJsonRecord(p.metadata),
    session_resume: sessionConfig.resume,
  };
}

function cloneJsonRecord(value: Record<string, unknown> | null | undefined): Record<string, unknown> {
  if (!value) return {};
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>;
}

function readSessionConfig(metadata: Record<string, unknown> | null | undefined): {
  resume: boolean;
  scope: "process" | "keyed";
  keyField: string;
  explicit: boolean;
} {
  const session = metadata?.session;
  if (!session || typeof session !== "object" || Array.isArray(session)) {
    return { resume: false, scope: "process", keyField: "session_key", explicit: false };
  }

  const sessionRecord = session as Record<string, unknown>;
  const rawKeyField = typeof sessionRecord.key_field === "string" && sessionRecord.key_field.trim()
    ? sessionRecord.key_field.trim()
    : "session_key";

  if ("resume" in sessionRecord || "scope" in sessionRecord) {
    return {
      resume: sessionRecord.resume === true,
      scope: sessionRecord.scope === "keyed" ? "keyed" : "process",
      keyField: rawKeyField,
      explicit: true,
    };
  }

  if (sessionRecord.mode === "process") {
    return { resume: true, scope: "process", keyField: rawKeyField, explicit: true };
  }
  if (sessionRecord.mode === "keyed") {
    return { resume: true, scope: "keyed", keyField: rawKeyField, explicit: true };
  }
  if (sessionRecord.mode === "off") {
    return { resume: false, scope: "process", keyField: rawKeyField, explicit: true };
  }

  return { resume: false, scope: "process", keyField: rawKeyField, explicit: true };
}

function buildMetadataWithSessionResume(
  metadata: Record<string, unknown>,
  sessionResume: boolean,
): Record<string, unknown> {
  const next = cloneJsonRecord(metadata);
  const sessionConfig = readSessionConfig(next);
  const existingSession = next.session;
  const sessionRecord = existingSession && typeof existingSession === "object" && !Array.isArray(existingSession)
    ? cloneJsonRecord(existingSession as Record<string, unknown>)
    : {};

  if (!sessionResume && !sessionConfig.explicit) {
    delete next.session;
    return next;
  }

  sessionRecord.resume = sessionResume;
  sessionRecord.scope = sessionConfig.scope;
  if (sessionConfig.keyField && sessionConfig.keyField !== "session_key") {
    sessionRecord.key_field = sessionConfig.keyField;
  } else {
    delete sessionRecord.key_field;
  }
  delete sessionRecord.mode;
  next.session = sessionRecord;
  return next;
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

function SectionHelp({ title, bullets }: { title: string; bullets: string[] }) {
  return (
    <InfoTooltip title={title}>
      <ul className="m-0 pl-4 space-y-1">
        {bullets.map((bullet) => (
          <li key={bullet}>{bullet}</li>
        ))}
      </ul>
    </InfoTooltip>
  );
}

function grantAllowsRead(config: Record<string, unknown> | null): boolean {
  const ops = config?.ops;
  return !Array.isArray(ops) || ops.includes("read");
}

function getPromptReferenceSuggestions(fileKeys: string[], grants: CapGrant[]): string[] {
  const sortedKeys = [...fileKeys].sort((a, b) => a.localeCompare(b));
  const suggestions: string[] = [];
  const seen = new Set<string>();

  const add = (key: string) => {
    if (!seen.has(key)) {
      seen.add(key);
      suggestions.push(key);
    }
  };

  for (const grant of grants) {
    if (!grantAllowsRead(grant.config)) continue;

    const config = (grant.config || {}) as Record<string, unknown>;
    if (grant.capability_name === "file") {
      const key = typeof config.key === "string" ? config.key : "";
      if (!key) return sortedKeys;
      if (sortedKeys.includes(key)) add(key);
      continue;
    }

    if (grant.capability_name === "dir" || grant.capability_name === "files") {
      const prefix = typeof config.prefix === "string" ? config.prefix : "";
      if (!prefix) return sortedKeys;
      for (const key of sortedKeys) {
        if (key.startsWith(prefix)) add(key);
      }
    }
  }

  return suggestions;
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

/* ── FileGrantEditor: quick-add file/dir capabilities with name: path [ops] ── */

const FILE_OPS = ["read", "write", "delete", "get_metadata"] as const;
const DIR_OPS = ["list", "read", "write", "create", "delete"] as const;

const OP_DESCRIPTIONS: Record<string, string> = {
  list: "list — list files under prefix",
  read: "read — read file content",
  write: "write — update existing file",
  create: "create — create new file",
  delete: "delete — delete a file",
  get_metadata: "get_metadata — file info (versions, timestamps)",
};

function FileGrantEditor({
  grants,
  onChange,
  processName,
  help,
}: {
  grants: CapGrant[];
  onChange: (grants: CapGrant[]) => void;
  processName: string;
  help?: ReactNode;
}) {
  const [addType, setAddType] = useState<"file" | "dir" | null>(null);
  const [addName, setAddName] = useState("");
  const [addPath, setAddPath] = useState("");

  const fileGrants = useMemo(() =>
    grants.map((g, idx) => ({ ...g, _idx: idx })).filter((g) => g.capability_name === "file" || g.capability_name === "dir"),
  [grants]);

  const usedNames = useMemo(() => new Set(grants.map((g) => g.grant_name)), [grants]);

  const addGrant = useCallback(() => {
    if (!addType || !addName.trim()) return;
    if (usedNames.has(addName.trim())) return;
    const pathKey = addType === "file" ? "key" : "prefix";
    const config = addPath.trim() ? { [pathKey]: addPath.trim() } : null;
    onChange([...grants, { grant_name: addName.trim(), capability_name: addType, config }]);
    setAddType(null);
    setAddName("");
    setAddPath("");
  }, [addType, addName, addPath, grants, onChange, usedNames]);

  const toggleOp = useCallback((grantIdx: number, op: string, allOps: readonly string[]) => {
    const updated = [...grants];
    const g = updated[grantIdx];
    const cfg = { ...(g.config || {}) } as Record<string, unknown>;
    const currentOps = (cfg.ops as string[] | undefined) || [];
    let nextOps: string[];
    if (currentOps.length === 0) {
      nextOps = [...allOps].filter((o) => o !== op);
    } else if (currentOps.includes(op)) {
      nextOps = currentOps.filter((o) => o !== op);
    } else {
      nextOps = [...currentOps, op];
    }
    if (nextOps.length >= allOps.length || nextOps.length === 0) {
      delete cfg.ops;
    } else {
      cfg.ops = nextOps;
    }
    updated[grantIdx] = { ...g, config: Object.keys(cfg).length > 0 ? cfg : null };
    onChange(updated);
  }, [grants, onChange]);

  const removeGrant = useCallback((grantIdx: number) => {
    onChange(grants.filter((_, i) => i !== grantIdx));
  }, [grants, onChange]);

  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <label className="text-[10px] text-[var(--text-muted)] uppercase">Files & Directories</label>
        {help}
      </div>
      {fileGrants.length > 0 && (
        <div className="space-y-1 mb-1">
          {fileGrants.map((g) => {
            const isDir = g.capability_name === "dir";
            const ops = isDir ? DIR_OPS : FILE_OPS;
            const cfg = (g.config || {}) as Record<string, unknown>;
            const currentOps = (cfg.ops as string[] | undefined) || [];
            const pathKey = isDir ? "prefix" : "key";
            const pathVal = cfg[pathKey] as string | undefined;
            return (
              <div key={g._idx} className="flex items-center gap-1.5 text-[11px] font-mono">
                <span
                  className="px-1 py-0 rounded text-[9px]"
                  style={{
                    background: isDir ? "rgba(139,92,246,0.15)" : "rgba(59,130,246,0.15)",
                    color: isDir ? "#a78bfa" : "#60a5fa",
                    border: "1px solid",
                    borderColor: isDir ? "rgba(139,92,246,0.3)" : "rgba(59,130,246,0.3)",
                  }}
                >
                  {isDir ? "dir" : "file"}
                </span>
                <span className="text-[var(--accent)]">{g.grant_name}</span>
                {pathVal && <span className="text-[var(--text-muted)]">: {pathVal}</span>}
                <span className="flex gap-0.5 ml-1">
                  {ops.map((op) => {
                    const isOn = currentOps.length === 0 || currentOps.includes(op);
                    const label = op === "get_metadata" ? "meta" : op === "create" ? "new" : op[0];
                    return (
                      <button
                        key={op}
                        onClick={() => toggleOp(g._idx, op, ops)}
                        className="px-1 py-0 rounded text-[9px] font-mono border cursor-pointer"
                        style={{
                          background: isOn ? "var(--bg-surface)" : "transparent",
                          borderColor: isOn ? "var(--accent)" : "var(--border)",
                          color: isOn ? "var(--accent)" : "var(--text-muted)",
                          opacity: isOn ? 1 : 0.3,
                        }}
                        title={OP_DESCRIPTIONS[op] || op}
                      >
                        {label}
                      </button>
                    );
                  })}
                </span>
                <button
                  onClick={() => removeGrant(g._idx)}
                  className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--error)] text-[10px] leading-none p-0 ml-auto"
                >
                  x
                </button>
              </div>
            );
          })}
        </div>
      )}
      {addType ? (
        <div className="flex items-center gap-1.5 text-[11px]">
          <span
            className="px-1 py-0 rounded text-[9px] font-mono"
            style={{
              background: addType === "dir" ? "rgba(139,92,246,0.15)" : "rgba(59,130,246,0.15)",
              color: addType === "dir" ? "#a78bfa" : "#60a5fa",
            }}
          >
            {addType}
          </span>
          <input
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
            placeholder="name"
            className="bg-transparent border-0 border-b text-[11px] font-mono outline-none px-0 py-0 w-[80px]"
            style={{ borderColor: "var(--accent)", color: "var(--text-primary)" }}
            autoFocus
            autoComplete="off" autoCapitalize="off" spellCheck={false}
            onKeyDown={(e) => {
              if (e.key === "Enter") addGrant();
              if (e.key === "Escape") { setAddType(null); setAddName(""); setAddPath(""); }
            }}
          />
          <span className="text-[var(--text-muted)]">:</span>
          <input
            value={addPath}
            onChange={(e) => setAddPath(e.target.value)}
            placeholder={addType === "dir" ? "/prefix/" : "/path/to/file"}
            className="bg-transparent border-0 border-b text-[11px] font-mono outline-none px-0 py-0 flex-1"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
            autoComplete="off" autoCapitalize="off" spellCheck={false}
            onKeyDown={(e) => {
              if (e.key === "Enter") addGrant();
              if (e.key === "Escape") { setAddType(null); setAddName(""); setAddPath(""); }
            }}
          />
          <button onClick={addGrant} className="text-[9px] px-1.5 py-0 rounded border-0 cursor-pointer" style={{ background: "var(--accent)", color: "white" }}>+</button>
          <button onClick={() => { setAddType(null); setAddName(""); setAddPath(""); }} className="text-[9px] text-[var(--text-muted)] bg-transparent border-0 cursor-pointer p-0">x</button>
        </div>
      ) : (
        <div className="flex gap-1.5">
          <button
            onClick={() => setAddType("file")}
            className="text-[10px] px-1.5 py-0 rounded bg-transparent border cursor-pointer"
            style={{ borderColor: "rgba(59,130,246,0.3)", color: "#60a5fa" }}
          >
            + file
          </button>
          <button
            onClick={() => setAddType("dir")}
            className="text-[10px] px-1.5 py-0 rounded bg-transparent border cursor-pointer"
            style={{ borderColor: "rgba(139,92,246,0.3)", color: "#a78bfa" }}
          >
            + dir
          </button>
          {processName && !usedNames.has("scratch") && (
            <button
              onClick={() => {
                onChange([...grants, { grant_name: "scratch", capability_name: "dir", config: { prefix: `/proc/${processName}/scratch/` } }]);
              }}
              className="text-[10px] px-1.5 py-0 rounded bg-transparent border cursor-pointer"
              style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
            >
              + scratch
            </button>
          )}
          {processName && !usedNames.has("tmp") && (
            <button
              onClick={() => {
                onChange([...grants, { grant_name: "tmp", capability_name: "dir", config: { prefix: `/proc/${processName}/tmp/` } }]);
              }}
              className="text-[10px] px-1.5 py-0 rounded bg-transparent border cursor-pointer"
              style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
            >
              + tmp
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ── CapabilityEditor: named grants with scope config editing ── */

function CapabilityEditor({
  grants,
  onChange,
  suggestions,
  cogentName,
  capabilities,
}: {
  grants: CapGrant[];
  onChange: (grants: CapGrant[]) => void;
  suggestions: string[];
  cogentName: string;
  capabilities: CogosCapability[];
}) {
  const [query, setQuery] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [editingNameIdx, setEditingNameIdx] = useState<number | null>(null);
  const [nameText, setNameText] = useState("");
  const [editingArg, setEditingArg] = useState<{ idx: number; param: string } | null>(null);
  const [argText, setArgText] = useState("");
  const [methodsCache, setMethodsCache] = useState<Record<string, api.CapabilityMethod[]>>({});
  const [loadingMethods, setLoadingMethods] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const usedNames = useMemo(() => new Set(grants.map((g) => g.grant_name)), [grants]);

  const capSchemaMap = useMemo(() => {
    const m: Record<string, Record<string, { type: string; description?: string; items?: { type?: string; enum?: string[] }; enum?: string[] }>> = {};
    for (const c of capabilities) {
      const scopeDef = (c.schema as Record<string, unknown>)?.scope as { properties?: Record<string, unknown> } | undefined;
      if (scopeDef?.properties) {
        m[c.name] = scopeDef.properties as typeof m[string];
      }
    }
    return m;
  }, [capabilities]);

  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    return suggestions
      .filter((s) => (!q || s.toLowerCase().includes(q)))
      .slice(0, 8);
  }, [query, suggestions]);

  const addGrant = useCallback((capName: string) => {
    // Default grant_name = capability_name, but make unique if needed
    let grantName = capName;
    if (usedNames.has(grantName)) {
      let i = 2;
      while (usedNames.has(`${capName}_${i}`)) i++;
      grantName = `${capName}_${i}`;
    }
    onChange([...grants, { grant_name: grantName, capability_name: capName, config: null }]);
    setQuery("");
    setShowSuggestions(false);
  }, [grants, onChange, usedNames]);

  const removeGrant = useCallback((idx: number) => {
    onChange(grants.filter((_, i) => i !== idx));
    if (expandedIdx === idx) setExpandedIdx(null);
    if (editingNameIdx === idx) setEditingNameIdx(null);
    if (editingArg?.idx === idx) setEditingArg(null);
  }, [grants, onChange, expandedIdx, editingNameIdx, editingArg]);

  const toggleExpand = useCallback(async (idx: number) => {
    if (expandedIdx === idx) {
      setExpandedIdx(null);
      return;
    }
    setExpandedIdx(idx);
    const capName = grants[idx].capability_name;
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
  }, [expandedIdx, grants, methodsCache, cogentName]);

  const updateGrantConfig = useCallback((idx: number, updater: (cfg: Record<string, unknown>) => Record<string, unknown>) => {
    const updated = [...grants];
    const cfg = updater({ ...(updated[idx].config || {}) });
    updated[idx] = { ...updated[idx], config: Object.keys(cfg).length > 0 ? cfg : null };
    onChange(updated);
  }, [grants, onChange]);

  const toggleMethod = useCallback((idx: number, methodName: string, allMethodNames: string[]) => {
    updateGrantConfig(idx, (cfg) => {
      const currentOps = (cfg.ops as string[] | undefined) || [];
      const hasOps = currentOps.length > 0;
      let nextOps: string[];
      if (!hasOps) {
        // First toggle: all methods except the clicked one
        nextOps = allMethodNames.filter((m) => m !== methodName);
      } else if (currentOps.includes(methodName)) {
        nextOps = currentOps.filter((m) => m !== methodName);
      } else {
        nextOps = [...currentOps, methodName];
      }
      // If all methods selected, remove ops restriction
      if (nextOps.length >= allMethodNames.length) {
        const { ops: _, ...rest } = cfg;
        return rest;
      }
      return { ...cfg, ops: nextOps };
    });
  }, [updateGrantConfig]);

  const setArgValue = useCallback((idx: number, param: string, value: string) => {
    updateGrantConfig(idx, (cfg) => {
      if (!value.trim()) {
        const { [param]: _, ...rest } = cfg;
        return rest;
      }
      return { ...cfg, [param]: value.trim() };
    });
    setEditingArg(null);
  }, [updateGrantConfig]);

  const startEditName = useCallback((idx: number) => {
    setEditingNameIdx(idx);
    setNameText(grants[idx].grant_name);
  }, [grants]);

  const saveName = useCallback((idx: number) => {
    const trimmed = nameText.trim();
    if (!trimmed) return;
    if (trimmed !== grants[idx].grant_name && usedNames.has(trimmed)) return;
    const updated = [...grants];
    updated[idx] = { ...updated[idx], grant_name: trimmed };
    onChange(updated);
    setEditingNameIdx(null);
  }, [nameText, grants, onChange, usedNames]);

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
      <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">Capabilities</label>
      {grants.length > 0 && (
        <div className="space-y-1 mb-1">
          {grants.map((g, idx) => {
            const isExpanded = expandedIdx === idx;
            const methods = methodsCache[g.capability_name];
            const hasConfig = g.config && Object.keys(g.config).length > 0;
            return (
              <div key={`${g.grant_name}-${idx}`}>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => toggleExpand(idx)}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono border-0 cursor-pointer"
                    style={{
                      background: isExpanded ? "var(--bg-hover)" : "var(--bg-surface)",
                      border: "1px solid var(--border)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    <span style={{ fontSize: "8px", opacity: 0.5 }}>{isExpanded ? "▾" : "▸"}</span>
                    {editingNameIdx === idx ? (
                      <input
                        value={nameText}
                        onChange={(e) => setNameText(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") saveName(idx); if (e.key === "Escape") setEditingNameIdx(null); e.stopPropagation(); }}
                        onBlur={() => saveName(idx)}
                        onClick={(e) => e.stopPropagation()}
                        className="bg-transparent border-0 text-[11px] font-mono text-[var(--accent)] outline-none p-0"
                        style={{ width: `${Math.max(nameText.length, 4)}ch`, borderBottom: "1px solid var(--accent)" }}
                        autoFocus
                      />
                    ) : (
                      <span
                        onClick={(e) => { e.stopPropagation(); startEditName(idx); }}
                        className="hover:underline"
                        style={{ cursor: "text" }}
                        title="Click to rename"
                      >
                        {g.grant_name}
                      </span>
                    )}
                    <span className="text-[9px] text-[var(--text-muted)]">: {g.capability_name}</span>
                    {hasConfig && (
                      <span className="text-[9px] text-[var(--text-muted)]">
                        ({Object.entries(g.config!).map(([k, v]) => `${k}=${Array.isArray(v) ? (v as string[]).join(",") : v}`).join(" ")})
                      </span>
                    )}
                  </button>
                  <button
                    onClick={() => removeGrant(idx)}
                    className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--error)] text-[10px] leading-none p-0"
                  >
                    x
                  </button>
                </div>
                {isExpanded && (() => {
                  const scopeParams = capSchemaMap[g.capability_name] || {};
                  const paramNames = Object.keys(scopeParams);
                  const cfg = (g.config || {}) as Record<string, unknown>;
                  return (
                    <div
                      className="ml-4 mt-1 rounded p-2 space-y-1.5"
                      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                    >
                      {paramNames.length === 0 && (
                        <div className="text-[10px] text-[var(--text-muted)]">No scope parameters</div>
                      )}
                      {paramNames.map((pName) => {
                        const pDef = scopeParams[pName];
                        const isArray = pDef.type === "array";
                        const hasEnum = isArray ? !!pDef.items?.enum : !!pDef.enum;
                        const enumVals = isArray ? pDef.items?.enum : pDef.enum;
                        const currentVal = cfg[pName];
                        const isEditing = editingArg?.idx === idx && editingArg?.param === pName;
                        const hasValue = currentVal !== undefined && currentVal !== null;

                        // For enum arrays (like ops), render as toggleable chips
                        if (hasEnum && isArray && enumVals) {
                          const selected = (currentVal as string[] | undefined) || [];
                          return (
                            <div key={pName}>
                              <div className="text-[9px] text-[var(--text-muted)] uppercase mb-0.5">
                                {pName}
                                {pDef.description && <span className="normal-case ml-1 opacity-60">— {pDef.description}</span>}
                              </div>
                              <div className="flex flex-wrap gap-1">
                                {enumVals.map((v) => {
                                  const isOn = selected.length === 0 || selected.includes(v);
                                  return (
                                    <button
                                      key={v}
                                      onClick={() => {
                                        let next: string[];
                                        if (selected.length === 0) {
                                          // First click: all except this one
                                          next = enumVals.filter((e) => e !== v);
                                        } else if (selected.includes(v)) {
                                          next = selected.filter((e) => e !== v);
                                        } else {
                                          next = [...selected, v];
                                        }
                                        updateGrantConfig(idx, (c) => {
                                          if (next.length >= enumVals.length || next.length === 0) {
                                            const { [pName]: _, ...rest } = c;
                                            return rest;
                                          }
                                          return { ...c, [pName]: next };
                                        });
                                      }}
                                      className="px-1.5 py-0 rounded text-[10px] font-mono border cursor-pointer"
                                      style={{
                                        background: isOn ? "var(--bg-surface)" : "transparent",
                                        borderColor: isOn ? "var(--accent)" : "var(--border)",
                                        color: isOn ? "var(--accent)" : "var(--text-muted)",
                                        opacity: isOn ? 1 : 0.4,
                                      }}
                                    >
                                      {v}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        }

                        // For string/array params, render as clickable label + inline input
                        return (
                          <div key={pName} className="flex items-center gap-1.5">
                            <span
                              className="text-[10px] font-mono cursor-pointer"
                              style={{ color: hasValue ? "var(--accent)" : "var(--text-muted)" }}
                              onClick={() => {
                                setEditingArg({ idx, param: pName });
                                setArgText(
                                  hasValue
                                    ? (Array.isArray(currentVal) ? (currentVal as string[]).join(", ") : String(currentVal))
                                    : "",
                                );
                              }}
                              title={pDef.description || pName}
                            >
                              {pName}
                            </span>
                            {isEditing ? (
                              <input
                                value={argText}
                                onChange={(e) => setArgText(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") {
                                    const val = argText.trim();
                                    if (isArray && val) {
                                      setArgValue(idx, pName, ""); // clear first
                                      updateGrantConfig(idx, (c) => ({
                                        ...c,
                                        [pName]: val.split(",").map((s) => s.trim()).filter(Boolean),
                                      }));
                                      setEditingArg(null);
                                    } else {
                                      setArgValue(idx, pName, val);
                                    }
                                  }
                                  if (e.key === "Escape") setEditingArg(null);
                                }}
                                onBlur={() => {
                                  const val = argText.trim();
                                  if (isArray && val) {
                                    updateGrantConfig(idx, (c) => ({
                                      ...c,
                                      [pName]: val.split(",").map((s) => s.trim()).filter(Boolean),
                                    }));
                                    setEditingArg(null);
                                  } else {
                                    setArgValue(idx, pName, val);
                                  }
                                }}
                                placeholder={pDef.description || pName}
                                className="flex-1 bg-transparent border-0 border-b text-[10px] font-mono outline-none px-0 py-0"
                                style={{ borderColor: "var(--accent)", color: "var(--text-primary)" }}
                                autoFocus
                              />
                            ) : hasValue ? (
                              <span
                                className="text-[10px] font-mono cursor-pointer"
                                style={{ color: "var(--text-secondary)" }}
                                onClick={() => {
                                  setEditingArg({ idx, param: pName });
                                  setArgText(Array.isArray(currentVal) ? (currentVal as string[]).join(", ") : String(currentVal));
                                }}
                              >
                                = {Array.isArray(currentVal) ? (currentVal as string[]).join(", ") : String(currentVal)}
                              </span>
                            ) : (
                              <span
                                className="text-[10px] text-[var(--text-muted)] cursor-pointer opacity-50 hover:opacity-100"
                                onClick={() => {
                                  setEditingArg({ idx, param: pName });
                                  setArgText("");
                                }}
                              >
                                click to set
                              </span>
                            )}
                            {hasValue && !isEditing && (
                              <button
                                onClick={() => updateGrantConfig(idx, (c) => { const { [pName]: _, ...rest } = c; return rest; })}
                                className="text-[8px] text-[var(--text-muted)] hover:text-[var(--error)] bg-transparent border-0 cursor-pointer p-0 leading-none"
                              >
                                x
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}
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
              if (filtered.length > 0) addGrant(filtered[0]);
              else if (query.trim()) addGrant(query);
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
                onClick={() => addGrant(s)}
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

/* ── TagEditor: simple tag list with typeahead (for handlers, output_events) ── */

function TagEditor({
  items,
  onChange,
  suggestions,
  label,
  placeholder,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  suggestions: string[];
  label: string;
  placeholder: string;
}) {
  const [query, setQuery] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
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
      <label className="text-[10px] text-[var(--text-muted)] uppercase block mb-1">{label}</label>
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
          placeholder={placeholder}
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

/* ── Session Log Inline Viewer ── */

function SessionLogInline({ cogentName, runId }: { cogentName: string; runId: string }) {
  const [logs, setLogs] = useState<CogosRunLogsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getRunLogs(cogentName, runId, 100).then((data) => {
      if (!cancelled) { setLogs(data); setLoading(false); }
    }).catch((err) => {
      if (!cancelled) { setError(err instanceof Error ? err.message : "Failed to load"); setLoading(false); }
    });
    return () => { cancelled = true; };
  }, [cogentName, runId]);

  if (loading) return <div className="text-[11px] text-[var(--text-muted)] py-1">Loading session log...</div>;
  if (error) return <div className="text-[11px] text-red-400 py-1">{error}</div>;
  if (!logs || logs.entries.length === 0) return <div className="text-[11px] text-[var(--text-muted)] py-1">No session log entries found.</div>;

  return (
    <div className="rounded border border-[var(--border)] bg-[var(--bg-surface)] mt-1 max-h-[400px] overflow-y-auto">
      {logs.log_stream && (
        <div className="px-3 py-1 text-[10px] text-[var(--text-muted)] border-b border-[var(--border)]" style={{ background: "var(--bg-deep)" }}>
          {logs.log_stream}
        </div>
      )}
      {logs.entries.map((entry, i) => (
        <div
          key={`${entry.log_stream}-${entry.timestamp}-${i}`}
          className="grid gap-2 px-3 py-1.5 text-[11px] font-mono border-b border-[var(--border)] last:border-b-0"
          style={{ gridTemplateColumns: "150px 1fr" }}
        >
          <div className="text-[var(--text-muted)] text-[10px]">{fmtTimestamp(entry.timestamp)}</div>
          <pre className="whitespace-pre-wrap break-words text-[var(--text-secondary)] m-0 text-[10px]">{entry.message}</pre>
        </div>
      ))}
    </div>
  );
}

function SessionLogToggle({ onClick }: { cogentName?: string; runId?: string; onClick?: (e: React.MouseEvent) => void }) {
  return (
    <button
      onClick={onClick}
      className="text-[10px] font-mono px-1 py-0 rounded hover:underline bg-transparent border-0 cursor-pointer"
      style={{ background: "rgba(59,130,246,0.12)", color: "#60a5fa" }}
      title="Session log (inline)"
    >
      L
    </button>
  );
}

/* ── Last Run Display ── */

function LastRunInfo({ run, cogentName, runner }: { run: CogosProcessRun; cogentName?: string; runner?: string }) {
  const [showResult, setShowResult] = useState(false);
  const [showSessionLog, setShowSessionLog] = useState(false);
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
            <>
              <a
                href={buildCogentRunLogsUrl(cogentName, run.id, run.created_at, runner)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--accent)] text-[10px] hover:underline"
                title="View CloudWatch logs"
              >
                CW Logs
              </a>
              <SessionLogToggle cogentName={cogentName} runId={run.id} onClick={() => setShowSessionLog(!showSessionLog)} />
            </>
          )}
        </div>
      </div>
      {showSessionLog && cogentName && <SessionLogInline cogentName={cogentName} runId={run.id} />}
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
  help,
  options,
  value,
  onChange,
}: {
  label: string;
  help?: React.ReactNode;
  options: { value: T; icon: string; title: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <label className="text-[10px] text-[var(--text-muted)] uppercase block">{label}</label>
        {help}
      </div>
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
  { value: "", label: EXECUTOR_DEFAULT_MODEL_LABEL },
  { value: "us.anthropic.claude-haiku-4-5-20251001-v1:0", label: "haiku" },
  { value: "us.anthropic.claude-sonnet-4-20250514-v1:0", label: "sonnet" },
  { value: "us.anthropic.claude-opus-4-20250514-v1:0", label: "opus" },
];

function modelLabel(value: string): string {
  if (!value) return EXECUTOR_DEFAULT_MODEL_LABEL;
  const m = MODELS.find((m) => m.value === value);
  if (m) return m.label;
  if (value.includes("haiku")) return "haiku";
  if (value.includes("opus")) return "opus";
  if (value.includes("sonnet")) return "sonnet";
  return value;
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

/* ── InlineFileEditor: version selector + edit for a single file ── */

function InlineFileEditor({
  fileKey,
  fileSuggestions,
  cogentName,
  onRefresh,
  onClose,
}: {
  fileKey: string;
  fileSuggestions: string[];
  cogentName: string;
  onRefresh?: () => void;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<CogosFileVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [activating, setActivating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveConfirm, setSaveConfirm] = useState<"update" | null>(null);

  const loadVersions = useCallback(async () => {
    setLoading(true);
    try {
      const detail = await api.getFileDetail(cogentName, fileKey);
      const sorted = [...detail.versions].sort((a, b) => b.version - a.version);
      setVersions(sorted);
      if (selectedVersion === null && sorted.length > 0) {
        const active = sorted.find((v) => v.is_active);
        setSelectedVersion(active?.version ?? sorted[0].version);
      }
    } finally {
      setLoading(false);
    }
  }, [cogentName, fileKey, selectedVersion]);

  useEffect(() => {
    setSelectedVersion(null);
    setEditing(false);
    loadVersions();
  }, [fileKey, cogentName]);

  const currentVersion = useMemo(
    () => versions.find((v) => v.version === selectedVersion) ?? versions[0],
    [versions, selectedVersion],
  );

  const handleActivate = useCallback(async (version: number) => {
    if (activating) return;
    setActivating(true);
    try {
      await api.activateFileVersion(cogentName, fileKey, version);
      await loadVersions();
      onRefresh?.();
    } finally {
      setActivating(false);
    }
  }, [cogentName, fileKey, activating, loadVersions, onRefresh]);

  const handleStartEdit = useCallback(() => {
    setEditContent(currentVersion?.content ?? "");
    setEditing(true);
    setSaveConfirm(null);
  }, [currentVersion]);

  const handleUpdate = useCallback(async () => {
    if (saving || !selectedVersion) return;
    setSaving(true);
    try {
      await api.updateFileVersionContent(cogentName, fileKey, selectedVersion, editContent);
      setEditing(false);
      setSaveConfirm(null);
      await loadVersions();
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, fileKey, selectedVersion, editContent, saving, loadVersions, onRefresh]);

  const handleSaveNewVersion = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      const fv = await api.updateFile(cogentName, fileKey, { content: editContent });
      setSelectedVersion(fv.version);
      setEditing(false);
      setSaveConfirm(null);
      await loadVersions();
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, fileKey, editContent, saving, loadVersions, onRefresh]);

  if (loading) {
    return <div className="px-2 py-1 text-[10px] text-[var(--text-muted)]">Loading...</div>;
  }

  return (
    <div style={{ background: "var(--bg-deep)" }}>
      {/* Version selector bar */}
      <div className="px-2 py-1 flex items-center gap-1 overflow-x-auto flex-wrap" style={{ borderTop: "1px solid var(--border)" }}>
        {versions.map((v) => {
          const isActive = v.is_active;
          const isSel = v.version === selectedVersion;
          return (
            <button
              key={v.version}
              onClick={() => { setSelectedVersion(v.version); setEditing(false); }}
              className="flex items-center gap-1 px-1.5 py-0.5 rounded border cursor-pointer text-[10px] font-mono flex-shrink-0"
              style={{
                background: isSel ? "var(--bg-hover)" : "transparent",
                borderColor: isSel ? "var(--accent)" : "var(--border)",
                color: isSel ? "var(--accent)" : "var(--text-muted)",
                fontWeight: isSel ? 600 : 400,
              }}
            >
              v{v.version}
              {isActive && (
                <span className="text-[7px] px-0.5 rounded-full font-semibold" style={{ background: "var(--accent)", color: "var(--bg-deep)" }}>
                  active
                </span>
              )}
            </button>
          );
        })}
        {currentVersion && !currentVersion.is_active && (
          <button
            onClick={() => handleActivate(currentVersion.version)}
            disabled={activating}
            className="text-[9px] px-1.5 py-0.5 rounded border cursor-pointer disabled:opacity-40"
            style={{ background: "transparent", borderColor: "var(--accent)", color: "var(--accent)" }}
          >
            {activating ? "..." : "Make Active"}
          </button>
        )}
        {!editing && (
          <button
            onClick={handleStartEdit}
            className="text-[9px] px-1.5 py-0.5 rounded border cursor-pointer"
            style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            Edit
          </button>
        )}
        <button
          onClick={onClose}
          className="text-[9px] px-1.5 py-0.5 rounded border cursor-pointer ml-auto"
          style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          Close
        </button>
      </div>

      {/* Content area */}
      {currentVersion && (
        editing ? (
          <div className="px-2 py-1.5 space-y-1.5">
            <FileReferenceTextarea
              value={editContent}
              onChange={(value) => { setEditContent(value); setSaveConfirm(null); }}
              suggestions={fileSuggestions}
              currentKey={fileKey}
              placeholder="File content..."
              rows={8}
              className="w-full px-2 py-1 text-[11px] rounded border font-mono resize-y"
              style={{ background: "var(--bg-base)", borderColor: "var(--border)", color: "var(--text-primary)" }}
              helperText="Type @{ to reference another file."
            />
            <div className="flex gap-1.5 items-center flex-wrap">
              {saveConfirm === "update" ? (
                <span className="flex items-center gap-1 text-[10px]">
                  <span className="text-[var(--text-muted)]">Overwrite v{selectedVersion}?</span>
                  <button onClick={handleUpdate} disabled={saving} className="text-[var(--accent)] border-0 bg-transparent cursor-pointer text-[10px] font-semibold disabled:opacity-40">{saving ? "..." : "Yes"}</button>
                  <button onClick={() => setSaveConfirm(null)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[10px]">No</button>
                </span>
              ) : (
                <button
                  onClick={() => setSaveConfirm("update")}
                  className="text-[9px] px-1.5 py-0.5 rounded border cursor-pointer"
                  style={{ background: "transparent", borderColor: "var(--accent)", color: "var(--accent)" }}
                >
                  Update v{selectedVersion}
                </button>
              )}
              <button
                onClick={handleSaveNewVersion}
                disabled={saving}
                className="text-[9px] px-1.5 py-0.5 rounded border-0 cursor-pointer disabled:opacity-40"
                style={{ background: "var(--accent)", color: "white" }}
              >
                {saving ? "Saving..." : "Save as New Version"}
              </button>
              <button
                onClick={() => { setEditing(false); setSaveConfirm(null); }}
                className="text-[9px] px-1.5 py-0.5 rounded border cursor-pointer"
                style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div
            className="text-[11px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap px-2 py-1.5"
            style={{ maxHeight: "300px", overflowY: "auto" }}
          >
            {currentVersion.content || "(empty)"}
          </div>
        )
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
  promptReferenceSuggestions,
  capabilitySuggestions,
  eventTypeSuggestions,
  cogentName,
  capabilities,
}: {
  form: ProcessForm;
  onChange: React.Dispatch<React.SetStateAction<ProcessForm>>;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  isNew: boolean;
  resourceSuggestions: string[];
  promptReferenceSuggestions: string[];
  capabilitySuggestions: string[];
  eventTypeSuggestions: string[];
  cogentName: string;
  capabilities: CogosCapability[];
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
          label="Process Mode"
          help={(
            <SectionHelp
              title="Process Mode"
              bullets={[
                "One-shot runs once for a wake or delivery, then exits.",
                "Daemon stays installed, wakes repeatedly, and returns to waiting between runs.",
                "This is separate from session resume settings in process metadata.",
              ]}
            />
          )}
          value={form.mode}
          onChange={(mode) => onChange({ ...form, mode })}
          options={[
            { value: "one_shot" as const, icon: "→", title: "One-shot: run once, then exit" },
            { value: "daemon" as const, icon: "⟳", title: "Daemon: wake repeatedly and return to waiting" },
          ]}
        />
        <IconButtonGroup
          label="Session Resume"
          help={(
            <SectionHelp
              title="Session Resume"
              bullets={[
                "Off: write session artifacts, but always start from a fresh prompt state.",
                "On: resume from the latest checkpoint for this process before appending the new trigger.",
                "This is separate from Process Mode. A daemon can still have session resume off, and a one-shot process can have it on.",
              ]}
            />
          )}
          value={form.session_resume ? "on" : "off"}
          onChange={(value) => onChange({ ...form, session_resume: value === "on" })}
          options={[
            { value: "off" as const, icon: "off", title: "Do not load a checkpoint before each run" },
            { value: "on" as const, icon: "on", title: "Resume from the latest process session checkpoint" },
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
        <div className="flex items-center gap-2 mb-1">
          <label className="text-[10px] text-[var(--text-muted)] uppercase">Prompt Source</label>
          <SectionHelp
            title="1. Prompt Source"
            bullets={[
              "Inline instructions stored on the process itself.",
              "This is the full process prompt source.",
              "Use @{file-key} to inline file content into the system prompt.",
            ]}
          />
        </div>
        <FileReferenceTextarea
          className={INPUT_CLS}
          rows={4}
          value={form.content}
          onChange={(value) => onChange({ ...form, content: value })}
          suggestions={promptReferenceSuggestions}
          placeholder="Add process instructions..."
          helperText="Type @{ to reference a readable file."
          style={{ resize: "vertical" }}
        />
      </div>

      {/* Files & Directories — quick-add for file/dir capabilities */}
      <FileGrantEditor
        grants={form.grants}
        onChange={(grants) => onChange((prev) => ({ ...prev, grants }))}
        processName={form.name}
        help={(
          <SectionHelp
            title="2. Files & Directories"
            bullets={[
              "Runtime file access grants, not prompt content.",
              "Controls what the process can read or write through capabilities.",
              "Use @{file-key} in prompt source when you want static prompt includes.",
            ]}
          />
        )}
      />

      {/* Other Capabilities (file/dir shown above) */}
      <CapabilityEditor
        grants={form.grants.filter((g) => g.capability_name !== "file" && g.capability_name !== "dir")}
        onChange={(nonFileGrants) => {
          // Merge back: keep file/dir grants, replace the rest
          const fileGrants = form.grants.filter((g) => g.capability_name === "file" || g.capability_name === "dir");
          onChange((prev) => ({ ...prev, grants: [...fileGrants, ...nonFileGrants] }));
        }}
        suggestions={capabilitySuggestions.filter((s) => s !== "file" && s !== "dir")}
        cogentName={cogentName}
        capabilities={capabilities}
      />

      {/* Events: receive | send */}
      <div className="flex gap-4">
        <div className="flex-1">
          <TagEditor
            items={form.handlers}
            onChange={(handlers) => onChange({ ...form, handlers })}
            suggestions={eventTypeSuggestions}
            label="Receive Events"
            placeholder="Add event subscription..."
          />
        </div>
        <div className="flex-1">
          <TagEditor
            items={form.output_events}
            onChange={(output_events) => onChange({ ...form, output_events })}
            suggestions={eventTypeSuggestions}
            label="Send Events"
            placeholder="Add output event..."
          />
        </div>
      </div>

      {/* Resources */}
      <TagListEditor
        label="Resources"
        items={form.resources}
        onChange={(resources) => onChange((prev) => ({ ...prev, resources }))}
        suggestions={resourceSuggestions}
      />

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

export function ProcessesPanel({ processes, cogentName, onRefresh, resources, runs, files, capabilities, eventTypes, currentEpoch }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null); // "new" for create
  const [form, setForm] = useState<ProcessForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailRuns, setDetailRuns] = useState<CogosProcessRun[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [resolvedPrompt, setResolvedPrompt] = useState<string>("");
  const [showResolved, setShowResolved] = useState(false);
  const [promptTree, setPromptTree] = useState<Array<{ key: string; content: string; is_direct: boolean }>>([]);
  const [expandedPromptFiles, setExpandedPromptFiles] = useState<Set<string>>(new Set());
  const [detailCapGrants, setDetailCapGrants] = useState<Array<{ id: string; grant_name: string; capability_name: string; config: Record<string, unknown> | null }>>([]);
  const [detailIncludes, setDetailIncludes] = useState<Array<{ key: string; content: string }>>([]);
  const [detailHandlers, setDetailHandlers] = useState<Array<{ id: string; channel?: string; event_pattern?: string; enabled: boolean }>>([]);
  const [editingFileKey, setEditingFileKey] = useState<string | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<"tree" | "status">("tree");
  const [sessionLogRunId, setSessionLogRunId] = useState<string | null>(null);

  const resourceSuggestions = useMemo(() => resources.map((r) => r.name), [resources]);
  const fileSuggestions = useMemo(() => files.map((f) => f.key), [files]);
  const promptReferenceSuggestions = useMemo(
    () => getPromptReferenceSuggestions(fileSuggestions, form.grants),
    [fileSuggestions, form.grants],
  );
  const capabilitySuggestions = useMemo(() => capabilities.map((c) => c.name), [capabilities]);
  const eventTypeSuggestions = useMemo(() => eventTypes.map((et) => et.name), [eventTypes]);

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

  const fetchDetail = useCallback(async (id: string, opts?: { preserveExpanded?: boolean }) => {
    setLoadingDetail(true);
    try {
      const detail = await api.getProcessDetail(cogentName, id);
      setDetailRuns(detail.runs);
      setResolvedPrompt(detail.resolved_prompt || "");
      setDetailCapGrants(detail.cap_grants || []);
      setDetailIncludes(detail.includes || []);
      setDetailHandlers(detail.handlers || []);
      setPromptTree(detail.prompt_tree || []);
      if (!opts?.preserveExpanded) {
        const tree = detail.prompt_tree || [];
        setExpandedPromptFiles(new Set(tree.length > 0 ? [tree[tree.length - 1].key] : []));
      }
    } catch {
      setDetailRuns([]);
      setResolvedPrompt("");
      setDetailCapGrants([]);
      setDetailIncludes([]);
      setDetailHandlers([]);
      setPromptTree([]);
      setExpandedPromptFiles(new Set());
    }
    setLoadingDetail(false);
  }, [cogentName]);

  const handleSelect = useCallback(async (id: string) => {
    if (selectedId === id) {
      setSelectedId(null);
      setDetailRuns([]);
      setResolvedPrompt("");
      setShowResolved(false);
      setDetailIncludes([]);
      setDetailHandlers([]);
      setPromptTree([]);
      setExpandedPromptFiles(new Set());
      return;
    }
    setSelectedId(id);
    setShowResolved(false);
    await fetchDetail(id);
  }, [selectedId, fetchDetail]);

  const handleNew = useCallback(() => {
    setEditingId("new");
    setForm(EMPTY_FORM);
    setSelectedId(null);
  }, []);

  const handleEdit = useCallback((p: CogosProcess) => {
    setEditingId(p.id);
    const handlerPatterns = detailHandlers.map((h) => h.channel || h.event_pattern || "");
    const grants: CapGrant[] = detailCapGrants.map((g) => ({
      grant_name: g.grant_name,
      capability_name: g.capability_name,
      config: g.config,
    }));
    setForm(formFromProcess(p, grants, handlerPatterns));
  }, [detailCapGrants, detailHandlers]);

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
        priority: parseFloat(form.priority) || 0,
        runner: form.runner,
        status: form.status,
        model: form.model.trim() || null,
        max_duration_ms: formDurationToMs(form.max_duration_val, form.max_duration_unit),
        max_retries: parseInt(form.max_retries) || 0,
        preemptible: form.preemptible,
        clear_context: form.clear_context,
        resources: form.resources,
        cap_grants: form.grants.map((g) => ({
          grant_name: g.grant_name,
          capability_name: g.capability_name,
          config: g.config,
        })),
        metadata: buildMetadataWithSessionResume(form.metadata, form.session_resume),
        handlers: form.handlers,
        output_events: form.output_events,
      };
      if (editingId === "new") {
        await api.createProcess(cogentName, body as Parameters<typeof api.createProcess>[1]);
      } else {
        await api.updateProcess(cogentName, editingId!, body as Parameters<typeof api.updateProcess>[2]);
      }
      const savedId = editingId;
      setEditingId(null);
      setForm(EMPTY_FORM);
      setError(null);
      onRefresh();
      // Re-fetch detail so capabilities/files are fresh for next edit
      if (savedId && savedId !== "new" && selectedId === savedId) {
        await fetchDetail(savedId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save process");
      onRefresh();
    }
    setSaving(false);
  }, [form, editingId, cogentName, onRefresh, selectedId, fetchDetail]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await api.deleteProcess(cogentName, id);
      setConfirmDeleteId(null);
      setSelectedId(null);
      setEditingId(null);
      setError(null);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete process");
      onRefresh();
    }
  }, [cogentName, onRefresh]);

  return (
    <div>
      {error && (
        <div className="mb-3 px-3 py-2 rounded text-[12px] bg-red-500/10 text-red-400 border border-red-500/30 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-300 bg-transparent border-0 cursor-pointer">✕</button>
        </div>
      )}
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
            promptReferenceSuggestions={promptReferenceSuggestions}
            capabilitySuggestions={capabilitySuggestions}
            eventTypeSuggestions={eventTypeSuggestions}
            cogentName={cogentName}
            capabilities={capabilities}
          />
        </div>
      )}

      {/* View mode toggle + Process list */}
      {processes.length === 0 && editingId !== "new" && (
        <div className="text-[var(--text-muted)] text-xs py-8 text-center">No processes</div>
      )}

      {processes.length > 0 && (
        <div className="flex items-center gap-1 mb-2">
          {(["tree", "status"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setViewMode(m)}
              className="px-2 py-0.5 text-[10px] rounded cursor-pointer border-0"
              style={{
                background: viewMode === m ? "var(--bg-hover)" : "transparent",
                color: viewMode === m ? "var(--text-primary)" : "var(--text-muted)",
              }}
            >
              {m === "tree" ? "Tree" : "Status"}
            </button>
          ))}
        </div>
      )}

      {(() => {
        // Build parent→children map
        const procById = new Map(processes.map((p) => [p.id, p]));
        const childrenByParent = new Map<string, CogosProcess[]>();
        const rootProcesses: CogosProcess[] = [];
        for (const p of processes) {
          if (p.parent_process && procById.has(p.parent_process)) {
            const siblings = childrenByParent.get(p.parent_process) || [];
            siblings.push(p);
            childrenByParent.set(p.parent_process, siblings);
          } else {
            rootProcesses.push(p);
          }
        }
        // Flatten a process and its descendants into an ordered list with depth
        function flattenTree(proc: CogosProcess, depth: number): { proc: CogosProcess; depth: number }[] {
          const result: { proc: CogosProcess; depth: number }[] = [{ proc, depth }];
          const children = childrenByParent.get(proc.id) || [];
          for (const child of children) {
            result.push(...flattenTree(child, depth + 1));
          }
          return result;
        }

        // Build ancestor path for a process (for status view breadcrumbs)
        function ancestorPath(proc: CogosProcess): string[] {
          const path: string[] = [];
          let cur = proc.parent_process ? procById.get(proc.parent_process) : undefined;
          while (cur) {
            path.unshift(cur.name);
            cur = cur.parent_process ? procById.get(cur.parent_process) : undefined;
          }
          return path;
        }

        const STATUS_ORDER = ["running", "runnable", "waiting", "blocked", "suspended", "completed", "disabled"];

        type GroupEntry = { proc: CogosProcess; depth: number; ancestors?: string[] };

        let grouped: { label: string; variant: string; entries: GroupEntry[] }[];

        if (viewMode === "tree") {
          // Tree view: group by root process, show full hierarchy
          const treeEntries = rootProcesses.flatMap((p) => flattenTree(p, 0));
          grouped = [{ label: "all", variant: "neutral", entries: treeEntries }];
        } else {
          // Status view: flat list grouped by status, with ancestor breadcrumbs
          grouped = STATUS_ORDER
            .map((status) => {
              const matching = processes.filter((p) => p.status === status);
              const entries: GroupEntry[] = matching.map((p) => ({
                proc: p, depth: 0, ancestors: ancestorPath(p),
              }));
              return { label: status, variant: STATUS_VARIANT[status] || "neutral", entries };
            })
            .filter((g) => g.entries.length > 0);
          const knownStatuses = new Set(STATUS_ORDER);
          const extra = processes.filter((p) => !knownStatuses.has(p.status));
          if (extra.length > 0) {
            grouped.push({ label: "other", variant: "neutral", entries: extra.map((p) => ({ proc: p, depth: 0, ancestors: ancestorPath(p) })) });
          }
        }

        return grouped.map((group) => (
      <div key={group.label} className="mb-4 rounded-md overflow-hidden" style={{ border: "1px solid var(--border)" }}>
        {/* Hide group header in tree view when there's only one "all" group */}
        {viewMode !== "tree" && (
        <div
          className="flex items-center px-3 py-1.5 text-[10px] uppercase tracking-wide font-medium text-[var(--text-muted)] cursor-pointer select-none"
          style={{
            background: "var(--bg-deep)",
            borderBottom: collapsedGroups.has(group.label) ? "none" : "1px solid var(--border)",
          }}
          onClick={() => setCollapsedGroups((prev) => {
            const next = new Set(prev);
            if (next.has(group.label)) next.delete(group.label);
            else next.add(group.label);
            return next;
          })}
        >
          <span className="mr-2 text-[10px]" style={{ width: "12px", display: "inline-block" }}>
            {collapsedGroups.has(group.label) ? "▸" : "▾"}
          </span>
          <Badge variant={(STATUS_VARIANT[group.label] || "neutral") as BadgeVariant}>{group.label}</Badge>
          <span className="ml-2 text-[var(--text-muted)]">({group.entries.length})</span>
        </div>
        )}
        {!collapsedGroups.has(group.label) && group.entries.map(({ proc, depth, ancestors }) => {
          const isSelected = selectedId === proc.id;
          const isEditing = editingId === proc.id;
          const lastRun = lastRunByProcess[proc.id];
          const sessionConfig = readSessionConfig(proc.metadata);

          return (
            <div key={proc.id}>
              {/* Row */}
              <div
                className="grid items-center px-3 py-2 cursor-pointer transition-colors"
                style={{
                  gridTemplateColumns: "1fr 1fr 90px",
                  background: isSelected ? "var(--bg-hover)" : "var(--bg-surface)",
                  borderBottom: "1px solid var(--border)",
                  paddingLeft: `${12 + depth * 20}px`,
                  opacity: (currentEpoch != null && proc.epoch < currentEpoch) ? 0.5 : 1,
                }}
                role="button"
                tabIndex={0}
                aria-label={`Process ${proc.name}`}
                aria-expanded={isSelected}
                onClick={() => handleSelect(proc.id)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleSelect(proc.id); } }}
                onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = "var(--bg-surface)"; }}
              >
                <span className="inline-flex items-center gap-1.5 text-[var(--text-primary)] font-medium text-[12px] truncate">
                  {depth > 0 && <span className="text-[var(--text-muted)] text-[10px]">└</span>}
                  <span className="text-[var(--text-muted)]" title={proc.mode}>
                    {proc.mode === "daemon" ? "⟳" : "→"}
                  </span>
                  {viewMode === "status" && ancestors && ancestors.length > 0 && (
                    <span className="text-[var(--text-muted)] text-[10px]">
                      {ancestors.join(" › ")}{" › "}
                    </span>
                  )}
                  {proc.name}
                  {viewMode === "tree" && (
                    <Badge variant={STATUS_VARIANT[proc.status] || "neutral"}>{proc.status}</Badge>
                  )}
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
                        href={buildCogentRunLogsUrl(cogentName, lastRun.id, lastRun.created_at, proc.runner)}
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
                  <span className="inline-flex items-center justify-center w-[22px] h-[18px]">
                    {lastRun ? (
                      <SessionLogToggle cogentName={cogentName} runId={lastRun.id} onClick={(e) => { e.stopPropagation(); setSessionLogRunId(sessionLogRunId === lastRun.id ? null : lastRun.id); }} />
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

              {/* Inline session log */}
              {lastRun && sessionLogRunId === lastRun.id && (
                <div className="px-4 py-2" style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}>
                  <SessionLogInline cogentName={cogentName} runId={lastRun.id} />
                </div>
              )}

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
                    <span className="text-[var(--text-muted)]">session resume: <span className="text-[var(--text-secondary)]">{sessionConfig.resume ? "on" : "off"}</span></span>
                    {(sessionConfig.resume || sessionConfig.explicit) && (
                      <span className="text-[var(--text-muted)]">session scope: <span className="text-[var(--text-secondary)]">{sessionConfig.scope}</span></span>
                    )}
                  </div>

                  {/* Context — includes + prompt tree merged */}
                  {(() => {
                    const promptKeys = new Set(promptTree.map((e) => e.key));
                    const includeEntries = detailIncludes
                      .filter((inc) => !promptKeys.has(inc.key))
                      .map((inc) => ({ key: inc.key, content: inc.content, is_direct: false }));
                    const allEntries = [...includeEntries, ...promptTree];
                    return allEntries.length > 0 && (
                    <div>
                      <div className="text-[10px] text-[var(--text-muted)] uppercase mb-1">
                        Context ({allEntries.length} {allEntries.length === 1 ? "file" : "files"})
                      </div>
                      <div className="rounded overflow-hidden" style={{ border: "1px solid var(--border)" }}>
                        {allEntries.map((entry) => {
                          const isExpanded = expandedPromptFiles.has(entry.key);
                          const isContent = entry.key === "<content>";
                          const isFileEditing = editingFileKey === entry.key;
                          return (
                            <div key={entry.key} style={{ borderBottom: "1px solid var(--border)" }}>
                              <div
                                className="flex items-center gap-2 px-2 py-1 cursor-pointer text-[11px]"
                                style={{ background: "var(--bg-surface)" }}
                                onClick={() => setExpandedPromptFiles((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(entry.key)) next.delete(entry.key);
                                  else next.add(entry.key);
                                  return next;
                                })}
                              >
                                <span className="text-[9px] text-[var(--text-muted)]" style={{ width: "10px" }}>
                                  {isExpanded ? "▾" : "▸"}
                                </span>
                                <span className="font-mono text-[var(--text-secondary)] flex-1 truncate">
                                  {isContent ? "content (inline)" : entry.key}
                                </span>
                                {!isContent && (
                                  <span className="text-[9px] text-[var(--text-muted)]">
                                    {entry.is_direct ? "direct" : "include"}
                                  </span>
                                )}
                                {!isContent && !isFileEditing && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setEditingFileKey(entry.key);
                                      setExpandedPromptFiles((prev) => new Set([...prev, entry.key]));
                                    }}
                                    className="text-[9px] text-[var(--text-muted)] hover:text-[var(--accent)] bg-transparent border-0 cursor-pointer p-0 leading-none"
                                    title="Edit file contents"
                                  >
                                    edit
                                  </button>
                                )}
                              </div>
                              {isExpanded && (
                                isFileEditing ? (
                                  <InlineFileEditor
                                    fileKey={entry.key}
                                    fileSuggestions={fileSuggestions}
                                    cogentName={cogentName}
                                    onRefresh={async () => { onRefresh(); await fetchDetail(proc.id, { preserveExpanded: true }); }}
                                    onClose={() => setEditingFileKey(null)}
                                  />
                                ) : (
                                  <div
                                    className="text-[11px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap px-2 py-1.5"
                                    style={{ background: "var(--bg-deep)", maxHeight: "300px", overflowY: "auto" }}
                                  >
                                    {entry.content || "(empty)"}
                                  </div>
                                )
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                    );
                  })()}

                  {/* Files & Directories */}
                  {(() => {
                    const fileGrants = detailCapGrants.filter((g) => g.capability_name === "file" || g.capability_name === "dir");
                    return fileGrants.length > 0 && (
                      <div>
                        <div className="text-[10px] text-[var(--text-muted)] uppercase mb-1">Files & Directories</div>
                        <div className="flex flex-wrap gap-1">
                          {fileGrants.map((g) => {
                            const isDir = g.capability_name === "dir";
                            const cfg = g.config || {};
                            const path = (cfg as Record<string, unknown>)[isDir ? "prefix" : "key"] as string | undefined;
                            const ops = (cfg as Record<string, unknown>).ops as string[] | undefined;
                            return (
                              <span
                                key={g.id}
                                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono"
                                style={{
                                  background: "var(--bg-surface)",
                                  border: "1px solid",
                                  borderColor: isDir ? "rgba(139,92,246,0.3)" : "rgba(59,130,246,0.3)",
                                  color: isDir ? "#a78bfa" : "#60a5fa",
                                }}
                                title={JSON.stringify(g.config)}
                              >
                                <span className="text-[9px]">{isDir ? "dir" : "file"}</span>
                                <span style={{ color: "var(--accent)" }}>{g.grant_name}</span>
                                {path && <span className="text-[var(--text-muted)]">: {path}</span>}
                                {ops && <span className="text-[9px] text-[var(--text-muted)]">[{ops.map((o) => o[0]).join("")}]</span>}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })()}

                  {/* Other Capabilities */}
                  {(() => {
                    const otherGrants = detailCapGrants.filter((g) => g.capability_name !== "file" && g.capability_name !== "dir");
                    return otherGrants.length > 0 && (
                      <div>
                        <div className="text-[10px] text-[var(--text-muted)] uppercase mb-1">Capabilities</div>
                        <div className="flex flex-wrap gap-1">
                          {otherGrants.map((g) => (
                            <span
                              key={g.id}
                              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono"
                              style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--accent)" }}
                              title={g.config ? JSON.stringify(g.config) : undefined}
                            >
                              {g.grant_name}
                              {g.grant_name !== g.capability_name && (
                                <span className="text-[10px] text-[var(--text-muted)]">: {g.capability_name}</span>
                              )}
                              {g.config && Object.keys(g.config).length > 0 && (
                                <span className="text-[9px] text-[var(--text-muted)]">
                                  ({Object.entries(g.config).map(([k, v]) => `${k}=${Array.isArray(v) ? (v as string[]).join(",") : v}`).join(" ")})
                                </span>
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })()}

                  {/* Events — merged receive + send with icons */}
                  {(detailHandlers.length > 0 || (proc.output_events && proc.output_events.length > 0)) && (
                    <div>
                      <div className="text-[10px] text-[var(--text-muted)] uppercase mb-1">Events</div>
                      <div className="flex flex-wrap gap-1">
                        {detailHandlers.map((h) => (
                          <span
                            key={h.id}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono"
                            style={{
                              background: "rgba(59,130,246,0.08)",
                              border: "1px solid rgba(59,130,246,0.25)",
                              color: h.enabled ? "#60a5fa" : "var(--text-muted)",
                              opacity: h.enabled ? 1 : 0.6,
                            }}
                          >
                            →{h.channel || h.event_pattern}{!h.enabled && " (off)"}
                          </span>
                        ))}
                        {(proc.output_events || []).map((e) => (
                          <span
                            key={e}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono"
                            style={{
                              background: "rgba(34,197,94,0.08)",
                              border: "1px solid rgba(34,197,94,0.25)",
                              color: "#4ade80",
                            }}
                          >
                            {e}→
                          </span>
                        ))}
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
                            <React.Fragment key={run.id}>
                              <tr style={{ borderBottom: "1px solid var(--border)" }}>
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
                                <td className="px-2 py-1 text-right whitespace-nowrap">
                                  <span className="inline-flex items-center gap-1">
                                    <a
                                      href={buildCogentRunLogsUrl(cogentName, run.id, run.created_at, proc.runner)}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-[var(--accent)] text-[10px] hover:underline"
                                      title="CloudWatch logs"
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      CW
                                    </a>
                                    <SessionLogToggle cogentName={cogentName} runId={run.id} onClick={(e) => { e.stopPropagation(); setSessionLogRunId(sessionLogRunId === run.id ? null : run.id); }} />
                                  </span>
                                </td>
                              </tr>
                              {sessionLogRunId === run.id && (
                                <tr>
                                  <td colSpan={7} className="px-2 py-2" style={{ background: "var(--bg-deep)" }}>
                                    <SessionLogInline cogentName={cogentName} runId={run.id} />
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
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
                    promptReferenceSuggestions={promptReferenceSuggestions}
                    capabilitySuggestions={capabilitySuggestions}
                    eventTypeSuggestions={eventTypeSuggestions}
                    cogentName={cogentName}
                    capabilities={capabilities}
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
