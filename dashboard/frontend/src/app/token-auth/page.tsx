"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createExecutorToken,
  listExecutorTokens,
  listCogents,
  type ExecutorTokenItem,
} from "@/lib/api";

function useCogentName(override: string | null): string | null {
  const [name, setName] = useState<string | null>(override);
  useEffect(() => {
    if (override) return;
    const hostname = window.location.hostname;
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      if (process.env.NEXT_PUBLIC_COGENT) {
        setName(process.env.NEXT_PUBLIC_COGENT);
        return;
      }
      listCogents()
        .then((r) => setName(r.current || r.cogents[0] || "localhost"))
        .catch(() => setName("localhost"));
    } else {
      setName(hostname.split(".")[0].replace(/-/g, "."));
    }
  }, [override]);
  return name;
}

export default function TokenAuthPage() {
  const [callbackUrl, setCallbackUrl] = useState<string | null>(null);
  const [cogentParam, setCogentParam] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setCallbackUrl(params.get("callback"));
    setCogentParam(params.get("cogent"));
    setReady(true);
  }, []);

  const cogentName = useCogentName(cogentParam);

  if (!ready || !cogentName) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-deep)]">
        <div className="text-[var(--text-muted)] text-sm">Loading...</div>
      </div>
    );
  }

  return <TokenAuthCard cogentName={cogentName} callbackUrl={callbackUrl} />;
}

function TokenAuthCard({
  cogentName,
  callbackUrl,
}: {
  cogentName: string;
  callbackUrl: string | null;
}) {
  const [tokens, setTokens] = useState<ExecutorTokenItem[]>([]);
  const [tokenName, setTokenName] = useState("");
  const [pasteToken, setPasteToken] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [resultToken, setResultToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [autoCreated, setAutoCreated] = useState(false);

  const refreshTokens = useCallback(async () => {
    try {
      const data = await listExecutorTokens(cogentName);
      setTokens(data.tokens.filter((t) => !t.revoked));
    } catch {
      /* ignore */
    }
  }, [cogentName]);

  useEffect(() => {
    refreshTokens();
  }, [refreshTokens]);

  const deliverToken = useCallback(
    (token: string) => {
      if (callbackUrl) {
        setRedirecting(true);
        const url = new URL(callbackUrl);
        url.searchParams.set("token", token);
        window.location.href = url.toString();
      } else {
        setResultToken(token);
      }
    },
    [callbackUrl],
  );

  // Auto-create and deliver token when callback URL is present
  useEffect(() => {
    if (!callbackUrl || autoCreated) return;
    setAutoCreated(true);
    setCreating(true);
    const name = `claude-code-${Date.now()}`;
    createExecutorToken(cogentName, name)
      .then((result) => {
        deliverToken(result.token);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
        setCreating(false);
      });
  }, [callbackUrl, cogentName, deliverToken, autoCreated]);

  const handleCreate = async () => {
    setCreating(true);
    setError("");
    try {
      const name = tokenName.trim() || `claude-code-${Date.now()}`;
      const result = await createExecutorToken(cogentName, name);
      setTokenName("");
      await refreshTokens();
      deliverToken(result.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  const handlePaste = () => {
    const trimmed = pasteToken.trim();
    if (!trimmed) {
      setError("Please enter a token");
      return;
    }
    setError("");
    deliverToken(trimmed);
  };

  const handleCopy = () => {
    if (resultToken) {
      navigator.clipboard.writeText(resultToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (redirecting || (callbackUrl && creating && !error)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-deep)]">
        <div className="text-[var(--text-muted)] text-sm">
          {redirecting ? "Redirecting to Claude Code..." : "Creating token..."}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg-deep)] p-4">
      <div className="w-full max-w-md">
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="px-6 pt-6 pb-4 text-center border-b border-[var(--border)]">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--accent-glow-strong)] mb-3">
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--accent)"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">
              Connect Claude Code to CogOS
            </h1>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              Cogent:{" "}
              <span className="font-mono text-[var(--accent)]">
                {cogentName}
              </span>
            </p>
          </div>

          <div className="px-6 py-5 space-y-5">
            {error && (
              <div className="px-3 py-2 text-xs text-[var(--error)] bg-[rgba(239,68,68,0.08)] border border-[rgba(239,68,68,0.2)] rounded">
                {error}
              </div>
            )}

            {/* Success: show token for copy */}
            {resultToken && !callbackUrl && (
              <div className="space-y-3">
                <div className="px-3 py-2 text-xs text-[var(--success)] bg-[rgba(34,197,94,0.08)] border border-[rgba(34,197,94,0.2)] rounded">
                  Token created successfully. Copy it now — it will not be shown
                  again.
                </div>
                <div className="relative">
                  <pre className="px-3 py-2.5 text-xs font-mono bg-[var(--bg-base)] border border-[var(--border)] rounded text-[var(--text-secondary)] break-all whitespace-pre-wrap pr-16">
                    {resultToken}
                  </pre>
                  <button
                    onClick={handleCopy}
                    className="absolute top-1.5 right-1.5 px-2.5 py-1 text-xs font-medium bg-[var(--bg-surface)] border border-[var(--border)] rounded hover:bg-[var(--bg-hover)] transition-colors text-[var(--text-secondary)]"
                  >
                    {copied ? "Copied!" : "Copy"}
                  </button>
                </div>
                <button
                  onClick={() => {
                    setResultToken(null);
                    setError("");
                  }}
                  className="text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
                >
                  Create another token
                </button>
              </div>
            )}

            {/* Main actions (hidden once a token is shown) */}
            {!resultToken && (
              <>
                {/* Option A: Create new token */}
                <div className="space-y-2">
                  <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wide">
                    Create new token
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={tokenName}
                      onChange={(e) => setTokenName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleCreate();
                      }}
                      placeholder="Token name (optional)"
                      className="flex-1 px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border)] rounded text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] transition-colors"
                    />
                    <button
                      onClick={handleCreate}
                      disabled={creating}
                      className="px-4 py-2 text-sm font-medium bg-[var(--accent)] text-[var(--bg-deep)] rounded hover:opacity-90 disabled:opacity-50 transition-opacity whitespace-nowrap"
                    >
                      {creating ? "Creating..." : "Create Token"}
                    </button>
                  </div>
                </div>

                {/* Divider */}
                <div className="flex items-center gap-3">
                  <div className="flex-1 h-px bg-[var(--border)]" />
                  <span className="text-xs text-[var(--text-muted)]">or</span>
                  <div className="flex-1 h-px bg-[var(--border)]" />
                </div>

                {/* Option B: Paste existing token */}
                <div className="space-y-2">
                  <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wide">
                    Use existing token
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={pasteToken}
                      onChange={(e) => setPasteToken(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handlePaste();
                      }}
                      placeholder="Paste your token"
                      className="flex-1 px-3 py-2 text-sm font-mono bg-[var(--bg-base)] border border-[var(--border)] rounded text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] transition-colors"
                    />
                    <button
                      onClick={handlePaste}
                      className="px-4 py-2 text-sm font-medium border border-[var(--border)] text-[var(--text-secondary)] rounded hover:bg-[var(--bg-hover)] transition-colors whitespace-nowrap"
                    >
                      Connect
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Existing tokens list */}
          {tokens.length > 0 && (
            <div className="border-t border-[var(--border)]">
              <div className="px-6 py-2.5">
                <div className="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wide mb-2">
                  Active tokens ({tokens.length})
                </div>
                <div className="space-y-1">
                  {tokens.map((t) => (
                    <div
                      key={t.name}
                      className="flex items-center justify-between px-2 py-1.5 text-xs rounded hover:bg-[var(--bg-hover)] transition-colors"
                    >
                      <span className="font-mono text-[var(--text-secondary)]">
                        {t.name}
                      </span>
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {t.created_at
                          ? new Date(t.created_at).toLocaleDateString()
                          : ""}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Footer */}
          <div className="px-6 py-3 border-t border-[var(--border)] text-center">
            <p className="text-[10px] text-[var(--text-muted)]">
              Tokens grant executor access to this cogent.{" "}
              {callbackUrl
                ? "The token will be sent back to Claude Code automatically."
                : "Copy the token and paste it into Claude Code."}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
