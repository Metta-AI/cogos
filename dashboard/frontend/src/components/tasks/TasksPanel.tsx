"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import type { Task, MemoryItem, Program, Tool, TimeRange } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import * as api from "@/lib/api";
import { fmtTimestamp } from "@/lib/format";

interface TasksPanelProps {
  tasks: Task[];
  cogentName: string;
  onRefresh: () => void;
  memory: MemoryItem[];
  programs: Program[];
  tools: Tool[];
  timeRange: TimeRange;
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  runnable: "info",
  scheduled: "warning",
  running: "accent",
  completed: "success",
  disabled: "neutral",
  failed: "error",
  timeout: "warning",
};

const STATUSES = ["runnable", "scheduled", "running", "completed", "disabled"];

const STUCK_THRESHOLD_MS = 10 * 60 * 1000;
const RUN_COUNT_WINDOWS = ["1m", "5m", "1h", "24h", "7d"] as const;

// Map page-level TimeRange to the closest run_counts window key
const TIME_RANGE_TO_WINDOW: Record<TimeRange, string> = {
  "1m": "1m",
  "10m": "5m",
  "1h": "1h",
  "24h": "24h",
  "1w": "7d",
};

function isStuck(task: Task): boolean {
  if (task.status !== "running") return false;
  if (!task.updated_at) return false;
  return Date.now() - new Date(task.updated_at).getTime() > STUCK_THRESHOLD_MS;
}

interface TaskRun {
  id: string;
  program_name: string;
  status: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  tokens_input: number | null;
  tokens_output: number | null;
  cost_usd: number;
  error: string | null;
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  if (m < 60) return `${m}m${rem}s`;
  const h = Math.floor(m / 60);
  return `${h}h${m % 60}m`;
}

function fmtTokens(n: number | null): string {
  if (n == null || n === 0) return "";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

interface UndoToast {
  taskIds: string[];
  taskName: string;
  timer: ReturnType<typeof setTimeout>;
}

/* ── TagListEditor: editable list with typeahead ── */

function TagListEditor({
  label,
  items,
  onChange,
  suggestions,
  inputStyle,
}: {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  suggestions: string[];
  inputStyle: React.CSSProperties;
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

  // Close dropdown on outside click
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
    <div className="flex gap-2" ref={wrapperRef}>
      <label className="text-[10px] text-[var(--text-muted)] uppercase w-16 pt-1 shrink-0">{label}</label>
      <div className="flex-1">
        {/* Current items as tags */}
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
        {/* Input with typeahead */}
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
            style={{ ...inputStyle, fontSize: "11px" }}
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
    </div>
  );
}

/* ── Main component ── */

export function TasksPanel({ tasks, cogentName, onRefresh, memory, programs, tools: toolsList, timeRange }: TasksPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedRuns, setExpandedRuns] = useState<TaskRun[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<Task>>({});
  const [creating, setCreating] = useState(false);
  const [newTask, setNewTask] = useState<Partial<Task>>({ name: "", description: "", content: "", priority: 0.0, program_name: "do-content" });
  const [editingPriorityId, setEditingPriorityId] = useState<string | null>(null);
  const [editingPriorityValue, setEditingPriorityValue] = useState("");
  const [undoToast, setUndoToast] = useState<UndoToast | null>(null);
  const [pendingDeletes, setPendingDeletes] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy] = useState<"name" | "priority">(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("tasks-sort");
      if (saved === "name" || saved === "priority") return saved;
    }
    return "priority";
  });
  const undoRef = useRef<UndoToast | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback((ids: string[]) => {
    setSelectedIds((prev) => {
      const allSelected = ids.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allSelected) {
        ids.forEach((id) => next.delete(id));
      } else {
        ids.forEach((id) => next.add(id));
      }
      return next;
    });
  }, []);

  const [bulkConfirm, setBulkConfirm] = useState<{ action: string; ids: string[]; taskList?: Task[] } | null>(null);

  const handleBulkRun = useCallback(async (ids: string[]) => {
    const selected = ids.filter((id) => selectedIds.has(id));
    if (selected.length === 0) return;
    try {
      await Promise.all(selected.map((id) => api.updateTask(cogentName, id, { status: "scheduled" })));
    } catch (err) {
      console.error("Bulk run failed:", err);
    }
    setSelectedIds((prev) => { const next = new Set(prev); selected.forEach((id) => next.delete(id)); return next; });
    onRefresh();
  }, [selectedIds, cogentName, onRefresh]);

  const handleBulkStop = useCallback(async (ids: string[]) => {
    const selected = ids.filter((id) => selectedIds.has(id));
    if (selected.length === 0) return;
    try {
      await Promise.all(selected.map((id) => api.updateTask(cogentName, id, { status: "runnable" })));
    } catch (err) {
      console.error("Bulk stop failed:", err);
    }
    setSelectedIds((prev) => { const next = new Set(prev); selected.forEach((id) => next.delete(id)); return next; });
    onRefresh();
  }, [selectedIds, cogentName, onRefresh]);

  const handleBulkRerun = useCallback(async (taskList: Task[]) => {
    const selected = taskList.filter((t) => selectedIds.has(t.id));
    if (selected.length === 0) return;
    try {
      await Promise.all(selected.map((t) => api.createTask(cogentName, {
        name: t.name ?? "copy",
        description: t.description || undefined,
        content: t.content || undefined,
        program_name: t.program_name || undefined,
        priority: t.priority ?? undefined,
        runner: t.runner || undefined,
        clear_context: t.clear_context ?? undefined,
        memory_keys: t.memory_keys?.length ? t.memory_keys : undefined,
        tools: t.tools?.length ? t.tools : undefined,
        resources: t.resources?.length ? t.resources : undefined,
        creator: "dashboard",
        status: "scheduled",
      })));
    } catch (err) {
      console.error("Bulk rerun failed:", err);
    }
    setSelectedIds((prev) => { const next = new Set(prev); selected.forEach((t) => next.delete(t.id)); return next; });
    onRefresh();
  }, [selectedIds, cogentName, onRefresh]);

  const requestBulkDelete = useCallback((ids: string[]) => {
    const selected = ids.filter((id) => selectedIds.has(id));
    if (selected.length === 0) return;
    setBulkConfirm({ action: "delete", ids: selected });
  }, [selectedIds]);

  const executeBulkDelete = useCallback((selected: string[]) => {
    setBulkConfirm(null);
    setPendingDeletes((prev) => { const next = new Set(prev); selected.forEach((id) => next.add(id)); return next; });
    if (expandedId && selected.includes(expandedId)) setExpandedId(null);
    if (undoRef.current) {
      clearTimeout(undoRef.current.timer);
      Promise.all(undoRef.current.taskIds.map((id) => api.deleteTask(cogentName, id))).then(onRefresh);
    }
    const firstTask = tasks.find((t) => t.id === selected[0]);
    const timer = setTimeout(() => {
      Promise.all(selected.map((id) => api.deleteTask(cogentName, id))).then(() => {
        setPendingDeletes((prev) => { const next = new Set(prev); selected.forEach((id) => next.delete(id)); return next; });
        onRefresh();
      });
      setUndoToast(null);
      undoRef.current = null;
    }, 5000);
    const toast: UndoToast = { taskIds: selected, taskName: selected.length === 1 ? (firstTask?.name ?? selected[0]) : `${selected.length} tasks`, timer };
    undoRef.current = toast;
    setUndoToast(toast);
    setSelectedIds((prev) => { const next = new Set(prev); selected.forEach((id) => next.delete(id)); return next; });
  }, [tasks, cogentName, onRefresh, expandedId]);

  const toggleSort = useCallback(() => {
    setSortBy((prev) => {
      const next = prev === "priority" ? "name" : "priority";
      localStorage.setItem("tasks-sort", next);
      return next;
    });
  }, []);

  const sortTasks = useCallback((list: Task[]): Task[] => {
    return [...list].sort((a, b) => {
      if (sortBy === "priority") return (b.priority ?? 0) - (a.priority ?? 0);
      return (a.name ?? "").localeCompare(b.name ?? "");
    });
  }, [sortBy]);

  // Filter tasks: only show tasks with runs in the selected time range (or running/stuck/new)
  const activeWindow = TIME_RANGE_TO_WINDOW[timeRange];
  const filteredTasks = useMemo(() => {
    return tasks.filter((t) => {
      if (t.status === "running" || t.status === "scheduled") return true;
      const c = t.run_counts?.[activeWindow];
      if (c && c.runs > 0) return true;
      if (!t.run_counts || Object.values(t.run_counts).every((v) => v.runs === 0)) return true;
      return false;
    });
  }, [tasks, activeWindow]);

  // Typeahead suggestion sources
  const memoryKeySuggestions = useMemo(
    () => [...new Set(memory.map((m) => m.name).filter(Boolean))].sort(),
    [memory],
  );
  const programSuggestions = useMemo(
    () => programs.map((p) => p.name).sort(),
    [programs],
  );
  // Collect all resource names from existing tasks
  const resourceSuggestions = useMemo(() => {
    const set = new Set<string>();
    for (const t of tasks) {
      if (t.resources) t.resources.forEach((r) => set.add(r));
    }
    return [...set].sort();
  }, [tasks]);
  // Tool names from the tools table for typeahead suggestions
  const toolSuggestions = useMemo(
    () => toolsList.filter((t) => t.enabled).map((t) => t.name).sort(),
    [toolsList],
  );

  // Categorized task lists by status
  const stuckTasks = useMemo(
    () => sortTasks(filteredTasks.filter((t) => isStuck(t))),
    [filteredTasks, sortTasks],
  );
  const runningTasks = useMemo(
    () => sortTasks(filteredTasks.filter((t) => (t.status === "running" || t.status === "scheduled") && !isStuck(t))),
    [filteredTasks, sortTasks],
  );
  const runnableTasks = useMemo(
    () => sortTasks(filteredTasks.filter((t) => t.status === "runnable")),
    [filteredTasks, sortTasks],
  );
  const completedTasks = useMemo(
    () => sortTasks(filteredTasks.filter((t) => t.status === "completed")),
    [filteredTasks, sortTasks],
  );
  const disabledTasks = useMemo(
    () => sortTasks(filteredTasks.filter((t) => t.status === "disabled")),
    [filteredTasks, sortTasks],
  );
  const failedTasks = useMemo(
    () => sortTasks(filteredTasks.filter((t) =>
      t.status !== "running" && t.status !== "scheduled" && t.status !== "runnable" &&
      t.status !== "completed" && t.status !== "disabled" && !isStuck(t),
    )),
    [filteredTasks, sortTasks],
  );

  useEffect(() => {
    if (!expandedId) { setExpandedRuns([]); return; }
    let cancelled = false;
    api.getTaskDetail(cogentName, expandedId).then((detail) => {
      if (!cancelled) setExpandedRuns(detail.runs);
    }).catch(() => {
      if (!cancelled) setExpandedRuns([]);
    });
    return () => { cancelled = true; };
  }, [expandedId, cogentName]);

  const toggleExpand = useCallback((id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  const startEdit = useCallback(async (e: React.MouseEvent, task: Task) => {
    e.stopPropagation();
    setEditingId(task.id);
    setExpandedId(task.id);
    // Start with list data, then fetch detail (which includes content)
    setEditForm({
      name: task.name,
      description: task.description,
      content: task.content,
      program_name: task.program_name,
      status: task.status,
      priority: task.priority,
      runner: task.runner,
      clear_context: task.clear_context,
      memory_keys: task.memory_keys ? [...task.memory_keys] : [],
      tools: task.tools ? [...task.tools] : [],
      resources: task.resources ? [...task.resources] : [],
      creator: task.creator,
      source_event: task.source_event,
    });
    try {
      const detail = await api.getTaskDetail(cogentName, task.id);
      if (detail.task.content != null) {
        setEditForm((prev) => ({ ...prev, content: detail.task.content }));
      }
    } catch { /* use list data as fallback */ }
  }, [cogentName]);

  const cancelEdit = useCallback(() => {
    setEditingId(null);
    setEditForm({});
  }, []);

  const saveEdit = useCallback(async () => {
    if (!editingId) return;
    await api.updateTask(cogentName, editingId, {
      name: editForm.name ?? undefined,
      description: editForm.description ?? undefined,
      content: editForm.content ?? undefined,
      program_name: editForm.program_name ?? undefined,
      status: editForm.status ?? undefined,
      priority: editForm.priority ?? undefined,
      runner: editForm.runner ?? undefined,
      clear_context: editForm.clear_context ?? undefined,
      memory_keys: editForm.memory_keys ?? undefined,
      tools: editForm.tools ?? undefined,
      resources: editForm.resources ?? undefined,
      creator: editForm.creator ?? undefined,
      source_event: editForm.source_event ?? undefined,
    });
    setEditingId(null);
    setEditForm({});
    onRefresh();
  }, [editingId, editForm, cogentName, onRefresh]);

  const handleUndo = useCallback(() => {
    if (!undoRef.current) return;
    clearTimeout(undoRef.current.timer);
    const ids = undoRef.current.taskIds;
    setPendingDeletes((prev) => { const next = new Set(prev); ids.forEach((id) => next.delete(id)); return next; });
    setUndoToast(null);
    undoRef.current = null;
  }, []);

  const handlePrioritySave = useCallback(async (taskId: string) => {
    const val = parseFloat(editingPriorityValue);
    if (!isNaN(val)) {
      await api.updateTask(cogentName, taskId, { priority: val });
      onRefresh();
    }
    setEditingPriorityId(null);
  }, [cogentName, onRefresh, editingPriorityValue]);

  const handleCreate = useCallback(async () => {
    if (!newTask.name?.trim()) return;
    await api.createTask(cogentName, {
      name: newTask.name.trim(),
      description: newTask.description || undefined,
      content: newTask.content || undefined,
      program_name: newTask.program_name || undefined,
      priority: newTask.priority ?? undefined,
      runner: newTask.runner || undefined,
      clear_context: newTask.clear_context ?? undefined,
      memory_keys: newTask.memory_keys?.length ? newTask.memory_keys : undefined,
      tools: newTask.tools?.length ? newTask.tools : undefined,
      resources: newTask.resources?.length ? newTask.resources : undefined,
      creator: newTask.creator || undefined,
      source_event: newTask.source_event || undefined,
    });
    setNewTask({ name: "", description: "", content: "", priority: 0.0, program_name: "do-content" });
    setCreating(false);
    onRefresh();
  }, [newTask, cogentName, onRefresh]);

  const inputStyle: React.CSSProperties = {
    background: "var(--bg-deep)",
    border: "1px solid var(--border-active)",
    borderRadius: "4px",
    padding: "4px 8px",
    color: "var(--text-primary)",
    fontSize: "12px",
    fontFamily: "var(--font-mono)",
    outline: "none",
    width: "100%",
  };

  const btnStyle: React.CSSProperties = {
    padding: "4px 10px",
    fontSize: "11px",
    fontWeight: 600,
    borderRadius: "4px",
    border: "none",
    cursor: "pointer",
  };

  /* ── Edit form (shared between edit and create) ── */
  function renderEditForm(
    form: Partial<Task>,
    setForm: (fn: (prev: Partial<Task>) => Partial<Task>) => void,
    opts: { autoFocus?: boolean },
  ) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <label className="text-[10px] text-[var(--text-muted)] uppercase w-16 shrink-0">Name</label>
          <input
            value={form.name ?? ""}
            onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
            style={inputStyle}
            autoFocus={opts.autoFocus}
            placeholder="my-task-name"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[10px] text-[var(--text-muted)] uppercase w-16 shrink-0">Desc</label>
          <input
            value={form.description ?? ""}
            onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
            style={inputStyle}
            placeholder="Description"
          />
        </div>
        <div className="flex gap-2">
          <label className="text-[10px] text-[var(--text-muted)] uppercase w-16 pt-1 shrink-0">Content</label>
          <textarea
            value={form.content ?? ""}
            onChange={(e) => setForm((p) => ({ ...p, content: e.target.value }))}
            rows={4}
            style={{ ...inputStyle, resize: "vertical" }}
            placeholder="Task content / instructions"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[10px] text-[var(--text-muted)] uppercase w-16 shrink-0">Program</label>
          <input
            value={form.program_name ?? ""}
            onChange={(e) => setForm((p) => ({ ...p, program_name: e.target.value }))}
            style={{ ...inputStyle, width: "200px" }}
            list="program-suggestions"
            placeholder="do-content"
          />
          <datalist id="program-suggestions">
            {programSuggestions.map((p) => <option key={p} value={p} />)}
          </datalist>
          <label className="text-[10px] text-[var(--text-muted)] uppercase shrink-0">Status</label>
          <select
            value={form.status ?? "runnable"}
            onChange={(e) => setForm((p) => ({ ...p, status: e.target.value }))}
            style={{ ...inputStyle, width: "120px" }}
          >
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <label className="text-[10px] text-[var(--text-muted)] uppercase shrink-0">Priority</label>
          <input
            type="number" step="0.01"
            value={form.priority ?? 0}
            onChange={(e) => setForm((p) => ({ ...p, priority: parseFloat(e.target.value) || 0 }))}
            style={{ ...inputStyle, width: "60px" }}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[10px] text-[var(--text-muted)] uppercase w-16 shrink-0">Runner</label>
          <input
            value={form.runner ?? ""}
            onChange={(e) => setForm((p) => ({ ...p, runner: e.target.value || null }))}
            style={{ ...inputStyle, width: "160px" }}
            placeholder="(default)"
          />
          <label className="text-[10px] text-[var(--text-muted)] uppercase shrink-0">Creator</label>
          <input
            value={form.creator ?? ""}
            onChange={(e) => setForm((p) => ({ ...p, creator: e.target.value }))}
            style={{ ...inputStyle, width: "140px" }}
            placeholder="dashboard"
          />
          <label className="text-[10px] text-[var(--text-muted)] uppercase shrink-0 ml-2">Clear ctx</label>
          <input
            type="checkbox"
            checked={form.clear_context ?? false}
            onChange={(e) => setForm((p) => ({ ...p, clear_context: e.target.checked }))}
            className="cursor-pointer"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[10px] text-[var(--text-muted)] uppercase w-16 shrink-0">Src event</label>
          <input
            value={form.source_event ?? ""}
            onChange={(e) => setForm((p) => ({ ...p, source_event: e.target.value || null }))}
            style={inputStyle}
            placeholder="(none)"
          />
        </div>
        <TagListEditor
          label="Memory"
          items={form.memory_keys ?? []}
          onChange={(v) => setForm((p) => ({ ...p, memory_keys: v }))}
          suggestions={memoryKeySuggestions}
          inputStyle={inputStyle}
        />
        <TagListEditor
          label="Tools"
          items={form.tools ?? []}
          onChange={(v) => setForm((p) => ({ ...p, tools: v }))}
          suggestions={toolSuggestions}
          inputStyle={inputStyle}
        />
        <TagListEditor
          label="Resources"
          items={form.resources ?? []}
          onChange={(v) => setForm((p) => ({ ...p, resources: v }))}
          suggestions={resourceSuggestions}
          inputStyle={inputStyle}
        />
      </div>
    );
  }

  function renderTaskRow(task: Task) {
    if (pendingDeletes.has(task.id)) return null;

    const isExpanded = expandedId === task.id;
    const isEditing = editingId === task.id;
    const isSelected = selectedIds.has(task.id);
    const shortName = task.name ?? "--";

    return (
      <div key={task.id}>
        <div
          className="flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors"
          style={{
            background: isSelected ? "var(--accent-glow)" : isExpanded ? "var(--bg-hover)" : "var(--bg-surface)",
            borderBottom: "1px solid var(--border)",
          }}
          onClick={() => toggleSelect(task.id)}
          onDoubleClick={() => toggleExpand(task.id)}
          onMouseEnter={(e) => {
            if (!isExpanded && !isSelected) e.currentTarget.style.background = "var(--bg-hover)";
          }}
          onMouseLeave={(e) => {
            if (!isExpanded && !isSelected) e.currentTarget.style.background = "var(--bg-surface)";
            if (isSelected) e.currentTarget.style.background = "var(--accent-glow)";
          }}
        >
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => toggleSelect(task.id)}
            onClick={(e) => e.stopPropagation()}
            className="cursor-pointer shrink-0 opacity-50 hover:opacity-80 accent-[var(--accent)]"
          />
          {editingPriorityId === task.id ? (
            <input
              type="text"
              inputMode="decimal"
              autoFocus
              value={editingPriorityValue}
              onChange={(e) => setEditingPriorityValue(e.target.value)}
              onBlur={() => handlePrioritySave(task.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handlePrioritySave(task.id);
                if (e.key === "Escape") setEditingPriorityId(null);
              }}
              onClick={(e) => e.stopPropagation()}
              className="font-mono text-[11px] text-left"
              style={{
                width: "52px",
                padding: "1px 4px",
                background: "var(--bg-base)",
                border: "1px solid var(--accent)",
                borderRadius: "4px",
                color: "var(--text-primary)",
                outline: "none",
              }}
            />
          ) : (
            <span
              className="font-mono text-[11px] text-[var(--text-muted)] cursor-pointer hover:text-[var(--text-secondary)] shrink-0 inline-block text-left"
              style={{
                width: "52px",
                padding: "1px 4px",
                border: "1px solid var(--border)",
                borderRadius: "4px",
              }}
              title="Click to edit priority"
              onClick={(e) => {
                e.stopPropagation();
                setEditingPriorityId(task.id);
                setEditingPriorityValue((task.priority ?? 0).toFixed(2));
              }}
            >
              {(task.priority ?? 0).toFixed(2)}
            </span>
          )}
          {task.recurrent && <span className="text-[var(--info)] text-[11px]" title="Recurrent">↻</span>}
          <span className="font-mono text-[12px] text-[var(--text-primary)] truncate min-w-0 flex-1" title={task.name ?? ""}>
            {shortName}
          </span>
          {/* Run counts as separated blocks — only windows with runs */}
          {task.run_counts && (() => {
            const entries = RUN_COUNT_WINDOWS
              .map((w) => ({ w, c: task.run_counts![w] }))
              .filter(({ c }) => c && c.runs > 0);
            if (entries.length === 0) return null;
            return (
              <span className="flex gap-1 text-[10px] font-mono shrink-0">
                {entries.map(({ w, c }) => (
                  <span
                    key={w}
                    className="flex items-center gap-1 px-1.5 py-0.5 rounded"
                    style={{
                      background: "var(--bg-hover)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <span className="text-[var(--text-muted)]">{w}</span>
                    <span className="text-[#22c55e]">{c.runs}</span>
                    {c.failed > 0 && <span className="text-[var(--error)]">{c.failed}</span>}
                  </span>
                ))}
              </span>
            );
          })()}
          {/* Last ran / time stuck */}
          {isStuck(task) ? (
            <span className="text-[10px] text-[var(--warning)] shrink-0 whitespace-nowrap" title="Time stuck">
              stuck {fmtTimestamp(task.updated_at)}
            </span>
          ) : task.last_run_at ? (
            <span className="text-[10px] text-[var(--text-muted)] shrink-0 whitespace-nowrap" title="Last ran">
              ran {fmtTimestamp(task.last_run_at)}
            </span>
          ) : (
            <span className="text-[10px] text-[var(--text-muted)] shrink-0 whitespace-nowrap">{fmtTimestamp(task.updated_at)}</span>
          )}

          <button
            onClick={(e) => startEdit(e, task)}
            className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--accent)] text-[11px]"
            title="Edit"
          >
            ✎
          </button>
        </div>

        {/* Expanded detail */}
        {isExpanded && (
          <div
            className="px-4 py-3 space-y-3"
            style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--border)" }}
          >
            {/* Edit form */}
            {isEditing && (
              <div className="pb-3 space-y-2" style={{ borderBottom: "1px solid var(--border)" }}>
                {renderEditForm(editForm, setEditForm, { autoFocus: true })}
                <div className="flex justify-end gap-2 pt-1">
                  <button onClick={saveEdit} style={{ ...btnStyle, background: "var(--accent)", color: "var(--bg-deep)" }}>
                    Save
                  </button>
                  <button onClick={cancelEdit} style={{ ...btnStyle, background: "var(--bg-surface)", color: "var(--text-secondary)" }}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Task details (read-only) */}
            {!isEditing && (
              <div className="space-y-2">
                {/* Top bar: key fields inline */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
                  <span className="font-mono text-[var(--text-secondary)]" title="Full name">{task.name}</span>
                  <span className="font-mono px-1.5 py-0.5 rounded text-[var(--accent)]" style={{ background: "var(--accent-glow)" }}>{task.program_name ?? "--"}</span>
                  {task.runner && <span className="text-[var(--text-muted)]">runner:<span className="text-[var(--text-secondary)] ml-0.5">{task.runner}</span></span>}
                  <span className="text-[var(--text-muted)]">creator:<span className="text-[var(--text-secondary)] ml-0.5">{task.creator ?? "--"}</span></span>
                  {task.recurrent && <span className="text-[var(--info)]">↻ recurrent</span>}
                  {task.clear_context && <span className="text-[var(--warning)]">clear-ctx</span>}
                  {task.parent_task_id && <span className="text-[var(--text-muted)]">parent:<span className="font-mono text-[var(--text-secondary)] ml-0.5">{task.parent_task_id.slice(0, 8)}</span></span>}
                  {task.source_event && <span className="text-[var(--text-muted)]">event:<span className="text-[var(--text-secondary)] ml-0.5">{task.source_event}</span></span>}
                </div>

                {/* Tags row: memory, tools, resources */}
                {((task.memory_keys?.length ?? 0) > 0 || (task.tools?.length ?? 0) > 0 || (task.resources?.length ?? 0) > 0) && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px]">
                    {task.memory_keys && task.memory_keys.length > 0 && (
                      <span className="text-[var(--text-muted)]">mem: <span className="font-mono text-[var(--text-secondary)]">{task.memory_keys.join(", ")}</span></span>
                    )}
                    {task.tools && task.tools.length > 0 && (
                      <span className="text-[var(--text-muted)]">tools: <span className="font-mono text-[var(--text-secondary)]">{task.tools.join(", ")}</span></span>
                    )}
                    {task.resources && task.resources.length > 0 && (
                      <span className="text-[var(--text-muted)]">resources: <span className="font-mono text-[var(--text-secondary)]">{task.resources.join(", ")}</span></span>
                    )}
                  </div>
                )}

                {/* Stats row: timestamps, run counts, last run */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] py-1" style={{ borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
                  <span className="text-[var(--text-muted)]">created <span className="text-[var(--text-secondary)]">{fmtTimestamp(task.created_at)}</span></span>
                  <span className="text-[var(--text-muted)]">updated <span className="text-[var(--text-secondary)]">{fmtTimestamp(task.updated_at)}</span></span>
                  {task.completed_at && <span className="text-[var(--text-muted)]">completed <span className="text-[var(--text-secondary)]">{fmtTimestamp(task.completed_at)}</span></span>}
                  {task.last_run_status && (
                    <span className="text-[var(--text-muted)]">last run: <Badge variant={STATUS_VARIANT[task.last_run_status] ?? "neutral"}>{task.last_run_status}</Badge>{task.last_run_at && <span className="ml-1 text-[var(--text-secondary)]">{fmtTimestamp(task.last_run_at)}</span>}</span>
                  )}
                  {task.last_run_error && <span className="text-red-400 truncate max-w-[300px]" title={task.last_run_error}>{task.last_run_error}</span>}
                  {task.run_counts && (
                    <span className="flex items-center gap-1.5 font-mono">
                      <span className="text-[var(--text-muted)]">runs:</span>
                      {RUN_COUNT_WINDOWS.map((w) => {
                        const c = task.run_counts![w];
                        const runs = c?.runs ?? 0;
                        const failed = c?.failed ?? 0;
                        if (runs === 0) return null;
                        return (
                          <span key={w} className="text-[var(--text-muted)]">
                            {w}:<span className="text-[#22c55e]">{runs}</span>
                            {failed > 0 && <span className="text-[var(--error)] ml-0.5">{failed}</span>}
                          </span>
                        );
                      })}
                    </span>
                  )}
                </div>

                {/* Limits / metadata inline if present */}
                {((task.limits && Object.keys(task.limits).length > 0) || (task.metadata && Object.keys(task.metadata).length > 0)) && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px]">
                    {task.limits && Object.keys(task.limits).length > 0 && (
                      <span className="text-[var(--text-muted)]">limits: <span className="font-mono text-[var(--text-secondary)]">{JSON.stringify(task.limits)}</span></span>
                    )}
                    {task.metadata && Object.keys(task.metadata).length > 0 && (
                      <span className="text-[var(--text-muted)]">meta: <span className="font-mono text-[var(--text-secondary)]">{JSON.stringify(task.metadata)}</span></span>
                    )}
                  </div>
                )}

                {/* Description */}
                {task.description && (
                  <div className="text-[11px] text-[var(--text-secondary)]">{task.description}</div>
                )}

                {/* Content — main area */}
                {task.content && (
                  <pre
                    className="text-[11px] font-mono text-[var(--text-primary)] whitespace-pre-wrap break-all p-2 rounded overflow-auto"
                    style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", maxHeight: "300px" }}
                  >{task.content}</pre>
                )}
              </div>
            )}

            {/* Recent Runs */}
            {expandedRuns.length > 0 && (
              <div>
                <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium mb-1">
                  <span>Runs ({expandedRuns.length})</span>
                  {task.runner && <span className="normal-case text-[var(--text-secondary)]">{task.runner}</span>}
                </div>
                <div className="space-y-0.5">
                  {expandedRuns.map((run) => {
                    const totalTokens = (run.tokens_input ?? 0) + (run.tokens_output ?? 0);
                    const statusChar = run.status?.[0]?.toUpperCase() ?? "?";
                    return (
                      <div
                        key={run.id}
                        className="flex items-center gap-2 px-2 py-0.5 rounded text-[10px]"
                        style={{ background: "var(--bg-surface)" }}
                      >
                        <Badge variant={STATUS_VARIANT[run.status ?? ""] ?? "neutral"}>
                          <span title={run.status ?? "unknown"}>{statusChar}</span>
                        </Badge>
                        <span className="font-mono text-[var(--text-secondary)]">{run.program_name}</span>
                        <span className="text-[var(--text-muted)]">{fmtDuration(run.duration_ms)}</span>
                        {totalTokens > 0 && (
                          <span className="text-[var(--text-muted)]" title={`in: ${run.tokens_input ?? 0} out: ${run.tokens_output ?? 0}`}>
                            {fmtTokens(totalTokens)} tok
                          </span>
                        )}
                        {run.cost_usd > 0 && (
                          <span className="text-[var(--text-muted)]">${run.cost_usd.toFixed(4)}</span>
                        )}
                        <div className="flex-1" />
                        <span className="text-[var(--text-muted)]">{fmtTimestamp(run.started_at)}</span>
                        {run.error && <span className="text-red-400 truncate max-w-[200px]" title={run.error}>{run.error}</span>}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  function renderSection(
    title: string,
    items: Task[],
    color: string,
    borderColor: string,
    bgColor: string,
    actions: Array<{ label: string; icon: string; onClick: () => void; hoverColor: string }>,
    icon?: React.ReactNode,
  ) {
    if (items.length === 0) return null;
    const ids = items.filter((t) => !pendingDeletes.has(t.id)).map((t) => t.id);
    const allSelected = ids.length > 0 && ids.every((id) => selectedIds.has(id));
    const someSelected = ids.some((id) => selectedIds.has(id));
    const selCount = ids.filter((id) => selectedIds.has(id)).length;
    return (
      <div
        className="mb-4 rounded-md overflow-hidden"
        style={{ border: `1px solid ${borderColor}` }}
      >
        <div
          className="flex items-center gap-2 px-3 py-1.5"
          style={{ background: bgColor, borderBottom: `1px solid ${borderColor}` }}
        >
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }}
            onChange={() => toggleSelectAll(ids)}
            className="cursor-pointer shrink-0 opacity-50 hover:opacity-80 accent-[var(--accent)]"
          />
          {icon}
          <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color }}>
            {title}
          </span>
          <span className="text-[10px]" style={{ color: borderColor }}>
            ({items.length})
          </span>
          <div className="flex-1" />
          {someSelected && (
            <span className="text-[10px] text-[var(--text-muted)] mr-1">{selCount} selected</span>
          )}
          {actions.map((action) => (
            <button
              key={action.label}
              onClick={action.onClick}
              disabled={!someSelected}
              className="border-0 bg-transparent cursor-pointer text-[11px] font-medium px-2 py-0.5 rounded transition-colors"
              style={{
                color: someSelected ? action.hoverColor : "var(--text-muted)",
                opacity: someSelected ? 1 : 0.4,
                background: someSelected ? "rgba(255,255,255,0.05)" : "transparent",
              }}
              title={`${action.label} selected`}
            >
              {action.icon} {action.label}
            </button>
          ))}
        </div>
        {items.filter((t) => !pendingDeletes.has(t.id)).map((task) => renderTaskRow(task))}
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-[var(--text-muted)] text-xs">
            {filteredTasks.length}/{tasks.length} task{tasks.length !== 1 ? "s" : ""}
          </span>
          <button
            onClick={toggleSort}
            className="border-0 cursor-pointer rounded px-2 py-0.5 text-[10px] font-mono transition-colors"
            style={{
              background: "var(--bg-hover)",
              color: "var(--text-secondary)",
            }}
            title="Toggle sort order"
          >
            sort: {sortBy}
          </button>
        </div>
        <button
          onClick={() => setCreating(!creating)}
          style={{
            ...btnStyle,
            background: creating ? "var(--bg-hover)" : "var(--accent)",
            color: creating ? "var(--text-secondary)" : "var(--bg-deep)",
          }}
        >
          {creating ? "Cancel" : "+ New Task"}
        </button>
      </div>

      {/* Create form */}
      {creating && (
        <div
          className="mb-3 p-3 rounded-md space-y-2"
          style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
        >
          {renderEditForm(
            newTask,
            (fn) => setNewTask((prev) => fn(prev)),
            { autoFocus: true },
          )}
          <div className="flex justify-end pt-1">
            <button
              onClick={handleCreate}
              style={{ ...btnStyle, background: "var(--accent)", color: "var(--bg-deep)" }}
            >
              Create
            </button>
          </div>
        </div>
      )}

      {/* Stuck */}
      {renderSection(
        "Stuck",
        stuckTasks,
        "#f59e0b",
        "#78350f",
        "rgba(245, 158, 11, 0.08)",
        [
          { label: "Stop", icon: "■", onClick: () => handleBulkStop(stuckTasks.map((t) => t.id)), hoverColor: "var(--warning)" },
          { label: "Re-run", icon: "⧉▶", onClick: () => handleBulkRerun(stuckTasks), hoverColor: "var(--success)" },
        ],
        <span className="inline-block w-[6px] h-[6px] rounded-full" style={{ background: "#f59e0b" }} />,
      )}

      {/* Currently Running */}
      {renderSection(
        "Currently Running",
        runningTasks,
        "var(--accent)",
        "var(--accent-dim)",
        "var(--accent-glow)",
        [
          { label: "Stop", icon: "■", onClick: () => handleBulkStop(runningTasks.map((t) => t.id)), hoverColor: "var(--warning)" },
        ],
        <span
          className="inline-block w-[6px] h-[6px] rounded-full"
          style={{ background: "var(--accent)", animation: "pulse-dot 1.5s ease-in-out infinite" }}
        />,
      )}

      {/* Runnable */}
      {renderSection(
        "Runnable",
        runnableTasks,
        "var(--info)",
        "var(--border)",
        "var(--bg-surface)",
        [
          { label: "Run", icon: "▶", onClick: () => handleBulkRun(runnableTasks.map((t) => t.id)), hoverColor: "var(--success)" },
          { label: "Delete", icon: "✕", onClick: () => requestBulkDelete(runnableTasks.map((t) => t.id)), hoverColor: "var(--error)" },
        ],
      )}

      {/* Completed */}
      {renderSection(
        "Completed",
        completedTasks,
        "#22c55e",
        "#14532d",
        "rgba(34, 197, 94, 0.06)",
        [
          { label: "Re-run", icon: "⧉▶", onClick: () => handleBulkRerun(completedTasks), hoverColor: "var(--success)" },
          { label: "Delete", icon: "✕", onClick: () => requestBulkDelete(completedTasks.map((t) => t.id)), hoverColor: "var(--error)" },
        ],
      )}

      {/* Failed */}
      {renderSection(
        "Failed",
        failedTasks,
        "#ef4444",
        "#7f1d1d",
        "rgba(239, 68, 68, 0.06)",
        [
          { label: "Re-run", icon: "⧉▶", onClick: () => handleBulkRerun(failedTasks), hoverColor: "var(--success)" },
          { label: "Delete", icon: "✕", onClick: () => requestBulkDelete(failedTasks.map((t) => t.id)), hoverColor: "var(--error)" },
        ],
        <span className="inline-block w-[6px] h-[6px] rounded-full" style={{ background: "#ef4444" }} />,
      )}

      {/* Disabled */}
      {renderSection(
        "Disabled",
        disabledTasks,
        "var(--text-muted)",
        "var(--border)",
        "var(--bg-surface)",
        [
          { label: "Run", icon: "▶", onClick: () => handleBulkRun(disabledTasks.map((t) => t.id)), hoverColor: "var(--success)" },
          { label: "Delete", icon: "✕", onClick: () => requestBulkDelete(disabledTasks.map((t) => t.id)), hoverColor: "var(--error)" },
        ],
      )}

      {tasks.length === 0 && !creating && (
        <div className="text-[var(--text-muted)] text-xs py-8 text-center">No tasks</div>
      )}

      {/* Bulk delete confirmation */}
      {bulkConfirm && (
        <div
          className="fixed inset-0 flex items-center justify-center z-50"
          style={{ background: "rgba(0,0,0,0.5)" }}
          onClick={() => setBulkConfirm(null)}
        >
          <div
            className="rounded-lg p-4 shadow-xl max-w-sm"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-[13px] text-[var(--text-primary)] mb-3">
              Delete <span className="font-semibold">{bulkConfirm.ids.length}</span> task{bulkConfirm.ids.length !== 1 ? "s" : ""}?
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setBulkConfirm(null)}
                className="px-3 py-1.5 rounded text-[11px] font-semibold border-0 cursor-pointer"
                style={{ background: "var(--bg-surface)", color: "var(--text-secondary)" }}
              >
                Cancel
              </button>
              <button
                onClick={() => executeBulkDelete(bulkConfirm.ids)}
                className="px-3 py-1.5 rounded text-[11px] font-semibold border-0 cursor-pointer"
                style={{ background: "var(--error)", color: "white" }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Undo toast */}
      {undoToast && (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-3 px-4 py-2.5 rounded-lg shadow-lg z-50"
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            animation: "fade-in 0.2s ease-out",
          }}
        >
          <span className="text-[12px] text-[var(--text-secondary)]">
            Deleted <span className="font-mono font-medium text-[var(--text-primary)]">{undoToast.taskName}</span>
          </span>
          <button
            onClick={handleUndo}
            className="border-0 cursor-pointer font-semibold text-[12px] rounded px-2 py-0.5"
            style={{ background: "var(--accent)", color: "var(--bg-deep)" }}
          >
            Undo
          </button>
        </div>
      )}
    </div>
  );
}
