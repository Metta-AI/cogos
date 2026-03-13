"use client";

import { useState, useMemo, useCallback, useEffect, useDeferredValue } from "react";
import type { CogosFile, CogosFileVersion } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { HierarchyPanel, findNode, getAllItems, buildTree } from "@/components/shared/HierarchyPanel";
import { FileReferenceTextarea } from "@/components/shared/FileReferenceTextarea";
import { fmtTimestamp } from "@/lib/format";
import {
  getFileDetail,
  createFile,
  updateFile,
  deleteFile,
  activateFileVersion,
  updateFileVersionContent,
  deleteFileVersion,
} from "@/lib/api";

interface FilesPanelProps {
  files: CogosFile[];
  cogentName?: string;
  onRefresh?: () => void;
}

const getFileGroup = (item: CogosFile) => {
  const parts = item.key.split("/");
  return parts.length > 1 ? parts.slice(0, -1).join("/") : "(root)";
};

const matchesFileSearch = (file: CogosFile, normalizedQuery: string) => {
  if (!normalizedQuery) return true;
  return [file.key, ...file.includes].join("\n").toLowerCase().includes(normalizedQuery);
};

/* ── Version detail panel (inline below file list) ── */

interface VersionPanelProps {
  file: CogosFile;
  fileSuggestions: string[];
  cogentName?: string;
  canMutate: boolean;
  onRefresh?: () => void;
  onClose: () => void;
}

function VersionPanel({ file, fileSuggestions, cogentName, canMutate, onRefresh, onClose }: VersionPanelProps) {
  const [versions, setVersions] = useState<CogosFileVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [activating, setActivating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveConfirm, setSaveConfirm] = useState<"update" | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleteVersionConfirm, setDeleteVersionConfirm] = useState(false);
  const [deletingVersion, setDeletingVersion] = useState(false);

  const loadVersions = useCallback(async () => {
    if (!cogentName) return;
    setLoading(true);
    try {
      const detail = await getFileDetail(cogentName, file.key);
      const sorted = [...detail.versions].sort((a, b) => b.version - a.version);
      setVersions(sorted);
      if (selectedVersion === null && sorted.length > 0) {
        const active = sorted.find((v) => v.is_active);
        setSelectedVersion(active?.version ?? sorted[0].version);
      }
    } finally {
      setLoading(false);
    }
  }, [cogentName, file.key, selectedVersion]);

  useEffect(() => {
    setSelectedVersion(null);
    setEditing(false);
    setDeleteConfirm(false);
    setDeleteVersionConfirm(false);
    loadVersions();
  }, [file.key, cogentName]);

  const activeVersion = useMemo(() => versions.find((v) => v.is_active), [versions]);
  const currentVersion = useMemo(
    () => versions.find((v) => v.version === selectedVersion) ?? versions[0],
    [versions, selectedVersion],
  );

  const handleActivate = useCallback(async (version: number) => {
    if (!cogentName || activating) return;
    setActivating(true);
    try {
      await activateFileVersion(cogentName, file.key, version);
      await loadVersions();
      onRefresh?.();
    } finally {
      setActivating(false);
    }
  }, [cogentName, file.key, activating, loadVersions, onRefresh]);

  const handleStartEdit = useCallback(() => {
    setEditContent(currentVersion?.content ?? "");
    setEditing(true);
    setSaveConfirm(null);
  }, [currentVersion]);

  const handleUpdate = useCallback(async () => {
    if (!cogentName || saving || !selectedVersion) return;
    setSaving(true);
    try {
      await updateFileVersionContent(cogentName, file.key, selectedVersion, editContent);
      setEditing(false);
      setSaveConfirm(null);
      await loadVersions();
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, file.key, selectedVersion, editContent, saving, loadVersions, onRefresh]);

  const handleSaveNewVersion = useCallback(async () => {
    if (!cogentName || saving) return;
    setSaving(true);
    try {
      const fv = await updateFile(cogentName, file.key, { content: editContent });
      setSelectedVersion(fv.version);
      setEditing(false);
      setSaveConfirm(null);
      await loadVersions();
      onRefresh?.();
    } finally {
      setSaving(false);
    }
  }, [cogentName, file.key, editContent, saving, loadVersions, onRefresh]);

  const handleDelete = useCallback(async () => {
    if (!cogentName || deleting) return;
    setDeleting(true);
    try {
      await deleteFile(cogentName, file.key);
      onRefresh?.();
      onClose();
    } finally {
      setDeleting(false);
    }
  }, [cogentName, file.key, deleting, onRefresh, onClose]);

  const handleDeleteVersion = useCallback(async () => {
    if (!cogentName || deletingVersion || !selectedVersion) return;
    setDeletingVersion(true);
    try {
      await deleteFileVersion(cogentName, file.key, selectedVersion);
      setDeleteVersionConfirm(false);
      setSelectedVersion(activeVersion?.version ?? null);
      await loadVersions();
      onRefresh?.();
    } finally {
      setDeletingVersion(false);
    }
  }, [cogentName, file.key, selectedVersion, activeVersion, deletingVersion, loadVersions, onRefresh]);

  return (
    <div className="flex flex-col h-full">
      {/* Header bar */}
      <div
        className="px-4 py-2 flex items-center gap-2 border-b"
        style={{ background: "var(--bg-surface)", borderColor: "var(--border)" }}
      >
        <span className="text-[12px] font-mono font-medium text-[var(--accent)] truncate">
          {file.key}
        </span>
        {file.includes.length > 0 && (
          <span className="text-[10px] text-[var(--text-muted)]">
            includes: {file.includes.join(", ")}
          </span>
        )}
        {canMutate && (
          <span className="ml-auto flex gap-1">
            {!editing && (
              <button
                onClick={handleStartEdit}
                disabled={loading}
                className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors disabled:opacity-40"
                style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
              >
                Edit
              </button>
            )}
            {deleteConfirm ? (
              <span className="flex items-center gap-1 text-[11px]">
                <span className="text-[var(--text-muted)]">Delete file?</span>
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
            <button
              onClick={onClose}
              className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors"
              style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
              title="Close"
            >
              &times;
            </button>
          </span>
        )}
        {!canMutate && (
          <button
            onClick={onClose}
            className="ml-auto text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors"
            style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-muted)" }}
            title="Close"
          >
            &times;
          </button>
        )}
      </div>

      {loading ? (
        <div className="py-4 text-center text-[var(--text-muted)] text-[13px]">
          Loading...
        </div>
      ) : (
        <>
          {/* Version selector bar */}
          <div
            className="px-4 py-1.5 border-b flex items-center gap-1.5 overflow-x-auto flex-shrink-0"
            style={{ background: "var(--bg-surface)", borderColor: "var(--border)" }}
          >
            {versions.map((v) => {
              const isActive = v.is_active;
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

            {/* Version metadata inline */}
            {currentVersion && (
              <span className="flex items-center gap-2 ml-2">
                <Badge variant="neutral">{currentVersion.source}</Badge>
                {currentVersion.read_only && <Badge variant="warning">read-only</Badge>}
                {currentVersion.is_active ? (
                  <Badge variant="success">active</Badge>
                ) : canMutate ? (
                  <>
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
                    {deleteVersionConfirm ? (
                      <span className="flex items-center gap-1 text-[11px]">
                        <span className="text-[var(--text-muted)]">Delete v{selectedVersion}?</span>
                        <button onClick={handleDeleteVersion} disabled={deletingVersion} className="text-[var(--error)] border-0 bg-transparent cursor-pointer text-[11px] font-semibold disabled:opacity-40">{deletingVersion ? "..." : "Yes"}</button>
                        <button onClick={() => setDeleteVersionConfirm(false)} className="text-[var(--text-muted)] border-0 bg-transparent cursor-pointer text-[11px]">No</button>
                      </span>
                    ) : (
                      <button
                        onClick={() => setDeleteVersionConfirm(true)}
                        className="text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors"
                        style={{ background: "transparent", borderColor: "var(--border)", color: "var(--error)" }}
                      >
                        Delete Version
                      </button>
                    )}
                  </>
                ) : null}
                {currentVersion.created_at && (
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {fmtTimestamp(currentVersion.created_at)}
                  </span>
                )}
              </span>
            )}
          </div>

          {/* Content area */}
          <div className="flex-1 overflow-y-auto p-4" style={{ background: "var(--bg-base)" }}>
            {currentVersion && (
              editing ? (
                <div className="space-y-2">
                  <FileReferenceTextarea
                    value={editContent}
                    onChange={(nextValue) => { setEditContent(nextValue); setSaveConfirm(null); }}
                    suggestions={fileSuggestions}
                    currentKey={file.key}
                    placeholder="File content..."
                    rows={12}
                    className="w-full px-2 py-1.5 text-[12px] rounded border font-mono resize-y"
                    style={inputStyle}
                    helperText="Type @{ to reference another file."
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
                    <button
                      onClick={handleSaveNewVersion}
                      disabled={saving}
                      className="text-[10px] px-2 py-0.5 rounded border-0 cursor-pointer disabled:opacity-40"
                      style={{ background: "var(--accent)", color: "white" }}
                    >
                      {saving ? "Saving..." : "Save as New Version"}
                    </button>
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
                <pre className="text-[12px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap break-all m-0">
                  {currentVersion.content || "(empty)"}
                </pre>
              )
            )}
          </div>
        </>
      )}
    </div>
  );
}

const inputStyle = {
  background: "var(--bg-base)",
  borderColor: "var(--border)",
  color: "var(--text-primary)",
};

export function FilesPanel({ files, cogentName, onRefresh }: FilesPanelProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<CogosFile | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  // Create form state
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newContent, setNewContent] = useState("");
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const normalizedSearchQuery = deferredSearchQuery.trim().toLowerCase();

  const fileSuggestions = useMemo(
    () => [...files.map((file) => file.key)].sort((a, b) => a.localeCompare(b)),
    [files],
  );

  const filteredFiles = useMemo(() => {
    if (!normalizedSearchQuery) return files;
    return files.filter((file) => matchesFileSearch(file, normalizedSearchQuery));
  }, [files, normalizedSearchQuery]);

  const filteredTree = useMemo(() => buildTree(filteredFiles, getFileGroup), [filteredFiles]);

  const selectedNode = useMemo(() => {
    if (!selectedPath) return null;
    return findNode(filteredTree, selectedPath);
  }, [filteredTree, selectedPath]);

  const visibleSelectedPath = selectedNode ? selectedPath : null;

  const displayItems = useMemo(() => {
    if (!selectedNode) return filteredFiles;
    return getAllItems(selectedNode);
  }, [filteredFiles, selectedNode]);

  // Keep selectedFile in sync with refreshed data
  const activeSelectedFile = useMemo(() => {
    if (!selectedFile) return null;
    const file = files.find((f) => f.id === selectedFile.id) ?? null;
    if (!file) return null;
    return matchesFileSearch(file, normalizedSearchQuery) ? file : null;
  }, [files, selectedFile, normalizedSearchQuery]);

  const handleCreate = useCallback(async () => {
    if (!cogentName || !newKey.trim()) return;
    await createFile(cogentName, {
      key: newKey.trim(),
      content: newContent,
    });
    setCreating(false);
    setNewKey("");
    setNewContent("");
    onRefresh?.();
  }, [cogentName, newKey, newContent, onRefresh]);

  const canMutate = !!cogentName && !!onRefresh;

  return (
    <div style={{ paddingBottom: activeSelectedFile ? "45vh" : undefined }}>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-[var(--text-muted)]">
            {filteredFiles.length}
            {normalizedSearchQuery ? `/${files.length}` : ""} file{filteredFiles.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search keys or includes"
            aria-label="Search files"
            className="w-[280px] max-w-full px-3 py-1.5 text-[12px] rounded border font-mono"
            style={inputStyle}
          />
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
              + New File
            </button>
          )}
        </div>
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
            New File
          </div>
          <div>
            <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
              Key
            </label>
            <input
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              placeholder="group/file-name"
              className="w-full px-2 py-1.5 text-[12px] rounded border font-mono"
              style={inputStyle}
            />
            <div className="text-[9px] text-[var(--text-muted)] mt-1">
              Use / to define path hierarchy
            </div>
          </div>
          <div>
            <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
              Content
            </label>
            <FileReferenceTextarea
              value={newContent}
              onChange={setNewContent}
              suggestions={fileSuggestions}
              currentKey={newKey.trim() || undefined}
              placeholder="File content..."
              rows={5}
              className="w-full px-2 py-1.5 text-[12px] rounded border font-mono resize-y"
              style={inputStyle}
              helperText="Type @{ to reference another file."
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={!newKey.trim()}
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

      {/* Tree + file list */}
      <div
        className="flex gap-0 border rounded-md overflow-hidden"
        style={{ borderColor: "var(--border)", minHeight: "120px" }}
      >
        <HierarchyPanel
          items={filteredFiles}
          getGroup={getFileGroup}
          selectedPath={visibleSelectedPath}
          onSelectPath={setSelectedPath}
        />

        {/* File list */}
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
              {visibleSelectedPath ?? "All"}
            </span>
            <span className="text-[10px] text-[var(--text-muted)]">
              {displayItems.length} file{displayItems.length !== 1 ? "s" : ""}
            </span>
          </div>

          {displayItems.length === 0 ? (
            <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
              No files{visibleSelectedPath ? ` in ${visibleSelectedPath}` : normalizedSearchQuery ? " match the current search" : ""}
            </div>
          ) : (
            <div>
              {displayItems.map((file) => {
                const isSelected = activeSelectedFile?.id === file.id;
                return (
                  <div
                    key={file.id}
                    className="px-4 py-2.5 border-b hover:bg-[var(--bg-hover)] transition-colors cursor-pointer"
                    style={{
                      borderColor: "var(--border)",
                      background: isSelected ? "var(--bg-hover)" : undefined,
                      borderLeft: isSelected ? "2px solid var(--accent)" : "2px solid transparent",
                    }}
                    onClick={() => setSelectedFile(isSelected ? null : file)}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="text-[12px] font-mono font-medium"
                        style={{ color: isSelected ? "var(--accent)" : "var(--text-primary)" }}
                      >
                        {file.key}
                      </span>
                      {file.includes.length > 0 && (
                        <Badge variant="neutral">{file.includes.length} includes</Badge>
                      )}
                      <span className="text-[10px] text-[var(--text-muted)] ml-auto">
                        {fmtTimestamp(file.updated_at)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Version panel — fixed bottom frame */}
      {activeSelectedFile && (
        <div
          className="fixed flex flex-col border-t"
          style={{
            left: "var(--sidebar-w)",
            right: 0,
            bottom: 0,
            height: "40vh",
            borderColor: "var(--border)",
            background: "var(--bg-deep)",
            zIndex: 20,
          }}
        >
          <VersionPanel
            file={activeSelectedFile}
            fileSuggestions={fileSuggestions}
            cogentName={cogentName}
            canMutate={canMutate}
            onRefresh={onRefresh}
            onClose={() => setSelectedFile(null)}
          />
        </div>
      )}
    </div>
  );
}
