const AWS_REGION = "us-east-1";

type QueryDetail = Record<string, string[]>;

function queryEscape(value: string): string {
  return encodeURIComponent(value);
}

function ecmaEscape(value: string): string {
  let out = "";

  for (const char of value) {
    const code = char.codePointAt(0);
    if (code == null) continue;

    const isAlphaNum =
      (code >= 0x30 && code <= 0x39) ||
      (code >= 0x41 && code <= 0x5a) ||
      (code >= 0x61 && code <= 0x7a);
    const isSafePunct = "@*_+-./".includes(char);
    if (isAlphaNum || isSafePunct) {
      out += char;
      continue;
    }

    const width = code >= 0x100 ? 4 : 2;
    out += `%${code.toString(16).toUpperCase().padStart(width, "0")}`;
  }

  return out;
}

function addDetailValue(detail: QueryDetail, key: string, value: string, quote = false): void {
  const encoded = queryEscape(value).replace(/%/g, "*");
  const nextValue = quote ? `'${encoded}` : encoded;
  detail[key] = [...(detail[key] ?? []), nextValue];
}

function encodeQueryDetail(detail: QueryDetail): string {
  const parts = Object.entries(detail)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, values]) => {
      if (values.length === 1) {
        return `${key}~${values[0]}`;
      }
      return `${key}~(${values.map((value) => `~${value}`).join("")})`;
    });

  const encoded = queryEscape(`?queryDetail=${ecmaEscape(`~(${parts.join("~")})`)}`);
  return encoded.replace(/%/g, "$");
}

function executorLogGroup(cogentName: string, runner: string | null | undefined): string {
  const safeName = cogentName.replace(/\./g, "-");
  if (runner === "ecs") {
    return `/ecs/cogent-${safeName}-executor`;
  }
  return `/aws/lambda/cogent-${safeName}-executor`;
}

function addTimeRange(detail: QueryDetail, createdAt: string | null): void {
  const timestamp = createdAt ? Date.parse(createdAt) : Number.NaN;
  if (Number.isFinite(timestamp)) {
    const start = Math.max(timestamp - 60 * 60 * 1000, 0);
    const end = Math.max(timestamp + 60 * 60 * 1000, Date.now());
    addDetailValue(detail, "start", String(start));
    addDetailValue(detail, "end", String(end));
    addDetailValue(detail, "timeType", "ABSOLUTE", true);
    return;
  }

  addDetailValue(detail, "start", "-3600");
  addDetailValue(detail, "end", "0");
  addDetailValue(detail, "timeType", "RELATIVE", true);
  addDetailValue(detail, "unit", "seconds", true);
}

export function buildCogentRunLogsUrl(
  cogentName: string,
  runId: string,
  createdAt: string | null,
  runner?: string | null,
): string {
  const detail: QueryDetail = {};
  const logGroup = executorLogGroup(cogentName, runner);
  const query = [
    "fields @timestamp, @message, @logStream, run_id",
    `| filter run_id = "${runId}" or @message like /${runId}/`,
    "| sort @timestamp asc",
  ].join("\n");

  addTimeRange(detail, createdAt);
  addDetailValue(detail, "editorString", query, true);
  addDetailValue(detail, "source", logGroup, true);

  return `https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}#logsV2:logs-insights${encodeQueryDetail(detail)}`;
}
