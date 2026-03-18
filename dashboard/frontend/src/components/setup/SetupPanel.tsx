"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/shared/Badge";
import * as api from "@/lib/api";
import type {
  ChannelSetup,
  SetupAction,
  SetupResponse,
  SetupStatus,
  SetupStep,
} from "@/lib/types";

interface SetupPanelProps {
  cogentName: string;
}

function statusLabel(status: SetupStatus, readyForTest = false): string {
  if (readyForTest) return "Ready to test";
  if (status === "ready") return "Ready";
  if (status === "manual") return "Manual";
  if (status === "unknown") return "Checks unavailable";
  return "Needs setup";
}

function statusVariant(status: SetupStatus, readyForTest = false): "success" | "warning" | "info" | "neutral" {
  if (readyForTest || status === "ready") return "success";
  if (status === "manual") return "info";
  if (status === "unknown") return "neutral";
  return "warning";
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="mt-2 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 overflow-x-auto text-[12px] text-[var(--text-secondary)]">
      <code>{children}</code>
    </pre>
  );
}

function ActionBlock({ action }: { action: SetupAction | null }) {
  if (!action) return null;

  return (
    <div className="mt-3 space-y-2">
      {action.href && (
        <a
          href={action.href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center rounded-md border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--accent)] hover:bg-[var(--bg-hover)] transition-colors"
        >
          {action.label}
        </a>
      )}
      {action.command && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">{action.label}</div>
          <CodeBlock>{action.command}</CodeBlock>
        </div>
      )}
    </div>
  );
}

function StepCard({ index, step }: { index: number; step: SetupStep }) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex w-5 h-5 items-center justify-center rounded-full bg-[var(--accent-glow)] text-[var(--accent)] text-[11px] font-semibold">
              {index}
            </span>
            <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">{step.title}</h3>
          </div>
          <p className="text-[13px] leading-6 text-[var(--text-secondary)]">{step.description}</p>
          {step.detail && (
            <p className="mt-2 whitespace-pre-line text-[12px] leading-5 text-[var(--text-muted)]">{step.detail}</p>
          )}
          <ActionBlock action={step.action} />
        </div>
        <Badge variant={statusVariant(step.status)}>{statusLabel(step.status)}</Badge>
      </div>
    </div>
  );
}

function ProfileEditor({ cogentName, step, onSaved }: { cogentName: string; step: SetupStep; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [discordHandle, setDiscordHandle] = useState("");
  const [discordUserId, setDiscordUserId] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [initial, setInitial] = useState({ name: "", discordHandle: "", discordUserId: "" });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    api.getIdentity(cogentName).then((id) => {
      setName(id.cogent_name);
      setDiscordHandle(id.discord_handle);
      setDiscordUserId(id.discord_user_id);
      setInitial({ name: id.cogent_name, discordHandle: id.discord_handle, discordUserId: id.discord_user_id });
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, [cogentName]);

  const hasChanges = name !== initial.name || discordHandle !== initial.discordHandle || discordUserId !== initial.discordUserId;

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const result = await api.putIdentity(cogentName, {
        cogent_name: name,
        discord_handle: discordHandle,
        discord_user_id: discordUserId,
      });
      setInitial({ name: result.cogent_name, discordHandle: result.discord_handle, discordUserId: result.discord_user_id });
      onSaved();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]";
  const emptyBorder = "border-[var(--warning)]";

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
      <div className="flex items-center gap-2 mb-4">
        <span className="inline-flex w-5 h-5 items-center justify-center rounded-full bg-[var(--accent-glow)] text-[var(--accent)] text-[11px] font-semibold">
          1
        </span>
        <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">{step.title}</h3>
        <Badge variant={statusVariant(step.status)}>{statusLabel(step.status)}</Badge>
      </div>
      <p className="text-[13px] leading-6 text-[var(--text-secondary)] mb-1">Identity secrets used by capabilities at runtime. Changes take effect on next reboot.</p>
      <p className="text-[11px] text-[var(--text-muted)] mb-4">Stored in AWS Secrets Manager under <code className="text-[11px]">cogent/{cogentName}/...</code></p>

      {!loaded ? (
        <p className="text-[12px] text-[var(--text-muted)]">Loading secrets...</p>
      ) : (
        <div className="space-y-3 max-w-md">
          <div>
            <label className="block text-[12px] font-medium text-[var(--text-secondary)] mb-1">Cogent Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. dr.alpha"
              className={`${inputClass} ${!name ? emptyBorder : ""}`} />
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">cogent/{cogentName}/identity/name</p>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-[var(--text-secondary)] mb-1">Discord Handle</label>
            <input type="text" value={discordHandle} onChange={(e) => setDiscordHandle(e.target.value)} placeholder="e.g. dr.alpha"
              className={`${inputClass} ${!discordHandle ? emptyBorder : ""}`} />
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">cogent/{cogentName}/discord/handle</p>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-[var(--text-secondary)] mb-1">Discord User ID</label>
            <input type="text" value={discordUserId} onChange={(e) => setDiscordUserId(e.target.value)} placeholder="e.g. 1477537399365046415"
              className={`${inputClass} ${!discordUserId ? emptyBorder : ""}`} />
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">cogent/{cogentName}/discord/user_id</p>
          </div>
        </div>
      )}

      {saveError && <p className="mt-3 text-[12px] text-[var(--warning)]">{saveError}</p>}

      <div className="mt-4 flex items-center gap-3">
        <button onClick={handleSave} disabled={saving || !hasChanges || !loaded}
          className="rounded-md bg-[var(--accent)] px-4 py-2 text-[12px] font-medium text-white hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed">
          {saving ? "Saving..." : "Save to secrets"}
        </button>
        {loaded && !hasChanges && (
          <span className="text-[12px] text-[var(--text-muted)]">No changes</span>
        )}
      </div>
    </div>
  );
}

export function SetupPanel({ cogentName }: SetupPanelProps) {
  const [setup, setSetup] = useState<SetupResponse | null>(null);
  const [activeChannelKey, setActiveChannelKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getSetup(cogentName);
      setSetup(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load setup status");
    } finally {
      setLoading(false);
    }
  }, [cogentName]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!setup?.channels.length) {
      setActiveChannelKey(null);
      return;
    }
    if (!activeChannelKey || !setup.channels.some((channel) => channel.key === activeChannelKey)) {
      setActiveChannelKey(setup.channels[0].key);
    }
  }, [setup, activeChannelKey]);

  const activeChannel = useMemo<ChannelSetup | null>(() => {
    if (!setup?.channels.length) return null;
    return setup.channels.find((channel) => channel.key === activeChannelKey) ?? setup.channels[0];
  }, [setup, activeChannelKey]);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-[18px] font-semibold text-[var(--text-primary)]">Setup</h2>
            {activeChannel && (
              <Badge variant={statusVariant(activeChannel.status, activeChannel.ready_for_test)}>
                {statusLabel(activeChannel.status, activeChannel.ready_for_test)}
              </Badge>
            )}
          </div>
          <p className="text-[13px] text-[var(--text-secondary)] max-w-[720px]">
            Walk through first-run tasks that are easy to miss after a fresh cogent bring-up.
          </p>
        </div>
        <button
          onClick={refresh}
          className="self-start rounded-md border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] transition-colors"
        >
          {loading ? "Refreshing..." : "Refresh checks"}
        </button>
      </div>

      {!!setup?.channels.length && (
        <div className="inline-flex rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-1">
          {setup.channels.map((channel) => (
            <button
              key={channel.key}
              onClick={() => setActiveChannelKey(channel.key)}
              className="rounded px-3 py-1.5 text-[12px] font-medium transition-colors"
              style={{
                background: activeChannel?.key === channel.key ? "var(--accent-glow)" : "transparent",
                color: activeChannel?.key === channel.key ? "var(--accent)" : "var(--text-secondary)",
              }}
            >
              {channel.title}
            </button>
          ))}
        </div>
      )}

      {!loading && !activeChannel && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4 text-[13px] text-[var(--text-secondary)]">
          No setup tracks are available for this cogent yet.
        </div>
      )}

      {activeChannel && (
        <>
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">{activeChannel.title}</h3>
              <Badge variant={statusVariant(activeChannel.status, activeChannel.ready_for_test)}>
                {statusLabel(activeChannel.status, activeChannel.ready_for_test)}
              </Badge>
            </div>
            <p className="text-[13px] text-[var(--text-secondary)]">{activeChannel.description}</p>
            <p className="mt-2 text-[13px] text-[var(--text-muted)]">{activeChannel.summary}</p>
            {(error || activeChannel.diagnostics.length > 0) && (
              <div className="mt-3 text-[12px] text-[var(--warning)] space-y-1">
                {error && <div>Setup status request failed: {error}</div>}
                {activeChannel.diagnostics.map((diagnostic) => (
                  <div key={diagnostic}>{diagnostic}</div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-3">
            {activeChannel.steps.map((step, index) => {
              if (activeChannel.key === "profile" && step.key === "edit-profile") {
                return <ProfileEditor key={step.key} cogentName={cogentName} step={step} onSaved={refresh} />;
              }
              return <StepCard key={step.key} index={index + 1} step={step} />;
            })}
          </div>
        </>
      )}
    </div>
  );
}
