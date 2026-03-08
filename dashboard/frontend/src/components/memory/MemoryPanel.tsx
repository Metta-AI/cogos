"use client";

import { useState, useMemo, useCallback } from "react";
import type { MemoryItem } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { HierarchyPanel, findNode, getAllItems, buildTree } from "@/components/shared/HierarchyPanel";
import { JsonViewer } from "@/components/shared/JsonViewer";
import { fmtTimestamp } from "@/lib/format";
import { createMemory, updateMemory, deleteMemory, activateVersion, updateVersionContent } from "@/lib/api";

interface MemoryPanelProps {
  memory: MemoryItem[];
  cogentName?: string;
  onRefresh?: () => void;
}

const getMemoryGroup = (item: MemoryItem) => item.group || "default";

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

/* ── Version detail panel ── */

interface VersionPanelProps {
  item: MemoryItem;
  cogentName?: string;
  canMutate: boolean;
  onRefresh?: () => void;
  onClose: () => void;
}

function VersionPanel({ item, cogentName, canMutate, onRefresh, onClose }: VersionPanelProps) {
  const [selectedVersion, setSelectedVersion] = useState<number>(item.active_version);
  const [activating, setActivating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveConfirm, setSaveConfirm] = useState<"update" | "new-version" | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  const versions = useMemo(
    () => [...(item.versions ?? [])].sort((a, b) => b.version - a.version),
    [item.versions],
  );

  const currentVersion = useMemo(
    () => versions.find((v) => v.version === selectedVersion) ?? versions[0],
    [versions, selectedVersion],
  );

  const handleActivate = useCallback(async (version: number) => {
    if (!cogentName || activating) return;
    setActivating(true);
    try {
      await activateVersion(cogentName, item.name, version);
      onRefresh?.();
    } finally {
      setActivating(false);
    }
  }, [cogentName, item.name, activating, onRefresh]);

  const handleStartEdit = useCallback(() => {
    const v = versions.find((v) => v.version === selectedVersion) ?? versions[0];
    setEditContent(v?.content ?? "");
    setEditing(true);
    setSaveConfirm(null);
  }, [versions, selectedVersion]);

  const handleUpdate = useCallback(async () => {
    if (!cogentName || saving) return;
    setSaving(true);
    try {
      await updateVersionContent(cogentName, item.name, selectedVersion, editContent);
      setEditing(false);
      setSaveConfirm(null);
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, item.name, selectedVersion, editContent, saving, onRefresh]);

  const handleSaveNewVersion = useCallback(async () => {
    if (!cogentName || saving) return;
    setSaving(true);
    try {
      const updated = await updateMemory(cogentName, item.name, { content: editContent, source: "dashboard" });
      // Activate the new version (latest = highest version number)
      const newVersion = Math.max(...(updated.versions ?? []).map((v) => v.version));
      await activateVersion(cogentName, item.name, newVersion);
      setSelectedVersion(newVersion);
      setEditing(false);
      setSaveConfirm(null);
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, item.name, editContent, saving, onRefresh]);

  const handleDelete = useCallback(async () => {
    if (!cogentName || deleting) return;
    setDeleting(true);
    try {
      await deleteMemory(cogentName, item.name);
      onRefresh?.();
      onClose();
    } finally {
      setDeleting(false);
    }
  }, [cogentName, item.name, deleting, onRefresh, onClose]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className="sticky top-0 z-10 px-4 py-2 border-b flex items-center gap-2"
        style={{ background: "var(--bg-surface)", borderColor: "var(--border)" }}
      >
        <button
          onClick={onClose}
          className="text-[11px] text-[var(--text-muted)] bg-transparent border-0 cursor-pointer p-0 mr-1"
          title="Back to list"
        >
          &larr;
        </button>
        <span className="text-[12px] font-mono font-medium text-[var(--text-primary)] truncate">
          {item.name}
        </span>
        <Badge variant={item.read_only ? "warning" : "success"}>
          {item.read_only ? "read-only" : "writable"}
        </Badge>
        {canMutate && !item.read_only && (
          <span className="ml-auto flex gap-1">
            {!editing && (
              <button
                onClick={handleStartEdit}
                className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors"
                style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
              >
                Edit
              </button>
            )}
            {deleteConfirm ? (
              <span className="flex items-center gap-1 text-[11px]">
                <span className="text-[var(--text-muted)]">Delete?</span>
                <button onClick={handleDelete} disabled={deleting} className="text-[var(--error)] border-0 bg-transparent cursor-pointer text-[11px] font-semibold">{deleting ? "..." : "Yes"}</button>
                <button onClick={() => setDeleteConfirm(false)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[11px]">No</button>
              </span>
            ) : (
              <button
                onClick={() => setDeleteConfirm(true)}
                className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors"
                style={{ background: "transparent", borderColor: "var(--border)", color: "var(--error)" }}
              >
                Delete
              </button>
            )}
          </span>
        )}
      </div>

      {/* Version selector bar */}
      <div
        className="px-4 py-1.5 border-b flex items-center gap-1.5 overflow-x-auto flex-shrink-0"
        style={{ background: "var(--bg-surface)", borderColor: "var(--border)" }}
      >
        {versions.map((v) => {
          const isActive = v.version === item.active_version;
          const isSelected = v.version === selectedVersion;
          return (
            <button
              key={v.version}
              onClick={() => setSelectedVersion(v.version)}
              className="flex items-center gap-1 px-2 py-1 rounded border cursor-pointer transition-colors text-[11px] font-mono flex-shrink-0"
              style={{
                background: isSelected ? "var(--bg-hover)" : "transparent",
                borderColor: isSelected ? "var(--accent)" : "var(--border)",
                color: isSelected ? "var(--accent)" : "var(--text-muted)",
                fontWeight: isSelected ? 600 : 400,
              }}
            >
              v{v.version}
              {isActive && (
                <span
                  className="text-[8px] px-1 py-0 rounded-full font-semibold"
                  style={{ background: "var(--accent)", color: "var(--bg-deep)" }}
                >
                  active
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Version content */}
      <div className="flex-1 overflow-y-auto p-4" style={{ background: "var(--bg-base)" }}>
        {currentVersion && (
          <div>
            {/* Version metadata bar */}
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <Badge variant="neutral">{currentVersion.source}</Badge>
              {currentVersion.read_only && <Badge variant="warning">read-only</Badge>}
              {currentVersion.version === item.active_version ? (
                <Badge variant="success">active</Badge>
              ) : canMutate ? (
                <button
                  onClick={() => handleActivate(currentVersion.version)}
                  disabled={activating}
                  className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors disabled:opacity-40"
                  style={{
                    background: "transparent",
                    borderColor: "var(--accent)",
                    color: "var(--accent)",
                  }}
                >
                  {activating ? "..." : "Make Active"}
                </button>
              ) : null}
              {currentVersion.created_at && (
                <span className="text-[10px] text-[var(--text-muted)] ml-auto">
                  {fmtTimestamp(currentVersion.created_at)}
                </span>
              )}
            </div>

            {/* Version content */}
            {editing ? (
              <div className="space-y-2">
                <textarea
                  value={editContent}
                  onChange={(e) => { setEditContent(e.target.value); setSaveConfirm(null); }}
                  rows={12}
                  className="w-full px-2 py-1.5 text-[12px] rounded border font-mono resize-y"
                  style={inputStyle}
                />
                <div className="flex gap-1.5 items-center flex-wrap">
                  {saveConfirm === "update" ? (
                    <span className="flex items-center gap-1 text-[11px]">
                      <span className="text-[var(--text-muted)]">Overwrite v{selectedVersion}?</span>
                      <button onClick={handleUpdate} disabled={saving} className="text-[var(--accent)] border-0 bg-transparent cursor-pointer text-[11px] font-semibold disabled:opacity-40">{saving ? "..." : "Yes"}</button>
                      <button onClick={() => setSaveConfirm(null)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[11px]">No</button>
                    </span>
                  ) : (
                    <button
                      onClick={() => setSaveConfirm("update")}
                      className="text-[10px] px-2 py-0.5 rounded border cursor-pointer"
                      style={{ background: "transparent", borderColor: "var(--accent)", color: "var(--accent)" }}
                    >
                      Update v{selectedVersion}
                    </button>
                  )}
                  {saveConfirm === "new-version" ? (
                    <span className="flex items-center gap-1 text-[11px]">
                      <span className="text-[var(--text-muted)]">Save &amp; activate new version?</span>
                      <button onClick={handleSaveNewVersion} disabled={saving} className="text-[var(--accent)] border-0 bg-transparent cursor-pointer text-[11px] font-semibold disabled:opacity-40">{saving ? "..." : "Yes"}</button>
                      <button onClick={() => setSaveConfirm(null)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[11px]">No</button>
                    </span>
                  ) : (
                    <button
                      onClick={() => setSaveConfirm("new-version")}
                      className="text-[10px] px-2 py-0.5 rounded border-0 cursor-pointer"
                      style={{ background: "var(--accent)", color: "white" }}
                    >
                      Save as New Version
                    </button>
                  )}
                  <button
                    onClick={() => { setEditing(false); setSaveConfirm(null); }}
                    className="text-[10px] px-2 py-0.5 rounded border cursor-pointer"
                    style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <MemoryContent content={currentVersion.content} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const inputStyle = {
  background: "var(--bg-base)",
  borderColor: "var(--border)",
  color: "var(--text-primary)",
};

export function MemoryPanel({ memory, cogentName, onRefresh }: MemoryPanelProps) {
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedMemory, setSelectedMemory] = useState<MemoryItem | null>(null);

  // Create form state
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newSource, setNewSource] = useState("cogent");

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editSource, setEditSource] = useState("cogent");

  // Delete confirmation
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // Compute available sources for the filter
  const sources = useMemo(() => {
    const s = new Set<string>();
    for (const m of memory) s.add(m.source);
    return ["all", ...Array.from(s).sort()];
  }, [memory]);

  const filteredItems = useMemo(
    () => sourceFilter === "all" ? memory : memory.filter((m) => m.source === sourceFilter),
    [memory, sourceFilter],
  );

  // Keep selectedMemory in sync with refreshed data
  const activeSelectedMemory = useMemo(() => {
    if (!selectedMemory) return null;
    return memory.find((m) => m.id === selectedMemory.id) ?? null;
  }, [memory, selectedMemory]);

  const displayItems = useMemo(() => {
    if (!selectedPath) return filteredItems;
    const tree = buildTree(filteredItems, getMemoryGroup);
    const node = findNode(tree, selectedPath);
    return node ? getAllItems(node) : filteredItems;
  }, [filteredItems, selectedPath]);

  const handleCreate = useCallback(async () => {
    if (!cogentName || !newName.trim()) return;
    await createMemory(cogentName, {
      name: newName.trim(),
      content: newContent,
      source: newSource,
    });
    setCreating(false);
    setNewName("");
    setNewContent("");
    setNewSource("cogent");
    onRefresh?.();
  }, [cogentName, newName, newContent, newSource, onRefresh]);

  const startEdit = useCallback((item: MemoryItem) => {
    setEditingId(item.id);
    setEditContent(item.content);
    setEditSource(item.source ?? "cogent");
  }, []);

  const handleUpdate = useCallback(async () => {
    if (!cogentName || !editingId) return;
    const item = memory.find((m) => m.id === editingId);
    if (!item) return;
    await updateMemory(cogentName, item.name, {
      content: editContent,
      source: editSource,
    });
    setEditingId(null);
    onRefresh?.();
  }, [cogentName, editingId, memory, editContent, editSource, onRefresh]);

  const handleDelete = useCallback(async (item: MemoryItem) => {
    if (!cogentName) return;
    await deleteMemory(cogentName, item.name);
    setDeleteConfirm(null);
    onRefresh?.();
  }, [cogentName, onRefresh]);

  const canMutate = !!cogentName && !!onRefresh;

  // If a memory is selected, show version detail view
  if (activeSelectedMemory) {
    return (
      <div className="flex flex-col h-full" style={{ minHeight: "calc(100vh - 160px)" }}>
        <div className="flex-1 min-h-0 border rounded-md overflow-hidden" style={{ borderColor: "var(--border)" }}>
          <VersionPanel
            item={activeSelectedMemory}
            cogentName={cogentName}
            canMutate={canMutate}
            onRefresh={onRefresh}
            onClose={() => setSelectedMemory(null)}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full" style={{ minHeight: "calc(100vh - 160px)" }}>
      {/* Header with source filter, count, and create button */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="flex text-[11px] font-mono rounded overflow-hidden border" style={{ borderColor: "var(--border)" }}>
            {sources.map((s) => (
              <button
                key={s}
                onClick={() => { setSourceFilter(s); setSelectedPath(null); }}
                className="border-0 cursor-pointer px-2.5 py-1 transition-colors"
                style={{
                  background: sourceFilter === s ? "var(--accent)" : "transparent",
                  color: sourceFilter === s ? "var(--bg-deep)" : "var(--text-muted)",
                  fontWeight: sourceFilter === s ? 700 : 400,
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
          className="p-4 rounded-md border space-y-3 mb-3"
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
                Source
              </label>
              <select
                value={newSource}
                onChange={(e) => setNewSource(e.target.value)}
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
              {displayItems.map((item) => (
                <div
                  key={item.id}
                  className="px-4 py-3 border-b hover:bg-[var(--bg-hover)] transition-colors cursor-pointer"
                  style={{ borderColor: "var(--border)" }}
                  onClick={() => setSelectedMemory(item)}
                >
                  {editingId === item.id ? (
                    <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                      <div>
                        <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Content</label>
                        <textarea
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          rows={4}
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
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-[12px] font-mono font-medium text-[var(--text-primary)]">
                          {item.name}
                        </span>
                        <Badge variant="neutral">v{item.active_version}</Badge>
                        <Badge variant="neutral">{item.source}</Badge>
                        {item.read_only && <Badge variant="warning">RO</Badge>}
                        {(item.versions ?? []).length > 1 && (
                          <span className="text-[10px] text-[var(--text-muted)]">
                            {(item.versions ?? []).length} versions
                          </span>
                        )}
                        <span className="text-[10px] text-[var(--text-muted)] ml-auto flex items-center gap-2">
                          {fmtTimestamp(item.modified_at)}
                          {canMutate && deleteConfirm === item.id ? (
                            <span className="text-[11px]" onClick={(e) => e.stopPropagation()}>
                              <span className="text-[var(--text-muted)] mr-1">Delete?</span>
                              <button onClick={() => handleDelete(item)} className="text-[var(--error)] border-0 bg-transparent cursor-pointer text-[11px] font-semibold mr-1">Yes</button>
                              <button onClick={() => setDeleteConfirm(null)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[11px]">No</button>
                            </span>
                          ) : canMutate ? (
                            <span className="flex gap-1" onClick={(e) => e.stopPropagation()}>
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
          )}
        </div>
      </div>
    </div>
  );
}
