import type { Timezone, TimeRange } from "./types";

const TZ = "America/Los_Angeles";

/** Parse an ISO/datetime string, treating bare timestamps (no Z or offset) as UTC. */
export function parseUtc(iso: string): Date {
  // If no timezone indicator, append Z to treat as UTC
  if (!iso.endsWith("Z") && !/[+-]\d{2}:\d{2}$/.test(iso)) {
    return new Date(iso.replace(" ", "T") + "Z");
  }
  return new Date(iso);
}

/** Convert a TimeRange value to milliseconds. */
export function timeRangeToMs(range: TimeRange): number {
  switch (range) {
    case "1m": return 60_000;
    case "10m": return 600_000;
    case "1h": return 3_600_000;
    case "24h": return 86_400_000;
    case "1w": return 604_800_000;
  }
}

/** Format a number with locale-aware separators (e.g. 1,234). */
export function fmtNum(n: number | null | undefined): string {
  if (n == null) return "--";
  return n.toLocaleString("en-US");
}

/** Format a USD cost value. Shows < $0.01 for tiny amounts. */
export function fmtCost(n: number | null | undefined): string {
  if (n == null) return "--";
  if (n === 0) return "$0.00";
  if (n < 0.01) return "< $0.01";
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

/** Format milliseconds into a human-readable duration. */
export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const mins = Math.floor(ms / 60_000);
  const secs = Math.round((ms % 60_000) / 1000);
  return `${mins}m ${secs}s`;
}

function toTimezoneDate(
  iso: string,
  tz: Timezone,
): { date: Date; tzLabel: string } {
  const date = parseUtc(iso);
  switch (tz) {
    case "utc":
      return { date, tzLabel: "UTC" };
    case "pst":
      return { date, tzLabel: "PST" };
    case "local":
    default:
      return { date, tzLabel: "" };
  }
}

function formatOptions(
  tz: Timezone,
): Intl.DateTimeFormatOptions {
  switch (tz) {
    case "utc":
      return { timeZone: "UTC" };
    case "pst":
      return { timeZone: TZ };
    case "local":
    default:
      return {};
  }
}

/** Format an ISO timestamp to a short time string (HH:MM:SS). */
export function fmtTime(
  iso: string | null | undefined,
  tz: Timezone = "local",
): string {
  if (!iso) return "--";
  const { date } = toTimezoneDate(iso, tz);
  return date.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    ...formatOptions(tz),
  });
}

/** Format an ISO timestamp to a date-time string. */
export function fmtDateTime(
  iso: string | null | undefined,
  tz: Timezone = "local",
): string {
  if (!iso) return "--";
  const { date } = toTimezoneDate(iso, tz);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    ...formatOptions(tz),
  });
}

/** Format a relative delta string (e.g. "3m ago"). */
function relativeDelta(ms: number): string {
  if (ms < 0) return "just now";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/** Format an ISO timestamp as a relative time string (e.g. "3m ago"). */
export function fmtRelative(
  iso: string | null | undefined,
): string {
  if (!iso) return "--";
  const diff = Date.now() - parseUtc(iso).getTime();
  return relativeDelta(diff);
}

/** Format an ISO timestamp as "today, 2:20 pm (10m ago)" or "Mar 5, 2:20 pm (1d ago)". All times PST. */
export function fmtTimestamp(
  iso: string | null | undefined,
): string {
  if (!iso) return "--";
  const date = parseUtc(iso);
  const now = new Date();

  // Compare dates in PST
  const datePST = date.toLocaleDateString("en-US", { timeZone: TZ });
  const nowPST = now.toLocaleDateString("en-US", { timeZone: TZ });
  const yesterdayDate = new Date(now.getTime() - 86_400_000);
  const yesterdayPST = yesterdayDate.toLocaleDateString("en-US", { timeZone: TZ });

  const time = date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: TZ,
  }).toLowerCase();

  let prefix: string;
  if (datePST === nowPST) {
    prefix = `today, ${time}`;
  } else if (datePST === yesterdayPST) {
    prefix = `yesterday, ${time}`;
  } else {
    const monthDay = date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: TZ });
    prefix = `${monthDay}, ${time}`;
  }

  const diff = now.getTime() - date.getTime();
  return `${prefix} (${relativeDelta(diff)})`;
}
