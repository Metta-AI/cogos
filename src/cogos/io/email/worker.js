/**
 * Cloudflare Email Worker — forwards inbound emails to the cogtainer ingest Lambda.
 *
 * Deployed once for the whole domain. Parses the email, extracts the cogent
 * name from the recipient local part, and POSTs to a single ingest endpoint.
 *
 * Bindings required:
 *   - INGEST_URL: string (Lambda Function URL)
 *   - INGEST_SECRET: secret (string)
 */

/**
 * Extract the text/plain body from a raw MIME email.
 * Handles both simple text emails and multipart messages.
 */
function extractTextBody(rawEmail) {
  const boundaryMatch = rawEmail.match(/boundary="?([^\s"]+)"?/i);
  if (!boundaryMatch) {
    const blankLine = rawEmail.indexOf("\r\n\r\n");
    if (blankLine === -1) {
      const blankLineLf = rawEmail.indexOf("\n\n");
      return blankLineLf === -1 ? "" : rawEmail.slice(blankLineLf + 2);
    }
    return rawEmail.slice(blankLine + 4);
  }

  const boundary = boundaryMatch[1];
  const parts = rawEmail.split("--" + boundary);

  for (const part of parts) {
    if (/content-type:\s*text\/plain/i.test(part)) {
      const bodyStart = part.indexOf("\r\n\r\n");
      if (bodyStart !== -1) {
        return part.slice(bodyStart + 4).trim();
      }
      const bodyStartLf = part.indexOf("\n\n");
      if (bodyStartLf !== -1) {
        return part.slice(bodyStartLf + 2).trim();
      }
    }
  }

  return "";
}

export default {
  async email(message, env, ctx) {
    const to = message.to;
    const from = message.from;
    const localPart = to.split("@")[0];

    const rawEmail = await new Response(message.raw).text();

    const subject = message.headers.get("subject") || "(no subject)";
    const messageId = message.headers.get("message-id") || "";
    const date = message.headers.get("date") || "";

    const body = extractTextBody(rawEmail);

    const payload = {
      event_type: "email:received",
      source: "cloudflare-email-worker",
      payload: {
        from: from,
        to: to,
        subject: subject,
        body: body,
        message_id: messageId,
        date: date,
        cogent: localPart,
      },
    };

    const resp = await fetch(env.INGEST_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.INGEST_SECRET}`,
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      throw new Error(`Ingest failed: ${resp.status} ${await resp.text()}`);
    }
  },
};
