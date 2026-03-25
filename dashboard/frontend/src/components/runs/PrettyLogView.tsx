"use client";

import { useMemo, useState } from "react";
import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import type { CogosRunLogEntry } from "@/lib/types";
import { fmtTime, fmtNum } from "@/lib/format";

hljs.registerLanguage("python", python);

interface StepPayload {
  type?: string;
  turn_number?: number;
  stop_reason?: string;
  final_stop_reason?: string;
  input_tokens?: number;
  output_tokens?: number;
  status?: string;
  message?: { role: string; content: ContentBlock[] };
  [key: string]: unknown;
}

type ContentBlock =
  | { text: string }
  | { toolUse: { toolUseId: string; name: string; input: Record<string, unknown> } }
  | { toolResult: { toolUseId: string; content: { text: string }[] } };

interface ParsedEntry {
  header: string;
  payload: StepPayload | null;
  timestamp: string;
  originalMessage: string;
}

function parseEntry(entry: CogosRunLogEntry): ParsedEntry {
  const msg = entry.message;
  const headerEnd = msg.indexOf("\n");
  const header = headerEnd >= 0 ? msg.substring(0, headerEnd) : msg;
  const rest = headerEnd >= 0 ? msg.substring(headerEnd + 1) : "";

  const jsonStart = rest.indexOf("{");
  const jsonEnd = rest.lastIndexOf("}");
  let payload: StepPayload | null = null;
  if (jsonStart >= 0 && jsonEnd > jsonStart) {
    try {
      payload = JSON.parse(rest.substring(jsonStart, jsonEnd + 1));
    } catch {
      /* leave null */
    }
  }

  return { header, payload, timestamp: entry.timestamp, originalMessage: msg };
}

function highlightPython(code: string): string {
  try {
    return hljs.highlight(code.trimEnd(), { language: "python" }).value;
  } catch {
    return code
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
}

function looksLikeCode(text: string): boolean {
  return (
    /^(import |from .+ import |def |class |if |for |while |with |try:|except |return |yield |@)/m.test(
      text,
    ) ||
    /\n\s*(def |class |if |for |while )/.test(text) ||
    (text.includes("=") && text.includes("(") && text.split("\n").length > 2)
  );
}

function CodeBlock({ code }: { code: string }) {
  const html = useMemo(() => highlightPython(code), [code]);
  return (
    <pre
      className="hljs rounded border border-[var(--border)] bg-[var(--bg-deep)] px-3 py-2 text-[11px] leading-[1.6] overflow-x-auto m-0"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function TextBlock({ text }: { text: string }) {
  if (looksLikeCode(text)) return <CodeBlock code={text} />;
  return (
    <pre className="text-[11px] font-mono text-[var(--text-secondary)] whitespace-pre-wrap break-words m-0 px-3 py-2 leading-[1.6]">
      {text}
    </pre>
  );
}

function ToolUseCard({
  toolUse,
}: {
  toolUse: { toolUseId: string; name: string; input: Record<string, unknown> };
}) {
  const isCode =
    toolUse.name === "run_code" && typeof toolUse.input?.code === "string";

  return (
    <div className="border border-blue-500/30 rounded bg-blue-500/5">
      <div className="flex items-center gap-2 px-3 py-1 text-[10px] border-b border-blue-500/20">
        <span className="text-blue-400 font-semibold font-mono">
          {toolUse.name}
        </span>
      </div>
      <div className="p-2">
        {isCode ? (
          <CodeBlock code={toolUse.input.code as string} />
        ) : (
          <pre className="text-[11px] font-mono text-[var(--text-secondary)] whitespace-pre-wrap m-0 px-1">
            {JSON.stringify(toolUse.input, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

function ToolResultCard({
  toolResult,
}: {
  toolResult: { toolUseId: string; content: { text: string }[] };
}) {
  const text = toolResult.content?.map((c) => c.text).join("\n") ?? "";
  return (
    <div className="border border-emerald-500/30 rounded bg-emerald-500/5">
      <div className="px-3 py-1 text-[10px] border-b border-emerald-500/20">
        <span className="text-emerald-400 font-semibold font-mono">result</span>
      </div>
      <pre className="text-[11px] font-mono text-[var(--text-secondary)] whitespace-pre-wrap break-words m-0 px-3 py-2">
        {text}
      </pre>
    </div>
  );
}

function SummaryPayload({ payload }: { payload: StepPayload }) {
  const { message: _msg, type: _type, ...rest } = payload;
  const display = Object.fromEntries(
    Object.entries(rest).filter(
      ([, v]) =>
        v != null && v !== "" && !(Array.isArray(v) && v.length === 0),
    ),
  );
  if (Object.keys(display).length === 0) return null;
  return (
    <pre className="text-[11px] font-mono text-[var(--text-muted)] whitespace-pre-wrap m-0 px-3 py-2">
      {JSON.stringify(display, null, 2)}
    </pre>
  );
}

const TYPE_COLORS: Record<string, string> = {
  assistant_message: "var(--accent)",
  tool_results_appended: "#a78bfa",
  trigger_loaded: "var(--warning)",
  final_stop: "var(--success)",
};

const KIND_COLORS: Record<string, string> = {
  trigger: "var(--warning)",
  final: "var(--success)",
  checkpoint: "var(--info)",
  manifest: "var(--text-muted)",
};

function StepEntry({ entry, defaultOpen }: { entry: ParsedEntry; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const p = entry.payload!;
  const type = p.type || entry.header.split("|")[0].trim();
  const stop = p.stop_reason || p.final_stop_reason;
  const content = p.message?.content;

  const chips: { label: string; color: string }[] = [];
  if (p.turn_number != null)
    chips.push({ label: `Turn ${p.turn_number}`, color: "var(--text-muted)" });
  if (stop)
    chips.push({
      label: stop,
      color:
        stop === "end_turn"
          ? "var(--success)"
          : stop === "tool_use"
            ? "var(--info)"
            : "var(--warning)",
    });
  if (p.input_tokens != null)
    chips.push({
      label: `${fmtNum(p.input_tokens)} in`,
      color: "var(--text-muted)",
    });
  if (p.output_tokens != null)
    chips.push({
      label: `${fmtNum(p.output_tokens)} out`,
      color: "var(--text-muted)",
    });

  return (
    <div className="border border-[var(--border)] rounded overflow-hidden">
      <div
        className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg-elevated)] cursor-pointer select-none hover:bg-[var(--bg-hover)]"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-[10px] text-[var(--text-muted)]">{open ? "\u25BC" : "\u25B6"}</span>
        <span
          className="text-[10px] font-mono font-semibold"
          style={{ color: TYPE_COLORS[type] || "var(--text-secondary)" }}
        >
          {type}
        </span>
        {chips.map((c, i) => (
          <span
            key={i}
            className="text-[10px] font-mono"
            style={{ color: c.color }}
          >
            {c.label}
          </span>
        ))}
        <span className="ml-auto text-[10px] text-[var(--text-muted)]">
          {fmtTime(entry.timestamp)}
        </span>
      </div>
      {open && (
        <>
          {content && content.length > 0 ? (
            <div className="space-y-2 p-2 border-t border-[var(--border)]">
              {content.map((block, i) => {
                if ("text" in block && typeof block.text === "string") {
                  return <TextBlock key={i} text={block.text} />;
                }
                if ("toolUse" in block) {
                  return <ToolUseCard key={i} toolUse={block.toolUse} />;
                }
                if ("toolResult" in block) {
                  return <ToolResultCard key={i} toolResult={block.toolResult} />;
                }
                return null;
              })}
            </div>
          ) : (
            <div className="border-t border-[var(--border)]">
              <SummaryPayload payload={p} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ArtifactEntry({ entry }: { entry: ParsedEntry }) {
  const [open, setOpen] = useState(false);
  const kind = entry.header.split("|")[0].trim();
  return (
    <div className="border border-[var(--border)] rounded overflow-hidden">
      <div
        className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg-elevated)] cursor-pointer select-none hover:bg-[var(--bg-hover)]"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-[10px] text-[var(--text-muted)]">{open ? "\u25BC" : "\u25B6"}</span>
        <span
          className="text-[10px] font-mono font-semibold"
          style={{ color: KIND_COLORS[kind] || "var(--text-secondary)" }}
        >
          {entry.header}
        </span>
        <span className="ml-auto text-[10px] text-[var(--text-muted)]">
          {fmtTime(entry.timestamp)}
        </span>
      </div>
      {open && entry.payload && (
        <div className="border-t border-[var(--border)]">
          <SummaryPayload payload={entry.payload} />
        </div>
      )}
    </div>
  );
}

function RawEntry({ entry }: { entry: ParsedEntry }) {
  return (
    <div
      className="grid gap-2 px-3 py-2 text-[11px] font-mono border border-[var(--border)] rounded bg-[var(--bg-surface)]"
      style={{ gridTemplateColumns: "180px 1fr" }}
    >
      <div className="text-[var(--text-muted)]">
        {fmtTime(entry.timestamp)}
      </div>
      <pre className="whitespace-pre-wrap break-words text-[var(--text-secondary)] m-0">
        {entry.originalMessage}
      </pre>
    </div>
  );
}

function EntryView({ entry }: { entry: ParsedEntry }) {
  if (entry.payload?.type) {
    const type = entry.payload.type;
    const defaultOpen = type === "assistant_message" || type === "tool_results_appended";
    return <StepEntry entry={entry} defaultOpen={defaultOpen} />;
  }
  if (entry.payload) return <ArtifactEntry entry={entry} />;
  return <RawEntry entry={entry} />;
}

interface PrettyLogViewProps {
  entries: CogosRunLogEntry[];
}

export function PrettyLogView({ entries }: PrettyLogViewProps) {
  const parsed = useMemo(() => entries.map(parseEntry), [entries]);

  return (
    <div className="space-y-2">
      {parsed.map((entry, i) => (
        <EntryView key={i} entry={entry} />
      ))}
    </div>
  );
}
