"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import type { Task, MemoryItem, Program } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import * as api from "@/lib/api";
import { fmtRelative } from "@/lib/format";

interface TasksPanelProps {
  tasks: Task[];
  cogentName: string;
  onRefresh: () => void;
  memory: MemoryItem[];
  programs: Program[];
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "neutral" | "accent";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  runnable: "info",
  running: "accent",
  completed: "success",
  disabled: "neutral",
  failed: "error",
  timeout: "warning",
};

const STATUSES = ["runnable", "running", "completed", "disabled"];

const STUCK_THRESHOLD_MS = 10 * 60 * 1000;
const RECENT_THRESHOLD_MS = 60 * 60 * 1000;

function getPrefix(name: string): string {
  const lastSlash = name.lastIndexOf("/");
  return lastSlash > 0 ? name.substring(0, lastSlash) : "";
}

function isRecent(dateStr: string | null): boolean {
  if (!dateStr) return false;
  return Date.now() - new Date(dateStr).getTime() < RECENT_THRESHOLD_MS;
}

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
  error: string | null;
}

interface UndoToast {
  taskId: string;
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

export function TasksPanel({ tasks, cogentName, onRefresh, memory, programs }: TasksPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedRuns, setExpandedRuns] = useState<TaskRun[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<Task>>({});
  const [creating, setCreating] = useState(false);
  const [newTask, setNewTask] = useState<Partial<Task>>({ name: "", description: "", content: "", priority: 0.0, program_name: "do-content" });
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [editingPriorityId, setEditingPriorityId] = useState<string | null>(null);
  const [editingPriorityValue, setEditingPriorityValue] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [undoToast, setUndoToast] = useState<UndoToast | null>(null);
  const [pendingDeletes, setPendingDeletes] = useState<Set<string>>(new Set());
  const undoRef = useRef<UndoToast | null>(null);

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
  // Collect all tool names from existing tasks + programs
  const toolSuggestions = useMemo(() => {
    const set = new Set<string>();
    for (const t of tasks) {
      if (t.tools) t.tools.forEach((tool) => set.add(tool));
    }
    for (const p of programs) {
      // programs don't have tools exposed in dashboard model yet, but just in case
    }
    return [...set].sort();
  }, [tasks, programs]);

  // Categorized task lists
  const runningTasks = useMemo(
    () => tasks.filter((t) => t.status === "running" && !isStuck(t)),
    [tasks],
  );
  const stuckTasks = useMemo(
    () => tasks.filter((t) => isStuck(t)),
    [tasks],
  );
  const recentlyFinished = useMemo(
    () => tasks.filter((t) => t.status === "completed" && isRecent(t.completed_at)),
    [tasks],
  );
  const recentlyFailed = useMemo(
    () => tasks.filter((t) =>
      (t.last_run_status === "failed" || t.last_run_status === "timeout") &&
      isRecent(t.last_run_at) &&
      t.status !== "running",
    ),
    [tasks],
  );

  const highlightIds = useMemo(() => {
    const ids = new Set<string>();
    for (const t of [...runningTasks, ...stuckTasks, ...recentlyFinished, ...recentlyFailed]) {
      ids.add(t.id);
    }
    return ids;
  }, [runningTasks, stuckTasks, recentlyFinished, recentlyFailed]);

  const grouped = useMemo(() => {
    const remaining = tasks.filter((t) => !highlightIds.has(t.id) && !pendingDeletes.has(t.id));
    const groups: Record<string, Task[]> = {};
    for (const t of remaining) {
      const prefix = getPrefix(t.name || "");
      const key = prefix || "(ungrouped)";
      if (!groups[key]) groups[key] = [];
      groups[key].push(t);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [tasks, highlightIds, pendingDeletes]);

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

  const toggleGroup = useCallback((key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const startEdit = useCallback((e: React.MouseEvent, task: Task) => {
    e.stopPropagation();
    setEditingId(task.id);
    setExpandedId(task.id);
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
  }, []);

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

  const requestDelete = useCallback((e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    setConfirmDeleteId((prev) => (prev === taskId ? null : taskId));
  }, []);

  const confirmDelete = useCallback((e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    setConfirmDeleteId(null);
    const task = tasks.find((t) => t.id === taskId);
    const taskName = task?.name ?? taskId;
    setPendingDeletes((prev) => new Set(prev).add(taskId));
    if (expandedId === taskId) setExpandedId(null);
    if (undoRef.current) {
      clearTimeout(undoRef.current.timer);
      api.deleteTask(cogentName, undoRef.current.taskId).then(onRefresh);
    }
    const timer = setTimeout(() => {
      api.deleteTask(cogentName, taskId).then(() => {
        setPendingDeletes((prev) => { const next = new Set(prev); next.delete(taskId); return next; });
        onRefresh();
      });
      setUndoToast(null);
      undoRef.current = null;
    }, 5000);
    const toast: UndoToast = { taskId, taskName, timer };
    undoRef.current = toast;
    setUndoToast(toast);
  }, [tasks, cogentName, onRefresh, expandedId]);

  const handleUndo = useCallback(() => {
    if (!undoRef.current) return;
    clearTimeout(undoRef.current.timer);
    const taskId = undoRef.current.taskId;
    setPendingDeletes((prev) => { const next = new Set(prev); next.delete(taskId); return next; });
    setUndoToast(null);
    undoRef.current = null;
  }, []);

  const cancelConfirm = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmDeleteId(null);
  }, []);

  const handleRunTask = useCallback(async (e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    await api.updateTask(cogentName, taskId, { status: "running" });
    onRefresh();
  }, [cogentName, onRefresh]);

  const handleStopTask = useCallback(async (e: React.MouseEvent, taskId: string) => {
    e.stopPropagation();
    await api.updateTask(cogentName, taskId, { status: "runnable" });
    onRefresh();
  }, [cogentName, onRefresh]);

  const handlePrioritySave = useCallback(async (taskId: string) => {
    const val = parseFloat(editingPriorityValue);
    if (!isNaN(val)) {
      await api.updateTask(cogentName, taskId, { priority: val });
      onRefresh();
    }
    setEditingPriorityId(null);
  }, [cogentName, onRefresh, editingPriorityValue]);

  const handleRunCopy = useCallback(async (e: React.MouseEvent, task: Task) => {
    e.stopPropagation();
    await api.createTask(cogentName, {
      name: task.name ?? "copy",
      description: task.description || undefined,
      content: task.content || undefined,
      program_name: task.program_name || undefined,
      priority: task.priority ?? undefined,
      runner: task.runner || undefined,
      clear_context: task.clear_context ?? undefined,
      memory_keys: task.memory_keys?.length ? task.memory_keys : undefined,
      tools: task.tools?.length ? task.tools : undefined,
      resources: task.resources?.length ? task.resources : undefined,
      creator: "dashboard",
      status: "running",
    });
    onRefresh();
  }, [cogentName, onRefresh]);

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
            placeholder="/path/to/task-name"
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

  function renderTaskRow(task: Task, showFullName: boolean) {
    if (pendingDeletes.has(task.id)) return null;

    const isExpanded = expandedId === task.id;
    const isEditing = editingId === task.id;
    const isConfirming = confirmDeleteId === task.id;
    const shortName = showFullName
      ? (task.name ?? "--")
      : task.name
        ? task.name.substring(getPrefix(task.name).length).replace(/^\//, "")
        : "--";

    return (
      <div key={task.id}>
        <div
          className="flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors"
          style={{
            background: isExpanded ? "var(--bg-hover)" : "var(--bg-surface)",
            borderBottom: "1px solid var(--border)",
          }}
          onClick={() => toggleExpand(task.id)}
          onMouseEnter={(e) => {
            if (!isExpanded) e.currentTarget.style.background = "var(--bg-hover)";
          }}
          onMouseLeave={(e) => {
            if (!isExpanded) e.currentTarget.style.background = "var(--bg-surface)";
          }}
        >
          <Badge variant={STATUS_VARIANT[task.status ?? ""] ?? "neutral"}>
            {task.status ?? "?"}{task.recurrent ? " ↻" : ""}
          </Badge>
          <span className="font-mono text-[12px] text-[var(--text-primary)]" title={task.name ?? ""}>
            {shortName}
          </span>
          {task.description && (
            <span className="text-[11px] text-[var(--text-muted)] truncate max-w-[300px]">
              {task.description}
            </span>
          )}
          {task.last_run_status && (task.last_run_status === "failed" || task.last_run_status === "timeout") && (
            <Badge variant="error">{task.last_run_status}</Badge>
          )}
          <div className="flex-1" />
          {/* Run counts */}
          {task.run_counts && (
            <span className="flex gap-1.5 text-[10px] font-mono text-[var(--text-muted)]">
              {["1m", "5m", "1h", "24h", "7d"].map((w) => (
                <span key={w} title={`Runs in ${w}`}>
                  <span className="text-[var(--text-secondary)]">{task.run_counts![w] ?? 0}</span>
                </span>
              ))}
            </span>
          )}
          {editingPriorityId === task.id ? (
            <input
              type="number"
              step="0.01"
              autoFocus
              value={editingPriorityValue}
              onChange={(e) => setEditingPriorityValue(e.target.value)}
              onBlur={() => handlePrioritySave(task.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handlePrioritySave(task.id);
                if (e.key === "Escape") setEditingPriorityId(null);
              }}
              onClick={(e) => e.stopPropagation()}
              className="font-mono text-[11px] text-center"
              style={{
                width: "48px",
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
              className="font-mono text-[11px] text-[var(--text-muted)] cursor-pointer hover:text-[var(--text-secondary)]"
              style={{
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
          {/* Last ran / time stuck */}
          {isStuck(task) ? (
            <span className="text-[10px] text-[var(--warning)]" title="Time stuck">
              stuck {fmtRelative(task.updated_at)}
            </span>
          ) : task.last_run_at ? (
            <span className="text-[10px] text-[var(--text-muted)]" title="Last ran">
              ran {fmtRelative(task.last_run_at)}
            </span>
          ) : (
            <span className="text-[10px] text-[var(--text-muted)]">{fmtRelative(task.updated_at)}</span>
          )}

          {isConfirming ? (
            <span className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <span className="text-[10px] text-[var(--error)]">Delete?</span>
              <button
                onClick={(e) => confirmDelete(e, task.id)}
                className="border-0 bg-transparent cursor-pointer text-[var(--error)] font-semibold text-[11px]"
              >
                Yes
              </button>
              <button
                onClick={cancelConfirm}
                className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] text-[11px]"
              >
                No
              </button>
            </span>
          ) : (
            <>
              {task.status === "running" ? (
                <button
                  onClick={(e) => handleStopTask(e, task.id)}
                  className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--warning)] text-[11px]"
                  title="Stop"
                >
                  ■
                </button>
              ) : task.status === "completed" ? (
                <button
                  onClick={(e) => handleRunCopy(e, task)}
                  className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--success)] text-[11px]"
                  title="Run Copy"
                >
                  ⧉▶
                </button>
              ) : (
                <button
                  onClick={(e) => handleRunTask(e, task.id)}
                  className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--success)] text-[11px]"
                  title="Run"
                >
                  ▶
                </button>
              )}
              <button
                onClick={(e) => startEdit(e, task)}
                className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--accent)] text-[11px]"
                title="Edit"
              >
                ✎
              </button>
              <button
                onClick={(e) => requestDelete(e, task.id)}
                className="border-0 bg-transparent cursor-pointer text-[var(--text-muted)] hover:text-[var(--error)] text-[11px]"
                title="Delete"
              >
                ✕
              </button>
            </>
          )}
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
              <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[11px]">
                <span className="text-[var(--text-muted)]">Full name</span>
                <span className="font-mono text-[var(--text-secondary)]">{task.name}</span>
                {task.description && (
                  <>
                    <span className="text-[var(--text-muted)]">Description</span>
                    <span className="text-[var(--text-secondary)]">{task.description}</span>
                  </>
                )}
                <span className="text-[var(--text-muted)]">Status</span>
                <span className="text-[var(--text-secondary)]">{task.status ?? "--"}</span>
                <span className="text-[var(--text-muted)]">Priority</span>
                <span className="text-[var(--text-secondary)]">{(task.priority ?? 0).toFixed(2)}</span>
                <span className="text-[var(--text-muted)]">Program</span>
                <span className="font-mono text-[var(--text-secondary)]">{task.program_name ?? "--"}</span>
                {task.runner && (
                  <>
                    <span className="text-[var(--text-muted)]">Runner</span>
                    <span className="font-mono text-[var(--text-secondary)]">{task.runner}</span>
                  </>
                )}
                <span className="text-[var(--text-muted)]">Creator</span>
                <span className="text-[var(--text-secondary)]">{task.creator ?? "--"}</span>
                {task.parent_task_id && (
                  <>
                    <span className="text-[var(--text-muted)]">Parent task</span>
                    <span className="font-mono text-[var(--text-secondary)]">{task.parent_task_id}</span>
                  </>
                )}
                {task.source_event && (
                  <>
                    <span className="text-[var(--text-muted)]">Source event</span>
                    <span className="text-[var(--text-secondary)]">{task.source_event}</span>
                  </>
                )}
                <span className="text-[var(--text-muted)]">Clear context</span>
                <span className="text-[var(--text-secondary)]">{task.clear_context ? "yes" : "no"}</span>
                {task.content && (
                  <>
                    <span className="text-[var(--text-muted)]">Content</span>
                    <span className="text-[var(--text-secondary)] whitespace-pre-wrap break-all">{task.content}</span>
                  </>
                )}
                {task.memory_keys && task.memory_keys.length > 0 && (
                  <>
                    <span className="text-[var(--text-muted)]">Memory keys</span>
                    <span className="font-mono text-[var(--text-secondary)]">{task.memory_keys.join(", ")}</span>
                  </>
                )}
                {task.tools && task.tools.length > 0 && (
                  <>
                    <span className="text-[var(--text-muted)]">Tools</span>
                    <span className="font-mono text-[var(--text-secondary)]">{task.tools.join(", ")}</span>
                  </>
                )}
                {task.resources && task.resources.length > 0 && (
                  <>
                    <span className="text-[var(--text-muted)]">Resources</span>
                    <span className="font-mono text-[var(--text-secondary)]">{task.resources.join(", ")}</span>
                  </>
                )}
                {task.limits && Object.keys(task.limits).length > 0 && (
                  <>
                    <span className="text-[var(--text-muted)]">Limits</span>
                    <span className="font-mono text-[var(--text-secondary)]">{JSON.stringify(task.limits)}</span>
                  </>
                )}
                {task.metadata && Object.keys(task.metadata).length > 0 && (
                  <>
                    <span className="text-[var(--text-muted)]">Metadata</span>
                    <span className="font-mono text-[var(--text-secondary)] whitespace-pre-wrap break-all">{JSON.stringify(task.metadata, null, 2)}</span>
                  </>
                )}
                {task.last_run_status && (
                  <>
                    <span className="text-[var(--text-muted)]">Last run</span>
                    <span className="text-[var(--text-secondary)]">
                      <Badge variant={STATUS_VARIANT[task.last_run_status] ?? "neutral"}>{task.last_run_status}</Badge>
                      {task.last_run_at && <span className="ml-2">{fmtRelative(task.last_run_at)}</span>}
                    </span>
                  </>
                )}
                {task.last_run_error && (
                  <>
                    <span className="text-[var(--text-muted)]">Last error</span>
                    <span className="text-red-400 whitespace-pre-wrap break-all">{task.last_run_error}</span>
                  </>
                )}
                <span className="text-[var(--text-muted)]">Created</span>
                <span className="text-[var(--text-secondary)]">{fmtRelative(task.created_at)}</span>
                <span className="text-[var(--text-muted)]">Updated</span>
                <span className="text-[var(--text-secondary)]">{fmtRelative(task.updated_at)}</span>
                {task.completed_at && (
                  <>
                    <span className="text-[var(--text-muted)]">Completed</span>
                    <span className="text-[var(--text-secondary)]">{fmtRelative(task.completed_at)}</span>
                  </>
                )}
              </div>
            )}

            {/* Recent Runs */}
            <div>
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium mb-1.5">
                Recent Runs
              </div>
              {expandedRuns.length === 0 ? (
                <div className="text-[11px] text-[var(--text-muted)] italic">No runs yet</div>
              ) : (
                <div className="space-y-1">
                  {expandedRuns.map((run) => (
                    <div
                      key={run.id}
                      className="flex items-center gap-2 px-2 py-1 rounded"
                      style={{ background: "var(--bg-surface)" }}
                    >
                      <Badge variant={STATUS_VARIANT[run.status ?? ""] ?? "neutral"}>
                        {run.status ?? "?"}
                      </Badge>
                      <span className="font-mono text-[11px] text-[var(--text-secondary)]">
                        {run.program_name}
                      </span>
                      {run.duration_ms != null && (
                        <span className="text-[10px] text-[var(--text-muted)]">
                          {run.duration_ms}ms
                        </span>
                      )}
                      <div className="flex-1" />
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {fmtRelative(run.started_at)}
                      </span>
                      {run.error && (
                        <span className="text-[10px] text-red-400 truncate max-w-[200px]" title={run.error}>
                          {run.error}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
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
    icon?: React.ReactNode,
  ) {
    if (items.length === 0) return null;
    return (
      <div
        className="mb-4 rounded-md overflow-hidden"
        style={{ border: `1px solid ${borderColor}` }}
      >
        <div
          className="flex items-center gap-2 px-3 py-1.5"
          style={{ background: bgColor, borderBottom: `1px solid ${borderColor}` }}
        >
          {icon}
          <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color }}>
            {title}
          </span>
          <span className="text-[10px]" style={{ color: borderColor }}>
            ({items.length})
          </span>
        </div>
        {items.filter((t) => !pendingDeletes.has(t.id)).map((task) => renderTaskRow(task, true))}
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-[var(--text-muted)] text-xs">
          {tasks.length} task{tasks.length !== 1 ? "s" : ""}
          {grouped.length > 1 && ` in ${grouped.length} groups`}
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

      {/* Run count column headers */}
      {tasks.length > 0 && (
        <div className="flex items-center gap-3 px-3 py-1 mb-1">
          <div className="flex-1" />
          <span className="flex gap-1.5 text-[9px] font-mono text-[var(--text-muted)] uppercase tracking-wide">
            {["1m", "5m", "1h", "24h", "7d"].map((w) => (
              <span key={w} style={{ minWidth: "16px", textAlign: "center" }}>{w}</span>
            ))}
          </span>
          <span className="text-[9px] text-[var(--text-muted)]" style={{ minWidth: "28px" }} />
          <span className="text-[9px] text-[var(--text-muted)]" style={{ minWidth: "70px" }} />
          <span style={{ minWidth: "60px" }} />
        </div>
      )}

      {/* Stuck */}
      {renderSection(
        "Stuck",
        stuckTasks,
        "#f59e0b",
        "#78350f",
        "rgba(245, 158, 11, 0.08)",
        <span className="inline-block w-[6px] h-[6px] rounded-full" style={{ background: "#f59e0b" }} />,
      )}

      {/* Currently Running */}
      {renderSection(
        "Currently Running",
        runningTasks,
        "var(--accent)",
        "var(--accent-dim)",
        "var(--accent-glow)",
        <span
          className="inline-block w-[6px] h-[6px] rounded-full"
          style={{ background: "var(--accent)", animation: "pulse-dot 1.5s ease-in-out infinite" }}
        />,
      )}

      {/* Recently Finished */}
      {renderSection(
        "Recently Finished",
        recentlyFinished,
        "#22c55e",
        "#14532d",
        "rgba(34, 197, 94, 0.06)",
      )}

      {/* Recently Failed */}
      {renderSection(
        "Recently Failed",
        recentlyFailed,
        "#ef4444",
        "#7f1d1d",
        "rgba(239, 68, 68, 0.06)",
        <span className="inline-block w-[6px] h-[6px] rounded-full" style={{ background: "#ef4444" }} />,
      )}

      {/* Task groups */}
      {tasks.length === 0 && !creating && (
        <div className="text-[var(--text-muted)] text-xs py-8 text-center">No tasks</div>
      )}

      {grouped.map(([group, groupTasks]) => {
        const isCollapsed = collapsedGroups.has(group);
        const statusCounts = {
          runnable: groupTasks.filter((t) => t.status === "runnable").length,
          running: groupTasks.filter((t) => t.status === "running").length,
          completed: groupTasks.filter((t) => t.status === "completed").length,
          disabled: groupTasks.filter((t) => t.status === "disabled").length,
        };

        return (
          <div key={group} className="mb-2">
            <button
              onClick={() => toggleGroup(group)}
              className="w-full flex items-center gap-2 px-3 py-1.5 rounded-t-md border-0 cursor-pointer transition-colors"
              style={{
                background: "var(--bg-elevated)",
                color: "var(--text-secondary)",
                borderBottom: isCollapsed ? "none" : "1px solid var(--border)",
                borderRadius: isCollapsed ? "6px" : undefined,
              }}
            >
              <span
                className="text-[10px] transition-transform"
                style={{ transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)" }}
              >
                ▼
              </span>
              <span className="font-mono text-[12px] font-medium text-[var(--accent-dim)]">{group}</span>
              <span className="text-[10px] text-[var(--text-muted)]">({groupTasks.length})</span>
              <div className="flex-1" />
              <div className="flex gap-1">
                {statusCounts.running > 0 && <Badge variant="accent">{statusCounts.running} running</Badge>}
                {statusCounts.runnable > 0 && <Badge variant="info">{statusCounts.runnable} runnable</Badge>}
                {statusCounts.disabled > 0 && <Badge variant="neutral">{statusCounts.disabled} disabled</Badge>}
                {statusCounts.completed > 0 && <Badge variant="success">{statusCounts.completed} done</Badge>}
              </div>
            </button>

            {!isCollapsed && (
              <div
                className="rounded-b-md overflow-hidden"
                style={{ border: "1px solid var(--border)", borderTop: "none" }}
              >
                {groupTasks.map((task) => renderTaskRow(task, false))}
              </div>
            )}
          </div>
        );
      })}

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
