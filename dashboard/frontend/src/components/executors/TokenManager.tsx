"use client";

import { useCallback, useEffect, useState } from "react";
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

  const buildLaunchCmd = (apiKey: string) => {
    const apiUrl = window.location.origin;
    return `COGOS_API_KEY=${apiKey} \\\nCOGOS_API_URL=${apiUrl} \\\nCOGENT=${cogentName} \\\nclaude --dangerously-load-development-channels server:cogos`;
  };

  const activeTokens = tokens.filter((t) => !t.revoked);

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md overflow-hidden">
      <div className="px-4 py-2.5 border-b border-[var(--border)] flex items-center justify-between">
        <div>
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">
            API Tokens
          </span>
          <span className="text-[11px] text-[var(--text-muted)] ml-2">
            ({activeTokens.length} active)
          </span>
        </div>
      </div>

      {/* Show created token (one-time display) */}
      {createdToken && (
        <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--bg-hover)]">
          <div className="text-[12px] font-medium text-[var(--text-primary)] mb-2">
            Token created — copy this now, it won't be shown again:
          </div>
          <div className="relative">
            <pre className="px-3 py-2 text-[11px] font-mono bg-[var(--bg-base)] border border-[var(--border)] rounded text-[var(--text-secondary)] overflow-x-auto whitespace-pre-wrap break-all">
              {buildLaunchCmd(createdToken.token)}
            </pre>
            <button
              onClick={() => handleCopy(buildLaunchCmd(createdToken.token), "created")}
              className="absolute top-1.5 right-1.5 px-2 py-1 text-[10px] font-medium bg-[var(--bg-surface)] border border-[var(--border)] rounded hover:bg-[var(--bg-hover)] transition-colors"
            >
              {copiedId === "created" ? "Copied!" : "Copy"}
            </button>
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
                      <button
                        onClick={() => handleCopy(buildLaunchCmd(t.token_raw || "<YOUR_TOKEN>"), `cmd-${t.name}`)}
                        className="text-[11px] text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors"
                        title="Copy launch command"
                      >
                        {copiedId === `cmd-${t.name}` ? "✓" : "📋"}
                      </button>
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
