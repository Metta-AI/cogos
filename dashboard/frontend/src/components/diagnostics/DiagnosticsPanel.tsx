"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { getDiagnosticsHistory, type DiagnosticRun, type DiagnosticCheck } from "@/lib/api";
import { fmtRelative } from "@/lib/format";

interface DiagnosticsPanelProps {
  cogentName: string;
}

interface FlatCheck {
  category: string;
  checkName: string;
}

export function DiagnosticsPanel({ cogentName }: DiagnosticsPanelProps) {
  const [runs, setRuns] = useState<DiagnosticRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCell, setSelectedCell] = useState<{ category: string; checkName: string; runIdx: number } | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDiagnosticsHistory(cogentName, 10);
      setRuns(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load diagnostics");
    } finally {
      setLoading(false);
    }
  }, [cogentName]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Build the list of all unique checks grouped by category
  const { categories, checksByCategory } = useMemo(() => {
    const checkSet = new Map<string, Set<string>>();
    for (const run of runs) {
      for (const [cat, catData] of Object.entries(run.categories)) {
        if (!checkSet.has(cat)) checkSet.set(cat, new Set());
        for (const diag of catData.diagnostics) {
          for (const ck of diag.checks) {
            checkSet.get(cat)!.add(ck.name);
          }
        }
      }
    }
    const cats = Array.from(checkSet.keys()).sort();
    const byCategory: Record<string, string[]> = {};
    for (const cat of cats) {
      byCategory[cat] = Array.from(checkSet.get(cat)!).sort();
    }
    return { categories: cats, checksByCategory: byCategory };
  }, [runs]);

  // Look up a check result for a given run
  const getCheck = useCallback(
    (run: DiagnosticRun, category: string, checkName: string): DiagnosticCheck | null => {
      const cat = run.categories[category];
      if (!cat) return null;
      for (const diag of cat.diagnostics) {
        for (const ck of diag.checks) {
          if (ck.name === checkName) return ck;
        }
      }
      return null;
    },
    [],
  );

  // Get selected check detail
  const selectedCheck = useMemo(() => {
    if (!selectedCell || !runs[selectedCell.runIdx]) return null;
    const run = runs[selectedCell.runIdx];
    const ck = getCheck(run, selectedCell.category, selectedCell.checkName);
    return { check: ck, run, category: selectedCell.category, checkName: selectedCell.checkName };
  }, [selectedCell, runs, getCheck]);

  if (loading && runs.length === 0) {
    return (
      <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
        Loading diagnostics...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-[var(--error)] text-[13px] py-8 text-center">
        {error}
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="text-[var(--text-muted)] text-[13px] py-8 text-center">
        No diagnostic runs available
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] text-[var(--text-muted)]">
          {runs.length} diagnostic run{runs.length !== 1 ? "s" : ""}
          {runs[0] && (
            <> &middot; latest: {runs[0].summary.pass}/{runs[0].summary.total} pass</>
          )}
        </div>
        <button
          onClick={fetchData}
          className="text-[11px] px-3 py-1 rounded border cursor-pointer transition-colors"
          style={{
            color: "var(--accent)",
            borderColor: "var(--accent)",
            background: "transparent",
          }}
        >
          Refresh
        </button>
      </div>

      <div
        className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-auto"
        style={{ maxHeight: "calc(100vh - 200px)" }}
      >
        <table className="w-full text-left text-[12px]" style={{ borderCollapse: "collapse" }}>
          <thead className="sticky top-0 z-10" style={{ background: "var(--bg-surface)" }}>
            <tr className="border-b border-[var(--border)]">
              <th
                className="px-3 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium sticky left-0 z-20"
                style={{ background: "var(--bg-surface)", minWidth: 180 }}
              >
                Diagnostic
              </th>
              {runs.map((run, i) => (
                <th
                  key={i}
                  className="px-2 py-2 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium text-center"
                  style={{ minWidth: 70 }}
                  title={run.timestamp}
                >
                  {fmtRelative(run.timestamp)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map((cat) => (
              <>
                {/* Category header row */}
                <tr key={`cat-${cat}`} style={{ background: "var(--bg-deep)" }}>
                  <td
                    colSpan={runs.length + 1}
                    className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider sticky left-0"
                    style={{ color: "var(--text-secondary)", background: "var(--bg-deep)" }}
                  >
                    {cat}
                  </td>
                </tr>
                {/* Check rows */}
                {(checksByCategory[cat] ?? []).map((checkName) => (
                  <tr
                    key={`${cat}:${checkName}`}
                    className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                  >
                    <td
                      className="px-3 py-1.5 font-mono text-[var(--text-secondary)] text-[11px] sticky left-0"
                      style={{ background: "var(--bg-surface)" }}
                    >
                      {checkName}
                    </td>
                    {runs.map((run, runIdx) => {
                      const ck = getCheck(run, cat, checkName);
                      const isSelected =
                        selectedCell?.category === cat &&
                        selectedCell?.checkName === checkName &&
                        selectedCell?.runIdx === runIdx;
                      return (
                        <td
                          key={runIdx}
                          className="px-2 py-1.5 text-center cursor-pointer"
                          onClick={() =>
                            setSelectedCell(
                              isSelected ? null : { category: cat, checkName, runIdx },
                            )
                          }
                          style={{
                            background: isSelected ? "var(--accent-glow)" : undefined,
                          }}
                        >
                          {ck == null ? (
                            <span className="text-[var(--text-muted)]">&mdash;</span>
                          ) : ck.status === "pass" ? (
                            <span style={{ color: "var(--success)", fontSize: 14 }}>&#x2714;</span>
                          ) : (
                            <span style={{ color: "var(--error)", fontSize: 14 }}>&#x2718;</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </>
            ))}
          </tbody>
        </table>
      </div>

      {/* Detail panel */}
      {selectedCheck && (
        <div
          className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4 space-y-2"
          style={{ borderColor: "var(--accent)" }}
        >
          <div className="flex items-center justify-between">
            <div className="text-[12px] font-semibold text-[var(--text-primary)]">
              {selectedCheck.category} / {selectedCheck.checkName}
            </div>
            <button
              onClick={() => setSelectedCell(null)}
              className="text-[11px] text-[var(--text-muted)] bg-transparent border-0 cursor-pointer hover:text-[var(--text-secondary)]"
            >
              Close
            </button>
          </div>
          <div className="text-[11px] text-[var(--text-muted)]">
            Run: {selectedCheck.run.timestamp}
            {" "}&middot;{" "}
            {selectedCheck.run.summary.pass}/{selectedCheck.run.summary.total} pass
          </div>
          {selectedCheck.check ? (
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-[12px]">
                <span
                  style={{
                    color:
                      selectedCheck.check.status === "pass"
                        ? "var(--success)"
                        : "var(--error)",
                    fontWeight: 600,
                  }}
                >
                  {selectedCheck.check.status.toUpperCase()}
                </span>
                {selectedCheck.check.ms > 0 && (
                  <span className="text-[var(--text-muted)]">
                    {selectedCheck.check.ms}ms
                  </span>
                )}
              </div>
              {selectedCheck.check.error && (
                <pre
                  className="text-[11px] font-mono p-3 rounded overflow-auto"
                  style={{
                    background: "var(--bg-deep)",
                    color: "var(--error)",
                    maxHeight: 300,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {selectedCheck.check.error}
                </pre>
              )}
              {!selectedCheck.check.error && selectedCheck.check.status === "pass" && (
                <div className="text-[11px] text-[var(--text-muted)]">
                  Check passed with no errors.
                </div>
              )}
            </div>
          ) : (
            <div className="text-[11px] text-[var(--text-muted)]">
              Check was not present in this run.
            </div>
          )}

          {/* Show all checks for this category in this run */}
          <details className="mt-2">
            <summary className="text-[11px] text-[var(--text-muted)] cursor-pointer hover:text-[var(--text-secondary)]">
              All checks in {selectedCheck.category} for this run
            </summary>
            <div className="mt-2 space-y-1">
              {selectedCheck.run.categories[selectedCheck.category]?.diagnostics.map((diag) =>
                diag.checks.map((ck) => (
                  <div
                    key={ck.name}
                    className="flex items-center gap-2 text-[11px] font-mono"
                  >
                    <span
                      style={{
                        color: ck.status === "pass" ? "var(--success)" : "var(--error)",
                      }}
                    >
                      {ck.status === "pass" ? "\u2714" : "\u2718"}
                    </span>
                    <span className="text-[var(--text-secondary)]">{ck.name}</span>
                    {ck.error && (
                      <span className="text-[var(--error)] truncate" style={{ maxWidth: 400 }}>
                        {ck.error}
                      </span>
                    )}
                  </div>
                )),
              )}
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
