/**
 * Cloudflare Email Worker — forwards inbound emails to the cogent's dashboard API.
 *
 * Deployed once for the whole domain. Parses the email, extracts the cogent
 * name from the recipient local part, and POSTs to the dashboard ingest endpoint.
 *
 * Bindings required:
 *   - DASHBOARD_DOMAIN: string (e.g. "agora.softmax-cogents.com")
 *   - DASHBOARD_API_KEY: secret (string)
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

    // POST to the cogent's dashboard API
    const domain = env.DASHBOARD_DOMAIN || "agora.softmax-cogents.com";
    const url = `https://${localPart}.${domain}/api/cogents/${localPart}/ingest/email`;

    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": env.DASHBOARD_API_KEY || "",
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      throw new Error(`Ingest failed: ${resp.status} ${await resp.text()}`);
    }
  },
};
