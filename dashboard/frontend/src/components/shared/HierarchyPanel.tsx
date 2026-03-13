"use client";

import { useState, useMemo, useCallback, type ReactNode } from "react";

/* ── Generic tree node ── */

export interface TreeNode<T> {
  name: string;
  path: string;
  items: T[];
  children: Map<string, TreeNode<T>>;
}

export function buildTree<T>(items: T[], getGroup: (item: T) => string): TreeNode<T> {
  const root: TreeNode<T> = { name: "", path: "", items: [], children: new Map() };

  for (const item of items) {
    const group = getGroup(item) || "default";
    const parts = group.split("/").filter(Boolean);

    let node = root;
    let pathSoFar = "";
    for (const part of parts) {
      pathSoFar = pathSoFar ? `${pathSoFar}/${part}` : part;
      if (!node.children.has(part)) {
        node.children.set(part, {
          name: part,
          path: pathSoFar,
          items: [],
          children: new Map(),
        });
      }
      node = node.children.get(part)!;
    }
    node.items.push(item);
  }

  return root;
}

export function countAllItems<T>(node: TreeNode<T>): number {
  let count = node.items.length;
  for (const child of node.children.values()) {
    count += countAllItems(child);
  }
  return count;
}

export function getAllItems<T>(node: TreeNode<T>): T[] {
  const result = [...node.items];
  for (const child of node.children.values()) {
    result.push(...getAllItems(child));
  }
  return result;
}

export function sortedChildren<T>(node: TreeNode<T>): TreeNode<T>[] {
  return [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function findNode<T>(tree: TreeNode<T>, path: string): TreeNode<T> | null {
  const parts = path.split("/");
  let node = tree;
  for (const part of parts) {
    const child = node.children.get(part);
    if (!child) return null;
    node = child;
  }
  return node;
}

/* ── Tree node row ── */

interface TreeNodeRowProps<T> {
  node: TreeNode<T>;
  depth: number;
  selectedPath: string | null;
  expandedPaths: Set<string>;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
  renderNodeActions?: (node: TreeNode<T>) => ReactNode;
  renderExtra?: (node: TreeNode<T>, depth: number) => ReactNode;
}

function TreeNodeRow<T>({
  node, depth, selectedPath, expandedPaths, onSelect, onToggle, renderNodeActions, renderExtra,
}: TreeNodeRowProps<T>) {
  const hasChildren = node.children.size > 0;
  const isExpanded = expandedPaths.has(node.path);
  const isSelected = selectedPath === node.path;
  const totalItems = countAllItems(node);
  const children = sortedChildren(node);

  return (
    <>
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
          className="text-[12px] font-mono truncate flex-1 min-w-0"
          style={{ color: isSelected ? "var(--accent)" : "var(--text-primary)" }}
        >
          {node.name}
        </span>
        <span className="text-[10px] text-[var(--text-muted)] flex-shrink-0 tabular-nums">
          {totalItems}
        </span>
        {renderNodeActions && (
          <div
            className="flex items-center flex-shrink-0"
            onClick={(event) => event.stopPropagation()}
          >
            {renderNodeActions(node)}
          </div>
        )}
      </div>
      {isExpanded && renderExtra?.(node, depth)}
      {hasChildren && isExpanded && children.map((child) => (
        <TreeNodeRow
          key={child.path}
          node={child}
          depth={depth + 1}
          selectedPath={selectedPath}
          expandedPaths={expandedPaths}
          onSelect={onSelect}
          onToggle={onToggle}
          renderNodeActions={renderNodeActions}
          renderExtra={renderExtra}
        />
      ))}
    </>
  );
}

/* ── Collapsible hierarchy panel ── */

interface HierarchyPanelProps<T> {
  items: T[];
  getGroup: (item: T) => string;
  selectedPath: string | null;
  onSelectPath: (path: string | null) => void;
  renderNodeActions?: (node: TreeNode<T>) => ReactNode;
  /** Extra content rendered below an expanded group node (e.g. leaf items) */
  renderExtra?: (node: TreeNode<T>, depth: number) => ReactNode;
  /** Override for what counts as "selected" in the All row (e.g. programs also checks selectedProgram) */
  isAllSelected?: boolean;
}

export function HierarchyPanel<T>({
  items, getGroup, selectedPath, onSelectPath, renderNodeActions, renderExtra, isAllSelected,
}: HierarchyPanelProps<T>) {
  const [collapsed, setCollapsed] = useState(false);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());

  const tree = useMemo(() => buildTree(items, getGroup), [items, getGroup]);
  const children = useMemo(() => sortedChildren(tree), [tree]);

  const toggleExpanded = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const allSelected = isAllSelected !== undefined ? isAllSelected : selectedPath === null;

  return (
    <div
      className="flex-shrink-0 overflow-y-auto border-r transition-all"
      style={{
        width: collapsed ? "32px" : "220px",
        background: "var(--bg-surface)",
        borderColor: "var(--border)",
      }}
    >
      {/* Collapse/expand toggle */}
      <div className="flex items-center py-1 border-b" style={{ borderColor: "var(--border)" }}>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="text-[10px] text-[var(--text-muted)] bg-transparent border-0 cursor-pointer px-2 py-0.5 hover:text-[var(--text-primary)] transition-colors text-left w-full"
          title={collapsed ? "Expand tree" : "Collapse tree"}
        >
          {collapsed ? "\u25B6" : "\u25C0"}
        </button>
      </div>

      {!collapsed && (
        <div className="py-1">
          {/* "All" root entry */}
          <div
            className="flex items-center gap-1 py-1 px-2 cursor-pointer transition-colors rounded-sm"
            style={{
              paddingLeft: "8px",
              background: allSelected ? "var(--bg-hover)" : "transparent",
              borderLeft: allSelected ? "2px solid var(--accent)" : "2px solid transparent",
            }}
            onClick={() => onSelectPath(null)}
          >
            <span className="w-3 flex-shrink-0" />
            <span
              className="text-[12px] font-mono"
              style={{ color: allSelected ? "var(--accent)" : "var(--text-primary)" }}
            >
              All
            </span>
            <span className="text-[10px] text-[var(--text-muted)] ml-auto flex-shrink-0">
              {items.length}
            </span>
          </div>

          {children.map((child) => (
            <TreeNodeRow
              key={child.path}
              node={child}
              depth={0}
              selectedPath={selectedPath}
              expandedPaths={expandedPaths}
              onSelect={(path) => onSelectPath(path)}
              onToggle={toggleExpanded}
              renderNodeActions={renderNodeActions}
              renderExtra={renderExtra}
            />
          ))}

          {children.length === 0 && (
            <div className="text-[11px] text-[var(--text-muted)] text-center py-4">
              No groups
            </div>
          )}
        </div>
      )}
    </div>
  );
}
