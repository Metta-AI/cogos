"use client";

import { useState, useMemo, useCallback } from "react";
import type { Program } from "@/lib/types";
import { Badge } from "@/components/shared/Badge";
import { fmtCost, fmtTimestamp } from "@/lib/format";
import { ExecutionDetail } from "./ExecutionDetail";

interface ProgramsPanelProps {
  programs: Program[];
  cogentName?: string;
}

interface TreeNode {
  name: string;
  path: string;
  programs: Program[];
  children: Map<string, TreeNode>;
}

function buildTree(programs: Program[]): TreeNode {
  const root: TreeNode = { name: "", path: "", programs: [], children: new Map() };

  for (const prog of programs) {
    const group = prog.group || "default";
    const parts = group.split("/").filter(Boolean);

    let node = root;
    let pathSoFar = "";
    for (const part of parts) {
      pathSoFar = pathSoFar ? `${pathSoFar}/${part}` : part;
      if (!node.children.has(part)) {
        node.children.set(part, {
          name: part,
          path: pathSoFar,
          programs: [],
          children: new Map(),
        });
      }
      node = node.children.get(part)!;
    }
    node.programs.push(prog);
  }

  return root;
}

function countAll(node: TreeNode): number {
  let count = node.programs.length;
  for (const child of node.children.values()) {
    count += countAll(child);
  }
  return count;
}

function getAllPrograms(node: TreeNode): Program[] {
  const result = [...node.programs];
  for (const child of node.children.values()) {
    result.push(...getAllPrograms(child));
  }
  return result;
}

function sortedChildren(node: TreeNode): TreeNode[] {
  return [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function typeVariant(type: string) {
  switch (type) {
    case "skill":
      return "accent" as const;
    case "trigger":
      return "warning" as const;
    case "system":
      return "info" as const;
    default:
      return "neutral" as const;
  }
}

interface TreeNodeRowProps {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  expandedPaths: Set<string>;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
}

function TreeNodeRow({ node, depth, selectedPath, expandedPaths, onSelect, onToggle }: TreeNodeRowProps) {
  const hasChildren = node.children.size > 0 || node.programs.length > 0;
  const isExpanded = expandedPaths.has(node.path);
  const isSelected = selectedPath === node.path;
  const total = countAll(node);

  return (
    <div
      className="flex items-center gap-1 py-1 px-2 cursor-pointer transition-colors rounded-sm"
      style={{
        paddingLeft: `${depth * 16 + 8}px`,
        background: isSelected ? "var(--bg-hover)" : "transparent",
        borderLeft: isSelected ? "2px solid var(--accent)" : "2px solid transparent",
      }}
      onClick={() => {
        onSelect(node.path);
        if (hasChildren && !isExpanded) onToggle(node.path);
      }}
    >
      {hasChildren ? (
        <button
          onClick={(e) => { e.stopPropagation(); onToggle(node.path); }}
          className="text-[9px] text-[var(--text-muted)] bg-transparent border-0 cursor-pointer p-0 w-3 flex-shrink-0"
        >
          {isExpanded ? "\u25BC" : "\u25B6"}
        </button>
      ) : (
        <span className="w-3 flex-shrink-0" />
      )}
      <span
        className="text-[12px] font-mono truncate"
        style={{ color: isSelected ? "var(--accent)" : "var(--text-primary)" }}
      >
        {node.name}
      </span>
      <span className="text-[10px] text-[var(--text-muted)] ml-auto flex-shrink-0">
        {total}
      </span>
    </div>
  );
}

function ProgramListItem({
  prog,
  depth = 0,
  isSelected,
  onSelect,
}: {
  prog: Program;
  depth?: number;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const pct = prog.runs > 0 ? ((prog.ok / prog.runs) * 100).toFixed(0) : "0";

  return (
    <div
      className="flex items-center gap-2 px-2 py-1 cursor-pointer transition-colors rounded-sm"
      style={{
        paddingLeft: `${(depth + 1) * 16 + 8}px`,
        background: isSelected ? "var(--bg-hover)" : "transparent",
        borderLeft: isSelected ? "2px solid var(--accent)" : "2px solid transparent",
      }}
      onClick={onSelect}
    >
      <span
        className="text-[11px] font-mono truncate"
        style={{ color: isSelected ? "var(--accent)" : "var(--text-secondary)" }}
      >
        {prog.name}
      </span>
      <span className="text-[9px] text-[var(--text-muted)] ml-auto flex-shrink-0">
        {prog.runs > 0 ? `${pct}%` : "---"}
      </span>
    </div>
  );
}

function TreeGroupNode({
  node,
  depth,
  selectedGroupPath,
  expandedPaths,
  selectedProgram,
  onSelectGroup,
  onToggle,
  onSelectProgram,
}: {
  node: TreeNode;
  depth: number;
  selectedGroupPath: string | null;
  expandedPaths: Set<string>;
  selectedProgram: Program | null;
  onSelectGroup: (path: string) => void;
  onToggle: (path: string) => void;
  onSelectProgram: (prog: Program, groupPath: string) => void;
}) {
  const isExpanded = expandedPaths.has(node.path);
  const children = sortedChildren(node);

  return (
    <>
      <TreeNodeRow
        node={node}
        depth={depth}
        selectedPath={selectedGroupPath}
        expandedPaths={expandedPaths}
        onSelect={onSelectGroup}
        onToggle={onToggle}
      />
      {isExpanded && (
        <>
          {/* Direct programs in this group */}
          {node.programs.map((p) => (
            <ProgramListItem
              key={p.name}
              prog={p}
              depth={depth + 1}
              isSelected={selectedProgram?.name === p.name}
              onSelect={() => onSelectProgram(p, node.path)}
            />
          ))}
          {/* Child groups */}
          {children.map((child) => (
            <TreeGroupNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedGroupPath={selectedGroupPath}
              expandedPaths={expandedPaths}
              selectedProgram={selectedProgram}
              onSelectGroup={onSelectGroup}
              onToggle={onToggle}
              onSelectProgram={onSelectProgram}
            />
          ))}
        </>
      )}
    </>
  );
}

export function ProgramsPanel({
  programs,
  cogentName = "cogent",
}: ProgramsPanelProps) {
  const [selectedGroupPath, setSelectedGroupPath] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [selectedProgram, setSelectedProgram] = useState<Program | null>(null);

  const tree = useMemo(() => buildTree(programs), [programs]);

  const toggleExpanded = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const selectedNode = useMemo(() => {
    if (!selectedGroupPath) return null;
    const parts = selectedGroupPath.split("/");
    let node = tree;
    for (const part of parts) {
      const child = node.children.get(part);
      if (!child) return null;
      node = child;
    }
    return node;
  }, [tree, selectedGroupPath]);

  const displayPrograms = useMemo(() => {
    if (!selectedNode) return programs;
    return getAllPrograms(selectedNode);
  }, [selectedNode, programs]);

  const children = sortedChildren(tree);

  const prog = selectedProgram;

  return (
    <div className="flex flex-col h-full" style={{ minHeight: "calc(100vh - 160px)" }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] text-[var(--text-muted)]">
          {programs.length} program{programs.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Split pane: tree left, detail right */}
      <div className="flex gap-0 flex-1 min-h-0 border rounded-md overflow-hidden" style={{ borderColor: "var(--border)" }}>
        {/* Left: hierarchy tree + program list */}
        <div
          className="flex-shrink-0 overflow-y-auto border-r py-2"
          style={{
            width: "220px",
            background: "var(--bg-surface)",
            borderColor: "var(--border)",
          }}
        >
          {/* "All" root entry */}
          <div
            className="flex items-center gap-1 py-1 px-2 cursor-pointer transition-colors rounded-sm"
            style={{
              paddingLeft: "8px",
              background: selectedGroupPath === null && !selectedProgram ? "var(--bg-hover)" : "transparent",
              borderLeft: selectedGroupPath === null && !selectedProgram ? "2px solid var(--accent)" : "2px solid transparent",
            }}
            onClick={() => { setSelectedGroupPath(null); setSelectedProgram(null); }}
          >
            <span className="w-3 flex-shrink-0" />
            <span
              className="text-[12px] font-mono"
              style={{ color: selectedGroupPath === null && !selectedProgram ? "var(--accent)" : "var(--text-primary)" }}
            >
              All
            </span>
            <span className="text-[10px] text-[var(--text-muted)] ml-auto flex-shrink-0">
              {programs.length}
            </span>
          </div>

          {children.map((child) => (
            <TreeGroupNode
              key={child.path}
              node={child}
              depth={0}
              selectedGroupPath={selectedGroupPath}
              expandedPaths={expandedPaths}
              selectedProgram={selectedProgram}
              onSelectGroup={(path) => { setSelectedGroupPath(path); setSelectedProgram(null); }}
              onToggle={toggleExpanded}
              onSelectProgram={(p, path) => { setSelectedProgram(p); setSelectedGroupPath(path); }}
            />
          ))}

          {children.length === 0 && (
            <div className="text-[11px] text-[var(--text-muted)] text-center py-4">
              No groups
            </div>
          )}
        </div>

        {/* Right: detail view */}
        <div
          className="flex-1 overflow-y-auto flex flex-col"
          style={{ background: "var(--bg-base)" }}
        >
          {prog ? (
            /* ---- Single program selected ---- */
            <>
              {/* Top: Stats & Metadata */}
              <div
                className="px-4 py-3 border-b"
                style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[13px] font-mono font-semibold text-[var(--text-primary)]">
                    {prog.name}
                  </span>
                  <Badge variant={typeVariant(prog.type)}>{prog.type}</Badge>
                  {prog.group && prog.group !== "default" && (
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">{prog.group}</span>
                  )}
                </div>

                <div className="grid grid-cols-4 gap-3">
                  <div>
                    <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide">Runs</div>
                    <div className="text-[13px] font-mono text-[var(--text-primary)]">{prog.runs}</div>
                  </div>
                  <div>
                    <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide">Success</div>
                    <div className="text-[13px] font-mono">
                      <span className="text-[#22c55e]">{prog.ok}</span>
                      {prog.fail > 0 && <span className="text-[var(--error)]"> / {prog.fail}</span>}
                      {prog.runs > 0 && (
                        <span className="text-[var(--text-muted)] text-[10px] ml-1">
                          ({((prog.ok / prog.runs) * 100).toFixed(0)}%)
                        </span>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide">Cost</div>
                    <div className="text-[13px] font-mono text-[var(--text-primary)]">
                      {prog.total_cost > 0 ? fmtCost(prog.total_cost) : "---"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide">Last Run</div>
                    <div className="text-[11px] font-mono text-[var(--text-muted)]">
                      {prog.last_run ? fmtTimestamp(prog.last_run) : "never"}
                    </div>
                  </div>
                </div>

                {(prog.model || prog.complexity || prog.trigger_count > 0) && (
                  <div className="flex items-center gap-3 mt-2 pt-2 border-t" style={{ borderColor: "var(--border)" }}>
                    {prog.model && (
                      <span className="text-[10px] font-mono text-[var(--text-muted)]">
                        {prog.model}
                      </span>
                    )}
                    {prog.complexity && (
                      <Badge variant="neutral">{prog.complexity}</Badge>
                    )}
                    {prog.trigger_count > 0 && (
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {prog.trigger_count} trigger{prog.trigger_count !== 1 ? "s" : ""}
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Middle: Recent Runs (max 10) */}
              <div className="flex-1 min-h-0 border-b" style={{ borderColor: "var(--border)" }}>
                <ExecutionDetail programName={prog.name} cogentName={cogentName} />
              </div>

              {/* Bottom: Content / Description */}
              <div className="px-4 py-3" style={{ background: "var(--bg-surface)" }}>
                <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide mb-1">
                  Description
                </div>
                <div className="text-[12px] text-[var(--text-secondary)] font-mono whitespace-pre-wrap">
                  {prog.description || "No description"}
                </div>
              </div>
            </>
          ) : (
            /* ---- Group overview / all programs list ---- */
            <>
              <div
                className="sticky top-0 z-10 px-4 py-2 border-b flex items-center gap-2"
                style={{ background: "var(--bg-surface)", borderColor: "var(--border)" }}
              >
                <span className="text-[12px] font-mono font-medium text-[var(--text-primary)]">
                  {selectedGroupPath ?? "All"}
                </span>
                <span className="text-[10px] text-[var(--text-muted)]">
                  {displayPrograms.length} program{displayPrograms.length !== 1 ? "s" : ""}
                </span>
              </div>

              {displayPrograms.length === 0 ? (
                <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
                  No programs{selectedGroupPath ? ` in ${selectedGroupPath}` : ""}
                </div>
              ) : (
                <div>
                  {displayPrograms.map((p) => {
                    const pct = p.runs > 0 ? ((p.ok / p.runs) * 100).toFixed(0) : "0";
                    return (
                      <div
                        key={p.name}
                        className="flex items-center gap-3 px-4 py-2 cursor-pointer transition-colors border-b"
                        style={{ borderColor: "var(--border)" }}
                        onClick={() => setSelectedProgram(p)}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                      >
                        <span className="font-mono text-[12px] text-[var(--text-primary)] font-medium">
                          {p.name}
                        </span>
                        <Badge variant={typeVariant(p.type)}>{p.type}</Badge>
                        {p.description && (
                          <span className="text-[11px] text-[var(--text-muted)] truncate max-w-[300px]">
                            {p.description}
                          </span>
                        )}
                        <div className="flex-1" />
                        <span className="font-mono text-[10px] text-[var(--text-muted)]">
                          {p.runs > 0 ? (
                            <>
                              <span className="text-[#22c55e]">{p.ok}</span>
                              {p.fail > 0 && <span className="text-[var(--error)]">/{p.fail}</span>}
                              <span className="text-[var(--text-muted)]"> ({pct}%)</span>
                            </>
                          ) : (
                            <span>0 runs</span>
                          )}
                        </span>
                        {p.total_cost > 0 && (
                          <span className="font-mono text-[10px] text-[var(--text-muted)]">{fmtCost(p.total_cost)}</span>
                        )}
                        <span className="text-[10px] text-[var(--text-muted)]" style={{ minWidth: "60px", textAlign: "right" }}>
                          {fmtTimestamp(p.last_run)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
