"use client";

import { useState, useCallback, useMemo } from "react";
import type { Trigger } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { toggleTriggers, createTrigger, updateTrigger, deleteTrigger } from "@/lib/api";
import { fmtNum } from "@/lib/format";

interface TriggersPanelProps {
  triggers: Trigger[];
  cogentName: string;
  programs?: string[];
  onRefresh?: () => void;
}

interface CreateFormState {
  program_name: string;
  event_pattern: string;
  priority: number;
  enabled: boolean;
}

interface EditFormState {
  program_name: string;
  event_pattern: string;
  priority: number;
}

const EMPTY_CREATE: CreateFormState = {
  program_name: "",
  event_pattern: "",
  priority: 10,
  enabled: true,
};

function groupByPrefix(triggers: Trigger[]): Record<string, Trigger[]> {
  const groups: Record<string, Trigger[]> = {};
  for (const t of triggers) {
    const dotIdx = t.name.indexOf(".");
    const prefix = dotIdx > 0 ? t.name.slice(0, dotIdx) : "other";
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push(t);
  }
  return groups;
}

export function TriggersPanel({ triggers, cogentName, programs = [], onRefresh }: TriggersPanelProps) {
  const groups = useMemo(() => groupByPrefix(triggers), [triggers]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CreateFormState>(EMPTY_CREATE);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<EditFormState>({ program_name: "", event_pattern: "", priority: 10 });
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const toggleCollapse = useCallback((group: string) => {
    setCollapsed((c) => ({ ...c, [group]: !c[group] }));
  }, []);

  const handleBulkToggle = useCallback(
    async (groupTriggers: Trigger[], enabled: boolean) => {
      const ids = groupTriggers.map((t) => t.id);
      setToggling((s) => {
        const next = new Set(s);
        ids.forEach((id) => next.add(id));
        return next;
      });
      try {
        await toggleTriggers(cogentName, ids, enabled);
        onRefresh?.();
      } finally {
        setToggling((s) => {
          const next = new Set(s);
          ids.forEach((id) => next.delete(id));
          return next;
        });
      }
    },
    [cogentName, onRefresh],
  );

  const handleSingleToggle = useCallback(
    async (trigger: Trigger) => {
      setToggling((s) => new Set(s).add(trigger.id));
      try {
        await toggleTriggers(cogentName, [trigger.id], !trigger.enabled);
        onRefresh?.();
      } finally {
        setToggling((s) => {
          const next = new Set(s);
          next.delete(trigger.id);
          return next;
        });
      }
    },
    [cogentName, onRefresh],
  );

  const handleCreate = useCallback(async () => {
    if (!createForm.program_name || !createForm.event_pattern) return;
    setCreating(true);
    try {
      await createTrigger(cogentName, {
        program_name: createForm.program_name,
        event_pattern: createForm.event_pattern,
        priority: createForm.priority,
        enabled: createForm.enabled,
      });
      setCreateForm(EMPTY_CREATE);
      setShowCreate(false);
      onRefresh?.();
    } finally {
      setCreating(false);
    }
  }, [cogentName, createForm, onRefresh]);

  const startEdit = useCallback((t: Trigger) => {
    setEditingId(t.id);
    setEditForm({
      program_name: t.program_name ?? "",
      event_pattern: t.event_pattern ?? "",
      priority: t.priority ?? 10,
    });
  }, []);

  const handleSaveEdit = useCallback(async () => {
    if (!editingId) return;
    setSaving(true);
    try {
      await updateTrigger(cogentName, editingId, {
        program_name: editForm.program_name,
        event_pattern: editForm.event_pattern,
        priority: editForm.priority,
      });
      setEditingId(null);
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, editingId, editForm, onRefresh]);

  const handleDelete = useCallback(async (triggerId: string) => {
    setDeletingId(triggerId);
    try {
      await deleteTrigger(cogentName, triggerId);
      setConfirmDeleteId(null);
      onRefresh?.();
    } finally {
      setDeletingId(null);
    }
  }, [cogentName, onRefresh]);

  const datalistId = "trigger-programs-list";

  const inputClass =
    "bg-[var(--bg-elevated)] border border-[var(--border)] rounded px-2 py-1 text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
  const btnClass =
    "px-2.5 py-1 rounded text-[11px] font-medium transition-colors disabled:opacity-40";
  const btnPrimary = `${btnClass} bg-[var(--accent)] text-white hover:opacity-90`;
  const btnDanger = `${btnClass} bg-red-600 text-white hover:bg-red-700`;
  const btnGhost = `${btnClass} text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]`;

  return (
    <div className="space-y-3">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <datalist id={datalistId}>
          {programs.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
        <button
          className={btnPrimary}
          onClick={() => setShowCreate((s) => !s)}
        >
          {showCreate ? "Cancel" : "+ New Trigger"}
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4 space-y-3">
          <div className="text-[13px] font-semibold text-[var(--text-primary)]">New Trigger</div>
          <div className="flex flex-wrap gap-3 items-end">
            <label className="flex flex-col gap-1">
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Program</span>
              <input
                list={datalistId}
                className={inputClass}
                placeholder="program-name"
                value={createForm.program_name}
                onChange={(e) => setCreateForm((f) => ({ ...f, program_name: e.target.value }))}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Event Pattern</span>
              <input
                className={inputClass}
                placeholder="event.pattern.*"
                value={createForm.event_pattern}
                onChange={(e) => setCreateForm((f) => ({ ...f, event_pattern: e.target.value }))}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Priority</span>
              <input
                type="number"
                className={`${inputClass} w-[70px]`}
                value={createForm.priority}
                onChange={(e) => setCreateForm((f) => ({ ...f, priority: parseInt(e.target.value) || 10 }))}
              />
            </label>
            <label className="flex items-center gap-2 pb-1">
              <input
                type="checkbox"
                checked={createForm.enabled}
                onChange={(e) => setCreateForm((f) => ({ ...f, enabled: e.target.checked }))}
                className="accent-[var(--accent)]"
              />
              <span className="text-[11px] text-[var(--text-secondary)]">Enabled</span>
            </label>
            <button
              className={btnPrimary}
              disabled={creating || !createForm.program_name || !createForm.event_pattern}
              onClick={handleCreate}
            >
              {creating ? "Creating..." : "Create"}
            </button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {triggers.length === 0 && !showCreate && (
        <div>
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Name</th>
                <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Type</th>
                <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">Pattern / Cron</th>
                <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-center">Enabled</th>
                <th className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">Fired</th>
              </tr>
            </thead>
          </table>
          <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
            No triggers configured
          </div>
        </div>
      )}

      {/* Grouped triggers */}
      {Object.keys(groups).sort().map((group) => {
        const items = groups[group];
        const isCollapsed = collapsed[group] ?? false;
        const allEnabled = items.every((t) => t.enabled);
        const anyToggling = items.some((t) => toggling.has(t.id));

        return (
          <div
            key={group}
            className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden"
          >
            {/* Group header */}
            <div
              className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
              onClick={() => toggleCollapse(group)}
            >
              <span className="text-[var(--text-muted)] text-[10px]">
                {isCollapsed ? "\u25B6" : "\u25BC"}
              </span>
              <span className="text-[13px] font-semibold text-[var(--text-primary)] flex-1">
                {group}
                <span className="text-[var(--text-muted)] font-normal ml-2 text-[11px]">
                  ({items.length})
                </span>
              </span>
              <label
                className="flex items-center gap-2"
                onClick={(e) => e.stopPropagation()}
              >
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">
                  All
                </span>
                <ToggleSwitch
                  checked={allEnabled}
                  disabled={anyToggling}
                  onChange={() => handleBulkToggle(items, !allEnabled)}
                />
              </label>
            </div>

            {/* Trigger rows */}
            {!isCollapsed && (
              <div className="border-t border-[var(--border)]">
                <table className="w-full text-left text-[12px]">
                  <thead>
                    <tr className="border-b border-[var(--border)]">
                      <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                        Name
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                        Type
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                        Pattern / Cron
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        Priority
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-center">
                        Enabled
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        1m
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        5m
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        1h
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        24h
                      </th>
                      <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-right">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((t) => {
                      const isEditing = editingId === t.id;
                      const isConfirmingDelete = confirmDeleteId === t.id;
                      const isDeleting = deletingId === t.id;

                      if (isEditing) {
                        return (
                          <tr
                            key={t.id}
                            className="border-b border-[var(--border)] last:border-0 bg-[var(--bg-hover)]"
                          >
                            <td className="px-4 py-2" colSpan={2}>
                              <input
                                list={datalistId}
                                className={`${inputClass} w-full`}
                                value={editForm.program_name}
                                onChange={(e) => setEditForm((f) => ({ ...f, program_name: e.target.value }))}
                                placeholder="program-name"
                              />
                            </td>
                            <td className="px-3 py-2">
                              <input
                                className={`${inputClass} w-full`}
                                value={editForm.event_pattern}
                                onChange={(e) => setEditForm((f) => ({ ...f, event_pattern: e.target.value }))}
                                placeholder="event.pattern.*"
                              />
                            </td>
                            <td className="px-3 py-2">
                              <input
                                type="number"
                                className={`${inputClass} w-[60px]`}
                                value={editForm.priority}
                                onChange={(e) => setEditForm((f) => ({ ...f, priority: parseInt(e.target.value) || 10 }))}
                              />
                            </td>
                            <td className="px-3 py-2 text-center">
                              <ToggleSwitch
                                checked={t.enabled}
                                disabled={toggling.has(t.id)}
                                onChange={() => handleSingleToggle(t)}
                              />
                            </td>
                            <td colSpan={4} />
                            <td className="px-3 py-2 text-right whitespace-nowrap">
                              <button
                                className={btnPrimary}
                                disabled={saving}
                                onClick={handleSaveEdit}
                              >
                                {saving ? "Saving..." : "Save"}
                              </button>
                              <button
                                className={`${btnGhost} ml-1`}
                                onClick={() => setEditingId(null)}
                              >
                                Cancel
                              </button>
                            </td>
                          </tr>
                        );
                      }

                      return (
                        <tr
                          key={t.id}
                          className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                        >
                          <td className="px-4 py-2 font-mono text-[var(--text-secondary)]">
                            {t.name}
                          </td>
                          <td className="px-3 py-2">
                            <Badge variant="info">{(t.trigger_type && t.trigger_type.toLowerCase() !== "unknown" ? t.trigger_type : null) || (t.cron_expression ? "cron" : t.event_pattern ? "event" : "unknown")}</Badge>
                          </td>
                          <td className="px-3 py-2 font-mono text-[var(--text-muted)] max-w-[200px] truncate">
                            {t.event_pattern ?? t.cron_expression ?? "--"}
                          </td>
                          <td className="px-3 py-2 font-mono text-[var(--text-secondary)] text-right">
                            {t.priority ?? "--"}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <ToggleSwitch
                              checked={t.enabled}
                              disabled={toggling.has(t.id)}
                              onChange={() => handleSingleToggle(t)}
                            />
                          </td>
                          <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                            {fmtNum(t.fired_1m)}
                          </td>
                          <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                            {fmtNum(t.fired_5m)}
                          </td>
                          <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                            {fmtNum(t.fired_1h)}
                          </td>
                          <td className="px-3 py-2 font-mono text-[var(--text-muted)] text-right text-[11px]">
                            {fmtNum(t.fired_24h)}
                          </td>
                          <td className="px-3 py-2 text-right whitespace-nowrap">
                            {isConfirmingDelete ? (
                              <span className="text-[11px]">
                                <span className="text-[var(--text-muted)] mr-1">Delete?</span>
                                <button
                                  className={btnDanger}
                                  disabled={isDeleting}
                                  onClick={() => handleDelete(t.id)}
                                >
                                  {isDeleting ? "..." : "Yes"}
                                </button>
                                <button
                                  className={`${btnGhost} ml-1`}
                                  onClick={() => setConfirmDeleteId(null)}
                                >
                                  No
                                </button>
                              </span>
                            ) : (
                              <>
                                <button
                                  className={btnGhost}
                                  onClick={() => startEdit(t)}
                                >
                                  Edit
                                </button>
                                <button
                                  className={`${btnGhost} ml-1 hover:!text-red-400`}
                                  onClick={() => setConfirmDeleteId(t.id)}
                                >
                                  Delete
                                </button>
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- Toggle switch ---------- */

function ToggleSwitch({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className="relative inline-flex items-center h-[18px] w-[32px] rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-40"
      style={{
        background: checked ? "var(--accent)" : "var(--bg-elevated)",
        border: "1px solid var(--border)",
      }}
    >
      <span
        className="inline-block h-[14px] w-[14px] rounded-full bg-white transition-transform duration-200"
        style={{
          transform: checked ? "translateX(14px)" : "translateX(1px)",
        }}
      />
    </button>
  );
}
