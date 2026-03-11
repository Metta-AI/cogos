"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/shared/Badge";
import { StatCard } from "@/components/shared/StatCard";
import * as api from "@/lib/api";
import type { DiscordSetupStatus } from "@/lib/types";

type SetupSection = "discord";

interface SetupPanelProps {
  cogentName: string;
}

function statusLabel(value: boolean | null, ok = "Ready", missing = "Missing", unknown = "Unknown"): string {
  if (value === true) return ok;
  if (value === false) return missing;
  return unknown;
}

function statusVariant(value: boolean | null): "accent" | "warning" | "error" | "default" {
  if (value === true) return "accent";
  if (value === false) return "warning";
  return "default";
}

function nextAction(status: DiscordSetupStatus | null, cogentName: string): { title: string; detail: string; command?: string } {
  if (!status) {
    return {
      title: "Load Discord setup status",
      detail: "The setup guide still applies even if live checks are unavailable.",
    };
  }
  if (!status.cogos_initialized) {
    return {
      title: "Initialize CogOS defaults",
      detail: "Fresh brain bring-up is not enough on its own. Load the default CogOS image first.",
      command: `uv run cogent ${cogentName} cogos reload --yes`,
    };
  }
  if (status.secret_configured !== true) {
    return {
      title: "Store the Discord bot token",
      detail: "The bridge cannot log in until the bot token is present in polis secrets.",
      command: `uv run polis secrets set cogent/${cogentName}/discord --value '{"access_token":"YOUR_BOT_TOKEN"}'`,
    };
  }
  if (status.bridge_service_exists === false) {
    return {
      title: "Deploy the Discord bridge service",
      detail: "This cogent does not have the Discord ECS service yet.",
      command: `uv run cogent ${cogentName} brain update stack`,
    };
  }
  if ((status.bridge_running_count ?? 0) === 0) {
    return {
      title: "Start the Discord bridge",
      detail: "The Discord ECS service exists, but it is currently stopped.",
      command: `uv run cogent ${cogentName} cogos discord start`,
    };
  }
  if (!status.capability_enabled || !status.dm_handler_enabled || !status.mention_handler_enabled) {
    return {
      title: "Restore Discord defaults",
      detail: "The bridge is running, but the default Discord capability or handlers are missing.",
      command: `uv run cogent ${cogentName} cogos reload --yes`,
    };
  }
  return {
    title: "Send a test message",
    detail: "DM the bot directly or @mention it in a server channel. Plain channel chatter will not trigger it.",
  };
}

function Step({ index, title, children }: { index: number; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex w-5 h-5 items-center justify-center rounded-full bg-[var(--accent-glow)] text-[var(--accent)] text-[11px] font-semibold">
          {index}
        </span>
        <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">{title}</h3>
      </div>
      <div className="text-[13px] leading-6 text-[var(--text-secondary)]">{children}</div>
    </div>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="mt-2 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 overflow-x-auto text-[12px] text-[var(--text-secondary)]">
      <code>{children}</code>
    </pre>
  );
}

export function SetupPanel({ cogentName }: SetupPanelProps) {
  const [section, setSection] = useState<SetupSection>("discord");
  const [discord, setDiscord] = useState<DiscordSetupStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getDiscordSetup(cogentName);
      setDiscord(next);
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

  const handlersReady = !!discord?.dm_handler_enabled && !!discord?.mention_handler_enabled;
  const bridgeRunning = (discord?.bridge_running_count ?? 0) > 0;
  const action = useMemo(() => nextAction(discord, cogentName), [discord, cogentName]);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-[18px] font-semibold text-[var(--text-primary)]">Setup</h2>
            <Badge variant={discord?.ready_for_test ? "success" : "warning"}>
              {discord?.ready_for_test ? "Ready to test" : "Needs setup"}
            </Badge>
          </div>
          <p className="text-[13px] text-[var(--text-secondary)] max-w-[720px]">
            Walk through first-run tasks that are easy to miss after a fresh cogent bring-up. Discord only responds to DMs and @mentions.
          </p>
        </div>
        <button
          onClick={refresh}
          className="self-start rounded-md border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] transition-colors"
        >
          {loading ? "Refreshing..." : "Refresh checks"}
        </button>
      </div>

      <div className="inline-flex rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-1">
        <button
          onClick={() => setSection("discord")}
          className="rounded px-3 py-1.5 text-[12px] font-medium transition-colors"
          style={{
            background: section === "discord" ? "var(--accent-glow)" : "transparent",
            color: section === "discord" ? "var(--accent)" : "var(--text-secondary)",
          }}
        >
          Discord
        </button>
      </div>

      {section === "discord" && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard
              value={statusLabel(discord?.cogos_initialized ?? null, "Loaded", "Missing")}
              label="CogOS Defaults"
              variant={statusVariant(discord?.cogos_initialized ?? null)}
            />
            <StatCard
              value={statusLabel(discord?.secret_configured ?? null, "Present", "Missing")}
              label="Discord Secret"
              variant={statusVariant(discord?.secret_configured ?? null)}
            />
            <StatCard
              value={statusLabel(bridgeRunning, "Running", "Stopped", "Unknown")}
              label="Bridge Service"
              variant={statusVariant(discord ? bridgeRunning : null)}
            />
            <StatCard
              value={statusLabel(handlersReady && !!discord?.capability_enabled, "Ready", "Missing")}
              label="Inbound Wiring"
              variant={statusVariant(discord ? handlersReady && !!discord.capability_enabled : null)}
            />
          </div>

          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md p-4">
            <div className="flex items-center gap-2 mb-2">
              <Badge variant={discord?.ready_for_test ? "success" : "warning"}>{action.title}</Badge>
              {discord?.bridge_status && <Badge variant="neutral">{discord.bridge_status}</Badge>}
            </div>
            <p className="text-[13px] text-[var(--text-secondary)]">{action.detail}</p>
            {action.command && <CodeBlock>{action.command}</CodeBlock>}
            {(error || discord?.cogos_error || discord?.secret_check_error || discord?.service_check_error) && (
              <div className="mt-3 text-[12px] text-[var(--warning)] space-y-1">
                {error && <div>Setup status request failed: {error}</div>}
                {discord?.cogos_error && <div>CogOS checks unavailable: {discord.cogos_error}</div>}
                {discord?.secret_check_error && <div>Discord secret check unavailable: {discord.secret_check_error}</div>}
                {discord?.service_check_error && <div>Discord service check unavailable: {discord.service_check_error}</div>}
              </div>
            )}
          </div>

          <Step index={1} title="Create and invite the bot">
            Create a Discord application, add a bot user, enable <span className="font-semibold text-[var(--text-primary)]">Message Content Intent</span>, then invite the bot into the server you want to test in.
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge variant="info">Direct messages work</Badge>
              <Badge variant="info">@mentions work</Badge>
              <Badge variant="warning">Plain channel messages do not</Badge>
            </div>
          </Step>

          <Step index={2} title="Store the bot token in polis secrets">
            The Discord bridge reads the bot token from <span className="font-mono text-[var(--text-primary)]">{discord?.secret_path ?? `cogent/${cogentName}/discord`}</span>.
            <CodeBlock>{`uv run polis secrets set cogent/${cogentName}/discord --value '{"access_token":"YOUR_BOT_TOKEN"}'`}</CodeBlock>
          </Step>

          <Step index={3} title="Start the Discord bridge">
            The bridge is its own ECS service and starts stopped by default.
            <CodeBlock>{`uv run cogent ${cogentName} cogos discord start`}</CodeBlock>
            <CodeBlock>{`uv run cogent ${cogentName} cogos discord status`}</CodeBlock>
          </Step>

          <Step index={4} title="Send a test message">
            Once the secret is present and the bridge is running, test it in one of two ways:
            <ul className="mt-2 list-disc pl-5">
              <li>DM the bot directly</li>
              <li>@mention the bot in a server channel</li>
            </ul>
          </Step>
        </>
      )}
    </div>
  );
}
