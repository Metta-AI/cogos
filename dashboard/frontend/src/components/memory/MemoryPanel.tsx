"use client";

import { useState, useMemo, useCallback } from "react";
import type { MemoryItem } from "@/lib/types";
import { HierarchyPanel, findNode, getAllItems, buildTree } from "@/components/shared/HierarchyPanel";
import { fmtTimestamp } from "@/lib/format";
import { createMemory, updateMemory, deleteMemory } from "@/lib/api";

interface MemoryPanelProps {
  memory: MemoryItem[];
  cogentName?: string;
  onRefresh?: () => void;
}

const getMemoryGroup = (item: MemoryItem) => item.group || "default";


const inputStyle = {
  background: "var(--bg-base)",
  borderColor: "var(--border)",
  color: "var(--text-primary)",
};

export function MemoryPanel({ memory, cogentName, onRefresh }: MemoryPanelProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Create form state
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newContent, setNewContent] = useState("");

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);

  // Confirmation state
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [updateConfirm, setUpdateConfirm] = useState(false);

  const filteredItems = memory;

  const displayItems = useMemo(() => {
    if (!selectedPath) return filteredItems;
    const tree = buildTree(filteredItems, getMemoryGroup);
    const node = findNode(tree, selectedPath);
    return node ? getAllItems(node) : filteredItems;
  }, [filteredItems, selectedPath]);

  const handleCreate = useCallback(async () => {
    if (!cogentName || !newName.trim()) return;
    try {
      await createMemory(cogentName, {
        name: newName.trim(),
        content: newContent,
      });
      setCreating(false);
      setNewName("");
      setNewContent("");
      onRefresh?.();
    } catch (err) {
      console.error("Failed to create memory:", err);
    }
  }, [cogentName, newName, newContent, onRefresh]);

  const startEdit = useCallback((item: MemoryItem) => {
    setEditingId(item.id);
    setExpandedId(item.id);
    setEditContent(item.content);
    setUpdateConfirm(false);
  }, []);

  const handleSave = useCallback(async () => {
    if (!cogentName || !editingId || saving) return;
    const item = memory.find((m) => m.id === editingId);
    if (!item) return;
    setSaving(true);
    try {
      await updateMemory(cogentName, item.name, {
        content: editContent,
      });
      setEditingId(null);
      setUpdateConfirm(false);
      onRefresh?.();
    } catch (err) {
      console.error("Failed to update memory:", err);
    } finally {
      setSaving(false);
    }
  }, [cogentName, editingId, memory, editContent, saving, onRefresh]);

  const handleDelete = useCallback(async (item: MemoryItem) => {
    if (!cogentName) return;
    try {
      await deleteMemory(cogentName, item.name);
      setDeleteConfirm(null);
      if (expandedId === item.id) setExpandedId(null);
      onRefresh?.();
    } catch (err) {
      console.error("Failed to delete memory:", err);
    }
  }, [cogentName, expandedId, onRefresh]);

  const canMutate = !!cogentName && !!onRefresh;

  return (
    <div className="flex flex-col h-full" style={{ minHeight: "calc(100vh - 160px)" }}>
      {/* Header with count and create button */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] text-[var(--text-muted)]">
          {memory.length} item{memory.length !== 1 ? "s" : ""}
        </span>
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
          className="p-4 rounded-md border space-y-3 mb-3"
          style={{
            background: "var(--bg-surface)",
            borderColor: "var(--accent)",
          }}
        >
          <div className="text-[12px] font-semibold text-[var(--text-primary)]">
            New Memory Item
          </div>
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

      {/* Split pane: tree left, detail right */}
      <div className="flex gap-0 flex-1 min-h-0 border rounded-md overflow-hidden" style={{ borderColor: "var(--border)" }}>
        <HierarchyPanel
          items={filteredItems}
          getGroup={getMemoryGroup}
          selectedPath={selectedPath}
          onSelectPath={setSelectedPath}
        />

        {/* Right: detail view */}
        <div
          className="flex-1 overflow-y-auto"
          style={{ background: "var(--bg-base)" }}
        >
          {/* Selected group header */}
          <div
            className="sticky top-0 z-10 px-4 py-2 border-b flex items-center gap-2"
            style={{
              background: "var(--bg-surface)",
              borderColor: "var(--border)",
            }}
          >
            <span className="text-[12px] font-mono font-medium text-[var(--text-primary)]">
              {selectedPath ?? "All"}
            </span>
            <span className="text-[10px] text-[var(--text-muted)]">
              {displayItems.length} item{displayItems.length !== 1 ? "s" : ""}
            </span>
          </div>

          {displayItems.length === 0 ? (
            <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
              No memory items{selectedPath ? ` in ${selectedPath}` : ""}
            </div>
          ) : (
            <div>
              {displayItems.map((item) => {
                const isExpanded = expandedId === item.id;
                return (
                  <div
                    key={item.id}
                    className="border-b"
                    style={{ borderColor: "var(--border)" }}
                  >
                    {/* Row header - always visible */}
                    <div
                      className="relative px-4 py-2 hover:bg-[var(--bg-hover)] transition-colors cursor-pointer group"
                      onClick={() => setExpandedId(isExpanded ? null : item.id)}
                    >
                      {canMutate && (
                        <button
                          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity border-0 bg-transparent cursor-pointer p-1 rounded hover:bg-[var(--bg-hover)]"
                          style={{ color: "var(--text-muted)" }}
                          title="Edit"
                          onClick={(e) => { e.stopPropagation(); startEdit(item); }}
                        >
                          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Zm1.414 1.06a.25.25 0 0 0-.354 0L3.463 11.098a.25.25 0 0 0-.064.108l-.631 2.208 2.208-.63a.25.25 0 0 0 .108-.064l8.61-8.61a.25.25 0 0 0 0-.354l-1.086-1.086Z"/></svg>
                        </button>
                      )}
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-[var(--text-muted)]">{isExpanded ? "\u25BE" : "\u25B8"}</span>
                        <span className="text-[12px] font-mono font-medium text-[var(--text-primary)] truncate">
                          {item.name}
                        </span>
                        <span className="text-[10px] text-[var(--text-muted)] ml-auto shrink-0">
                          {fmtTimestamp(item.modified_at)}
                        </span>
                      </div>
                    </div>

                    {/* Expanded inline detail */}
                    {isExpanded && (
                      <div
                        className="px-4 pb-3 ml-4 border-l-2"
                        style={{ background: "var(--bg-surface)", borderLeftColor: "var(--accent)" }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {/* Edit form */}
                        {editingId === item.id ? (
                          <div className="space-y-2 pt-2">
                            <div className="text-[11px] font-mono text-[var(--text-muted)]">Editing: {item.name}</div>
                            <textarea
                              value={editContent}
                              onChange={(e) => setEditContent(e.target.value)}
                              rows={6}
                              className="w-full px-2 py-1 text-[12px] rounded border font-mono resize-y"
                              style={inputStyle}
                            />
                            <div className="flex items-center gap-1.5">
                              {!updateConfirm ? (
                                <button
                                  onClick={() => setUpdateConfirm(true)}
                                  disabled={saving || editContent === item.content}
                                  className="text-[10px] px-2.5 py-1 rounded border-0 cursor-pointer disabled:opacity-40"
                                  style={{ background: "var(--accent)", color: "white" }}
                                >
                                  Save
                                </button>
                              ) : (
                                <span className="flex items-center gap-1.5 text-[10px]">
                                  <span className="text-[var(--warning)]">Save changes?</span>
                                  <button
                                    onClick={handleSave}
                                    disabled={saving}
                                    className="px-2 py-0.5 rounded border-0 cursor-pointer text-[10px] font-semibold disabled:opacity-40"
                                    style={{ background: "var(--accent)", color: "white" }}
                                  >
                                    {saving ? "Saving..." : "Confirm"}
                                  </button>
                                  <button
                                    onClick={() => setUpdateConfirm(false)}
                                    className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[10px]"
                                  >
                                    Cancel
                                  </button>
                                </span>
                              )}
                              <span className="flex gap-1.5 ml-auto">
                                <button
                                  onClick={() => { setEditingId(null); setUpdateConfirm(false); }}
                                  className="text-[10px] px-2.5 py-1 rounded border cursor-pointer"
                                  style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
                                >
                                  Discard
                                </button>
                                {deleteConfirm === item.id ? (
                                  <span className="flex items-center gap-1 text-[10px]">
                                    <span className="text-[var(--error)]">Delete?</span>
                                    <button onClick={() => handleDelete(item)} className="text-[var(--error)] border-0 bg-transparent cursor-pointer text-[10px] font-semibold">Yes</button>
                                    <button onClick={() => setDeleteConfirm(null)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[10px]">No</button>
                                  </span>
                                ) : (
                                  <button
                                    onClick={() => setDeleteConfirm(item.id)}
                                    className="text-[10px] px-2.5 py-1 rounded border cursor-pointer"
                                    style={{ background: "transparent", borderColor: "var(--border)", color: "var(--error)" }}
                                  >
                                    Delete
                                  </button>
                                )}
                              </span>
                            </div>
                          </div>
                        ) : (
                          <div className="pt-2">
                            <div className="text-[12px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap break-all">
                              {item.content}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
