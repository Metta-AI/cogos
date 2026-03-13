"use client";

import type { ReactNode } from "react";

interface InfoTooltipProps {
  title: string;
  children: ReactNode;
}

export function InfoTooltip({ title, children }: InfoTooltipProps) {
  return (
    <span className="relative inline-flex items-center group align-middle">
      <button
        type="button"
        aria-label={`${title} help`}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] font-semibold cursor-help"
        style={{
          borderColor: "var(--border)",
          color: "var(--text-muted)",
          background: "var(--bg-surface)",
        }}
      >
        i
      </button>
      <span
        className="pointer-events-none absolute left-0 top-full z-50 mt-1 hidden w-72 rounded-md border px-3 py-2 group-hover:block group-focus-within:block"
        style={{
          borderColor: "var(--border)",
          background: "var(--bg-elevated)",
          boxShadow: "0 8px 20px rgba(0,0,0,0.35)",
        }}
      >
        <span
          className="block text-[10px] font-semibold uppercase tracking-wide"
          style={{ color: "var(--text-primary)" }}
        >
          {title}
        </span>
        <span className="mt-2 block text-[10px]" style={{ color: "var(--text-secondary)" }}>
          {children}
        </span>
      </span>
    </span>
  );
}
