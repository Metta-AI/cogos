const AWS_REGION = "us-east-1";
const LOG_WINDOW_MS = 60 * 60 * 1000;

function encodeInsightsValue(value: string): string {
  return encodeURIComponent(value).replace(/%/g, "*");
}

function executorLogGroup(cogentName: string): string {
  const safeName = cogentName.replace(/\./g, "-");
  return `/aws/lambda/cogent-${safeName}-executor`;
}

function parseCreatedAtMillis(createdAt: string | null): number {
  if (!createdAt) return Number.NaN;

  let normalized = createdAt.trim();
  if (normalized.includes(" ") && !normalized.includes("T")) {
    normalized = normalized.replace(" ", "T");
  }
  if (!/[zZ]|[+-]\d{2}:\d{2}$/.test(normalized)) {
    normalized += "Z";
  }

  return Date.parse(normalized);
}

function buildTimeRangeFragment(createdAt: string | null): string {
  const timestamp = parseCreatedAtMillis(createdAt);
  if (!Number.isFinite(timestamp)) {
    return "start~-3600~timeType~'RELATIVE~unit~'seconds";
  }

  const start = Math.max(timestamp - LOG_WINDOW_MS, 0);
  const end = Math.max(timestamp + LOG_WINDOW_MS, Date.now());
  return `start~${start}~end~${end}~timeType~'ABSOLUTE`;
}

function buildSourceFragment(logGroup: string): string {
  return `source~(~'${encodeInsightsValue(logGroup)})`;
}

export function buildCogentRunLogsUrl(
  cogentName: string,
  runId: string,
  createdAt: string | null,
  _runner?: string | null,
): string {
  const logGroup = executorLogGroup(cogentName);
  const query = [
    "fields @timestamp, @message, @logStream",
    `| filter @message like /${runId}/ or run_id = "${runId}"`,
    "| sort @timestamp asc",
  ].join("\n");
  const fragment = [
    buildTimeRangeFragment(createdAt),
    `editorString~'${encodeInsightsValue(query)}`,
    buildSourceFragment(logGroup),
  ].join("~");

  return (
    `https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}` +
    `#logsV2:logs-insights$3FqueryDetail$3D~(${fragment})`
  );
}
