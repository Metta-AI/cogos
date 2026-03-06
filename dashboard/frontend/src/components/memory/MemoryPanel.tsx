"use client";

import { useState, useMemo, useCallback } from "react";
import type { MemoryItem } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { fmtRelative } from "@/lib/format";
import { createMemory, updateMemory, deleteMemory } from "@/lib/api";

interface MemoryPanelProps {
  memory: MemoryItem[];
  cogentName?: string;
  onRefresh?: () => void;
}


function tryParseJSON(str: string): unknown | null {
  try {
    const parsed = JSON.parse(str);
    if (typeof parsed === "object" && parsed !== null) return parsed;
    return null;
  } catch {
    return null;
  }
}

function MemoryContent({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);
  const parsed = useMemo(() => tryParseJSON(content), [content]);

  if (parsed) {
    if (!expanded) {
      return (
        <button
          onClick={() => setExpanded(true)}
          className="text-[11px] text-[var(--accent)] hover:underline bg-transparent border-0 cursor-pointer p-0"
        >
          Show JSON
        </button>
      );
    }
    return (
      <div className="mt-1">
        <button
          onClick={() => setExpanded(false)}
          className="text-[11px] text-[var(--accent)] hover:underline bg-transparent border-0 cursor-pointer p-0 mb-1"
        >
          Hide JSON
        </button>
        <JsonViewer data={parsed} />
      </div>
    );
  }

  const truncated = content.length > 200;
  if (!truncated || expanded) {
    return (
      <div className="text-[12px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap break-all">
        {content}
        {truncated && (
          <button
            onClick={() => setExpanded(false)}
            className="ml-1 text-[11px] text-[var(--accent)] hover:underline bg-transparent border-0 cursor-pointer p-0"
          >
            less
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="text-[12px] text-[var(--text-secondary)] font-mono">
      {content.slice(0, 200)}...
      <button
        onClick={() => setExpanded(true)}
        className="ml-1 text-[11px] text-[var(--accent)] hover:underline bg-transparent border-0 cursor-pointer p-0"
      >
        more
      </button>
    </div>
  );
}

const inputStyle = {
  background: "var(--bg-base)",
  borderColor: "var(--border)",
  color: "var(--text-primary)",
};

export function MemoryPanel({ memory, cogentName, onRefresh }: MemoryPanelProps) {
  const [scopeFilter, setScopeFilter] = useState<"cogent" | "polis">("cogent");
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});

  // Filter by selected scope, then group
  const filteredItems = useMemo(
    () => memory.filter((m) => (m.scope ?? "cogent") === scopeFilter),
    [memory, scopeFilter],
  );
  const groups = useMemo(() => {
    const g: Record<string, MemoryItem[]> = {};
    for (const item of filteredItems) {
      const group = item.group || "default";
      if (!g[group]) g[group] = [];
      g[group].push(item);
    }
    return Object.entries(g).sort(([a], [b]) => a.localeCompare(b));
  }, [filteredItems]);

  // Create form state
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newScope, setNewScope] = useState(scopeFilter);

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editScope, setEditScope] = useState("cogent");

  // Delete confirmation
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const toggleGroup = useCallback((key: string) => {
    setCollapsedGroups((c) => ({ ...c, [key]: !c[key] }));
  }, []);

  const handleCreate = useCallback(async () => {
    if (!cogentName || !newName.trim()) return;
    await createMemory(cogentName, {
      name: newName.trim(),
      content: newContent,
      scope: newScope,
    });
    setCreating(false);
    setNewName("");
    setNewContent("");
    setNewScope("cogent");
    onRefresh?.();
  }, [cogentName, newName, newContent, newScope, onRefresh]);

  const startEdit = useCallback((item: MemoryItem) => {
    setEditingId(item.id);
    setEditName(item.name);
    setEditContent(item.content);
    setEditScope(item.scope ?? "cogent");
  }, []);

  const handleUpdate = useCallback(async () => {
    if (!cogentName || !editingId) return;
    await updateMemory(cogentName, editingId, {
      name: editName.trim(),
      content: editContent,
      scope: editScope,
    });
    setEditingId(null);
    onRefresh?.();
  }, [cogentName, editingId, editName, editContent, editScope, onRefresh]);

  const handleDelete = useCallback(async (id: string) => {
    if (!cogentName) return;
    await deleteMemory(cogentName, id);
    setDeleteConfirm(null);
    onRefresh?.();
  }, [cogentName, onRefresh]);

  const canMutate = !!cogentName && !!onRefresh;

  return (
    <div className="space-y-3">
      {/* Header with scope toggle, count, and create button */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="flex text-[11px] font-mono rounded overflow-hidden border" style={{ borderColor: "var(--border)" }}>
            {(["cogent", "polis"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setScopeFilter(s)}
                className="border-0 cursor-pointer px-2.5 py-1 transition-colors"
                style={{
                  background: scopeFilter === s ? "var(--accent)" : "transparent",
                  color: scopeFilter === s ? "var(--bg-deep)" : "var(--text-muted)",
                  fontWeight: scopeFilter === s ? 700 : 400,
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                }}
              >
                {s}
              </button>
            ))}
          </span>
          <span className="text-[11px] text-[var(--text-muted)]">
            {filteredItems.length}/{memory.length} item{memory.length !== 1 ? "s" : ""}
          </span>
        </div>
        {canMutate && !creating && (
          <button
            onClick={() => setCreating(true)}
            className="text-[11px] px-3 py-1 rounded border cursor-pointer transition-colors"
            style={{
              color: "var(--accent)",
              borderColor: "var(--accent)",
              background: "transparent",
            }}
          >
            + New Memory
          </button>
        )}
      </div>

      {/* Create form */}
      {creating && (
        <div
          className="p-4 rounded-md border space-y-3"
          style={{
            background: "var(--bg-surface)",
            borderColor: "var(--accent)",
          }}
        >
          <div className="text-[12px] font-semibold text-[var(--text-primary)]">
            New Memory Item
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                Name
              </label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="group/key-name"
                className="w-full px-2 py-1.5 text-[12px] rounded border font-mono"
                style={inputStyle}
              />
              <div className="text-[9px] text-[var(--text-muted)] mt-1">
                Use / or - to define group
              </div>
            </div>
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                Scope
              </label>
              <select
                value={newScope}
                onChange={(e) => setNewScope(e.target.value)}
                className="w-full px-2 py-1.5 text-[12px] rounded border"
                style={inputStyle}
              >
                <option value="cogent">cogent</option>
                <option value="polis">polis</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
              Content
            </label>
            <textarea
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              placeholder="Memory content..."
              rows={3}
              className="w-full px-2 py-1.5 text-[12px] rounded border font-mono resize-y"
              style={inputStyle}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={!newName.trim()}
              className="text-[11px] px-3 py-1 rounded border-0 cursor-pointer transition-colors disabled:opacity-40"
              style={{
                background: "var(--accent)",
                color: "white",
              }}
            >
              Create
            </button>
            <button
              onClick={() => setCreating(false)}
              className="text-[11px] px-3 py-1 rounded border cursor-pointer transition-colors"
              style={{
                background: "transparent",
                borderColor: "var(--border)",
                color: "var(--text-muted)",
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {filteredItems.length === 0 && !creating && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md">
          <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
            No {scopeFilter} memory items
          </div>
        </div>
      )}

      {/* Grouped display — flat, no scope nesting */}
      {groups.map(([group, items]) => {
        const isGroupCollapsed = collapsedGroups[group] ?? false;

        return (
          <div key={group} className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
            {/* Group header */}
            <div
              className="flex items-center gap-2 px-4 py-2 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
              onClick={() => toggleGroup(group)}
            >
              <span className="text-[var(--text-muted)] text-[9px]">
                {isGroupCollapsed ? "\u25B6" : "\u25BC"}
              </span>
              <span className="text-[12px] text-[var(--text-secondary)] font-medium">
                {group}
              </span>
              <span className="text-[10px] text-[var(--text-muted)]">
                ({items.length})
              </span>
            </div>

            {/* Items */}
            {!isGroupCollapsed &&
              items.map((item) => (
                <div
                  key={item.id}
                  className="px-6 py-2 border-t border-[var(--border)] hover:bg-[var(--bg-hover)] transition-colors"
                >
                  {editingId === item.id ? (
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Name</label>
                          <input
                            value={editName}
                            onChange={(e) => setEditName(e.target.value)}
                            className="w-full px-2 py-1 text-[12px] rounded border font-mono"
                            style={inputStyle}
                          />
                        </div>
                        <div>
                          <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Scope</label>
                          <select
                            value={editScope}
                            onChange={(e) => setEditScope(e.target.value)}
                            className="w-full px-2 py-1 text-[12px] rounded border"
                            style={inputStyle}
                          >
                            <option value="cogent">cogent</option>
                            <option value="polis">polis</option>
                          </select>
                        </div>
                      </div>
                      <div>
                        <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Content</label>
                        <textarea
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          rows={3}
                          className="w-full px-2 py-1 text-[12px] rounded border font-mono resize-y"
                          style={inputStyle}
                        />
                      </div>
                      <div className="flex gap-1">
                        <button
                          onClick={handleUpdate}
                          className="text-[10px] px-2 py-0.5 rounded border-0 cursor-pointer"
                          style={{ background: "var(--accent)", color: "white" }}
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="text-[10px] px-2 py-0.5 rounded border cursor-pointer"
                          style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[12px] font-mono text-[var(--text-primary)]">
                          {item.name}
                        </span>
                        {item.type && <Badge variant="neutral">{item.type}</Badge>}
                        <span className="text-[10px] text-[var(--text-muted)] ml-auto flex items-center gap-2">
                          {fmtRelative(item.updated_at)}
                          {canMutate && deleteConfirm === item.id ? (
                            <span className="text-[11px]">
                              <span className="text-[var(--text-muted)] mr-1">Delete?</span>
                              <button onClick={() => handleDelete(item.id)} className="text-[var(--error)] border-0 bg-transparent cursor-pointer text-[11px] font-semibold mr-1">Yes</button>
                              <button onClick={() => setDeleteConfirm(null)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[11px]">No</button>
                            </span>
                          ) : canMutate ? (
                            <span className="flex gap-1">
                              <button onClick={() => startEdit(item)} className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors" style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}>Edit</button>
                              <button onClick={() => setDeleteConfirm(item.id)} className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors" style={{ background: "transparent", borderColor: "var(--border)", color: "var(--error)" }}>Delete</button>
                            </span>
                          ) : null}
                        </span>
                      </div>
                      <MemoryContent content={item.content} />
                    </>
                  )}
                </div>
              ))}
          </div>
        );
      })}
    </div>
  );
}
