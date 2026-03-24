"use client";

import { useState, useEffect, useCallback, useMemo, Fragment } from "react";
import { getDiagnosticsHistory, rerunDiagnostics, type DiagnosticRun, type DiagnosticCheck } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { ResizableBottomPanel } from "@/components/shared/ResizableBottomPanel";

interface DiagnosticsPanelProps {
  cogentName: string;
}

export function DiagnosticsPanel({ cogentName }: DiagnosticsPanelProps) {
  const [runs, setRuns] = useState<DiagnosticRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRunIdx, setSelectedRunIdx] = useState<number | null>(null);
  const [running, setRunning] = useState(false);

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

  const handleRun = useCallback(async () => {
    setRunning(true);
    try {
      await rerunDiagnostics(cogentName);
    } catch {
      // ignore — diagnostics will show up on next refresh
    } finally {
      setRunning(false);
      setTimeout(() => fetchData(), 3000);
    }
  }, [cogentName, fetchData]);

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

  const selectedRun = selectedRunIdx !== null ? runs[selectedRunIdx] ?? null : null;

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
        <div className="flex items-center gap-2">
          <button
            onClick={handleRun}
            disabled={running}
            className="text-[11px] px-3 py-1 rounded border cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              color: "var(--success)",
              borderColor: "var(--success)",
              background: "transparent",
            }}
          >
            {running ? "Triggering..." : "Run"}
          </button>
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
      </div>

      <div
        className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-auto"
        style={{ maxHeight: selectedRun ? "calc(100vh - 400px)" : "calc(100vh - 200px)" }}
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
                  className="px-2 py-2 text-[10px] uppercase tracking-wide font-medium text-center cursor-pointer"
                  style={{
                    minWidth: 70,
                    color: selectedRunIdx === i ? "var(--accent)" : "var(--text-muted)",
                    background: selectedRunIdx === i ? "var(--accent-glow)" : undefined,
                  }}
                  title={run.timestamp}
                  onClick={() => setSelectedRunIdx(selectedRunIdx === i ? null : i)}
                >
                  {fmtRelative(run.timestamp)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map((cat) => (
              <Fragment key={cat}>
                {/* Category header row */}
                <tr style={{ background: "var(--bg-deep)" }}>
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
                      return (
                        <td
                          key={runIdx}
                          className="px-2 py-1.5 text-center cursor-pointer"
                          onClick={() =>
                            setSelectedRunIdx(selectedRunIdx === runIdx ? null : runIdx)
                          }
                          style={{
                            background: selectedRunIdx === runIdx ? "var(--accent-glow)" : undefined,
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
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {/* Detail panel — resizable bottom panel like file content */}
      {selectedRun && (
        <ResizableBottomPanel defaultHeight={300} minHeight={150}>
          <div className="p-4 overflow-y-auto h-full">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[12px] font-semibold text-[var(--text-primary)]">
                Run: {selectedRun.timestamp}
                <span className="ml-2 font-normal text-[var(--text-muted)]">
                  {selectedRun.summary.pass}/{selectedRun.summary.total} pass
                  {selectedRun.summary.fail > 0 && (
                    <span style={{ color: "var(--error)" }}>
                      {" "}&middot; {selectedRun.summary.fail} failed
                    </span>
                  )}
                </span>
              </div>
              <button
                onClick={() => setSelectedRunIdx(null)}
                className="text-[11px] text-[var(--text-muted)] bg-transparent border-0 cursor-pointer hover:text-[var(--text-secondary)]"
              >
                Close
              </button>
            </div>

            <div className="space-y-3">
              {categories.map((cat) => {
                const catData = selectedRun.categories[cat];
                if (!catData) return null;
                const allChecks = catData.diagnostics.flatMap((d) => d.checks);
                const catPass = allChecks.filter((c) => c.status === "pass").length;
                const catFail = allChecks.length - catPass;
                return (
                  <div key={cat}>
                    <div
                      className="text-[10px] font-semibold uppercase tracking-wider mb-1 flex items-center gap-2"
                      style={{ color: catFail > 0 ? "var(--error)" : "var(--text-secondary)" }}
                    >
                      {cat}
                      <span className="text-[var(--text-muted)] font-normal normal-case tracking-normal">
                        {catPass}/{allChecks.length}
                      </span>
                    </div>
                    <div className="space-y-0.5 ml-2">
                      {allChecks.map((ck) => (
                        <div
                          key={`${cat}:${ck.name}`}
                          className="flex items-start gap-2 text-[11px] font-mono"
                        >
                          <span
                            className="flex-shrink-0"
                            style={{
                              color: ck.status === "pass" ? "var(--success)" : "var(--error)",
                            }}
                          >
                            {ck.status === "pass" ? "\u2714" : "\u2718"}
                          </span>
                          <span className="text-[var(--text-secondary)]">{ck.name}</span>
                          {ck.ms > 0 && (
                            <span className="text-[var(--text-muted)]">{ck.ms}ms</span>
                          )}
                          {ck.error && (
                            <span
                              className="text-[var(--error)]"
                              style={{ wordBreak: "break-word" }}
                            >
                              — {ck.error}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </ResizableBottomPanel>
      )}
    </div>
  );
}
