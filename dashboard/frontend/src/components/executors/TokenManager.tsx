"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createExecutorToken,
  listExecutorTokens,
  revokeExecutorToken,
  type CreateTokenResult,
  type ExecutorTokenItem,
} from "@/lib/api";
import { Badge } from "@/components/shared/Badge";
import { fmtTimestamp } from "@/lib/format";

interface TokenManagerProps {
  cogentName: string;
}

function CcDropdown({
  cogentName,
  copiedId,
  onCopy,
}: {
  cogentName: string;
  copiedId: string | null;
  onCopy: (text: string, id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const host = typeof window !== "undefined" ? window.location.host : "";
  const address = `${cogentName}.${host}`;
  const ccCommand = `/cogos:cogent ${address}`;

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-bold font-mono bg-[var(--accent-glow-strong)] text-[var(--accent)] hover:opacity-80 transition-opacity cursor-pointer border-0"
        title="Claude Code connect options"
      >
        cc
      </button>
      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-50 bg-[var(--bg-surface)] border border-[var(--border)] rounded-md shadow-lg overflow-hidden"
          style={{ minWidth: "220px" }}
        >
          <button
            onClick={() => {
              onCopy(ccCommand, `cc-${cogentName}`);
              setOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] transition-colors flex items-center gap-2"
          >
            <span className="text-[var(--text-muted)]">
              {copiedId === `cc-${cogentName}` ? "Copied!" : "Copy Claude Code command"}
            </span>
          </button>
          <div className="px-3 py-1.5 border-t border-[var(--border)]">
            <code className="text-[10px] font-mono text-[var(--text-muted)] break-all">
              {ccCommand}
            </code>
          </div>
        </div>
      )}
    </div>
  );
}

function TokenCcDropdown({
  tokenName,
  cogentName,
  tokenRaw,
  copiedId,
  onCopy,
}: {
  tokenName: string;
  cogentName: string;
  tokenRaw: string;
  copiedId: string | null;
  onCopy: (text: string, id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const host = typeof window !== "undefined" ? window.location.host : "";
  const address = `${cogentName}.${host}`;
  const ccCommand = `/cogos:cogent ${address}`;

  const buildLaunchCmd = () => {
    const apiUrl = typeof window !== "undefined" ? window.location.origin : "";
    return `COGOS_API_KEY=${tokenRaw} \\\nCOGOS_API_URL=${apiUrl} \\\nCOGENT=${cogentName} \\\nclaude --dangerously-load-development-channels server:cogos`;
  };

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-bold font-mono bg-[var(--accent-glow-strong)] text-[var(--accent)] hover:opacity-80 transition-opacity cursor-pointer border-0"
        title="Claude Code connect options"
      >
        cc
      </button>
      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-50 bg-[var(--bg-surface)] border border-[var(--border)] rounded-md shadow-lg overflow-hidden"
          style={{ minWidth: "240px" }}
        >
          <button
            onClick={() => {
              onCopy(ccCommand, `cc-cmd-${tokenName}`);
              setOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] transition-colors"
          >
            {copiedId === `cc-cmd-${tokenName}` ? "Copied!" : "Copy Claude Code command"}
          </button>
          <button
            onClick={() => {
              onCopy(buildLaunchCmd(), `cc-launch-${tokenName}`);
              setOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] transition-colors border-t border-[var(--border)]"
          >
            {copiedId === `cc-launch-${tokenName}` ? "Copied!" : "Copy launch command (env vars)"}
          </button>
          <div className="px-3 py-1.5 border-t border-[var(--border)]">
            <code className="text-[10px] font-mono text-[var(--text-muted)] break-all">
              {ccCommand}
            </code>
          </div>
        </div>
      )}
    </div>
  );
}

export function TokenManager({ cogentName }: TokenManagerProps) {
  const [tokens, setTokens] = useState<ExecutorTokenItem[]>([]);
  const [createdToken, setCreatedToken] = useState<CreateTokenResult | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newTokenName, setNewTokenName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listExecutorTokens(cogentName);
      setTokens(data.tokens);
    } catch {
      /* swallow */
    }
  }, [cogentName]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = async () => {
    setCreating(true);
    setError("");
    setCreatedToken(null);
    try {
      const result = await createExecutorToken(cogentName, newTokenName.trim());
      setCreatedToken(result);
      setNewTokenName("");
      setShowCreate(false);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (tokenName: string) => {
    try {
      await revokeExecutorToken(cogentName, tokenName);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const buildCreatedLaunchCmd = (apiKey: string) => {
    const apiUrl = typeof window !== "undefined" ? window.location.origin : "";
    return `COGOS_API_KEY=${apiKey} \\\nCOGOS_API_URL=${apiUrl} \\\nCOGENT=${cogentName} \\\nclaude --dangerously-load-development-channels server:cogos`;
  };

  const buildCreatedCcCommand = () => {
    const host = typeof window !== "undefined" ? window.location.host : "";
    return `/cogos:cogent ${cogentName}.${host}`;
  };

  const activeTokens = tokens.filter((t) => !t.revoked);

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
      <div className="px-4 py-2.5 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">
            API Tokens
          </span>
          <span className="text-[11px] text-[var(--text-muted)]">
            ({activeTokens.length} active)
          </span>
          <CcDropdown cogentName={cogentName} copiedId={copiedId} onCopy={handleCopy} />
        </div>
      </div>

      {/* Show created token (one-time display) */}
      {createdToken && (
        <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--bg-hover)]">
          <div className="text-[12px] font-medium text-[var(--text-primary)] mb-2">
            Token created — copy this now, it won't be shown again:
          </div>
          <div className="mb-2">
            <div className="text-[10px] text-[var(--text-muted)] mb-1 uppercase tracking-wide font-medium">Claude Code command</div>
            <div className="relative">
              <pre className="px-3 py-2 text-[11px] font-mono bg-[var(--bg-base)] border border-[var(--border)] rounded text-[var(--text-secondary)] overflow-x-auto whitespace-pre-wrap break-all">
                {buildCreatedCcCommand()}
              </pre>
              <button
                onClick={() => handleCopy(buildCreatedCcCommand(), "created-cc")}
                className="absolute top-1.5 right-1.5 px-2 py-1 text-[10px] font-medium bg-[var(--bg-surface)] border border-[var(--border)] rounded hover:bg-[var(--bg-hover)] transition-colors"
              >
                {copiedId === "created-cc" ? "Copied!" : "Copy"}
              </button>
            </div>
          </div>
          <div>
            <div className="text-[10px] text-[var(--text-muted)] mb-1 uppercase tracking-wide font-medium">Launch command (env vars)</div>
            <div className="relative">
              <pre className="px-3 py-2 text-[11px] font-mono bg-[var(--bg-base)] border border-[var(--border)] rounded text-[var(--text-secondary)] overflow-x-auto whitespace-pre-wrap break-all">
                {buildCreatedLaunchCmd(createdToken.token)}
              </pre>
              <button
                onClick={() => handleCopy(buildCreatedLaunchCmd(createdToken.token), "created-launch")}
                className="absolute top-1.5 right-1.5 px-2 py-1 text-[10px] font-medium bg-[var(--bg-surface)] border border-[var(--border)] rounded hover:bg-[var(--bg-hover)] transition-colors"
              >
                {copiedId === "created-launch" ? "Copied!" : "Copy"}
              </button>
            </div>
          </div>
          <button
            onClick={() => setCreatedToken(null)}
            className="mt-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div className="px-4 py-2 text-[12px] text-[var(--error)] border-b border-[var(--border)]">
          {error}
        </div>
      )}

      {/* Token list */}
      {tokens.length === 0 && !showCreate ? (
        <div className="px-4 py-6 text-center text-[12px] text-[var(--text-muted)]">
          No tokens yet. Create one to connect Claude Code as an executor.
        </div>
      ) : tokens.length > 0 && (
        <table className="w-full text-left text-[12px]">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="px-4 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Name
              </th>
              <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Status
              </th>
              <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Created
              </th>
              <th className="px-3 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide font-medium">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {tokens.map((t) => (
              <tr
                key={t.name}
                className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors"
                style={{ opacity: t.revoked ? 0.5 : 1 }}
              >
                <td className="px-4 py-2 font-mono text-[var(--text-secondary)]">
                  <span className="inline-flex items-center gap-1.5">
                    {!t.revoked && (
                      <TokenCcDropdown
                        tokenName={t.name}
                        cogentName={cogentName}
                        tokenRaw={t.token_raw || "<YOUR_TOKEN>"}
                        copiedId={copiedId}
                        onCopy={handleCopy}
                      />
                    )}
                    {t.name}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <Badge variant={t.revoked ? "error" : "success"}>
                    {t.revoked ? "revoked" : "active"}
                  </Badge>
                </td>
                <td className="px-3 py-2 text-[var(--text-muted)]">
                  {t.created_at ? fmtTimestamp(t.created_at) : "--"}
                </td>
                <td className="px-3 py-2">
                  {!t.revoked && (
                    <button
                      onClick={() => handleRevoke(t.name)}
                      className="text-[11px] text-[var(--error)] hover:underline"
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Create token: inline expand */}
      <div className="border-t border-[var(--border)]">
        {showCreate ? (
          <div className="px-4 py-2.5 flex items-center gap-2">
            <input
              type="text"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") { setShowCreate(false); setNewTokenName(""); }
              }}
              placeholder="Token name (optional)"
              autoFocus
              className="flex-1 px-2.5 py-1 text-[12px] bg-[var(--bg-base)] border border-[var(--border)] rounded text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
            />
            <button
              onClick={handleCreate}
              disabled={creating}
              className="px-2.5 py-1 text-[12px] font-medium bg-[var(--accent)] text-white rounded hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {creating ? "..." : "Create"}
            </button>
            <button
              onClick={() => { setShowCreate(false); setNewTokenName(""); }}
              className="px-2 py-1 text-[12px] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowCreate(true)}
            className="w-full px-4 py-2 text-[12px] text-[var(--text-muted)] hover:text-[var(--accent)] hover:bg-[var(--bg-hover)] transition-colors text-left"
          >
            + New Token
          </button>
        )}
      </div>
    </div>
  );
}
