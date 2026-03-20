"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { getChatMessages, sendChatMessage, getTraceViewer, type ChatMessage } from "@/lib/api";
import { TraceDetail } from "@/components/trace-viewer/TraceDetail";
import type { TraceData } from "@/components/trace-viewer/TraceDetail";

interface ChatPanelProps {
  cogentName: string;
}

export function ChatPanel({ cogentName }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTraceId, setActiveTraceId] = useState<string | null>(null);
  const [traceData, setTraceData] = useState<TraceData | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const fetchMessages = useCallback(async () => {
    try {
      const msgs = await getChatMessages(cogentName);
      setMessages(msgs);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load messages");
    }
  }, [cogentName]);

  useEffect(() => {
    fetchMessages();
    pollRef.current = setInterval(fetchMessages, 3000);
    return () => clearInterval(pollRef.current);
  }, [fetchMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setInput("");
    try {
      await sendChatMessage(cogentName, text);
      await fetchMessages();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send");
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTraceClick = async (traceId: string) => {
    if (activeTraceId === traceId) {
      setActiveTraceId(null);
      setTraceData(null);
      return;
    }
    setActiveTraceId(traceId);
    setTraceData(null);
    setTraceLoading(true);
    try {
      const data = await getTraceViewer(cogentName, traceId);
      setTraceData(data);
    } catch {
      setTraceData(null);
    } finally {
      setTraceLoading(false);
    }
  };

  const showTrace = activeTraceId !== null;

  return (
    <div
      style={{
        display: "flex",
        gap: "16px",
        height: "calc(100vh - var(--header-h) - 40px)",
      }}
    >
      {/* Chat column */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          flex: showTrace ? "0 0 360px" : "1 1 auto",
          maxWidth: showTrace ? "360px" : "800px",
          margin: showTrace ? undefined : "0 auto",
          minWidth: 0,
          transition: "flex 0.2s, max-width 0.2s",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "12px",
          }}
        >
          <h2 style={{ fontSize: "16px", fontWeight: 600, color: "var(--text-primary)" }}>
            Chat
          </h2>
          <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
            Messages are routed through the Discord DM pipeline
          </span>
        </div>

        {error && (
          <div
            style={{
              padding: "8px 12px",
              marginBottom: "8px",
              background: "rgba(var(--error-rgb, 239,68,68), 0.1)",
              border: "1px solid var(--error)",
              borderRadius: "6px",
              fontSize: "12px",
              color: "var(--error)",
            }}
          >
            {error}
          </div>
        )}

        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "12px",
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "8px",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          {messages.length === 0 && (
            <div
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--text-muted)",
                fontSize: "13px",
              }}
            >
              No messages yet. Send a message to start chatting with the cogent.
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              style={{
                display: "flex",
                justifyContent: msg.source === "user" ? "flex-end" : "flex-start",
              }}
            >
              <div
                style={{
                  maxWidth: "85%",
                  padding: "8px 12px",
                  borderRadius: msg.source === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                  background:
                    msg.source === "user"
                      ? "var(--accent)"
                      : activeTraceId === msg.trace_id
                        ? "var(--bg-elevated)"
                        : "var(--bg-elevated)",
                  color: msg.source === "user" ? "white" : "var(--text-primary)",
                  fontSize: "13px",
                  lineHeight: "1.4",
                  wordBreak: "break-word",
                  whiteSpace: "pre-wrap",
                  outline: activeTraceId && activeTraceId === msg.trace_id ? "1px solid var(--accent)" : undefined,
                }}
              >
                {msg.source === "cogent" && (
                  <div
                    style={{
                      fontSize: "10px",
                      fontWeight: 600,
                      color: "var(--accent)",
                      marginBottom: "2px",
                    }}
                  >
                    {msg.author || cogentName}
                  </div>
                )}
                {msg.content}
                <div
                  style={{
                    fontSize: "9px",
                    marginTop: "4px",
                    opacity: 0.6,
                    textAlign: msg.source === "user" ? "right" : "left",
                    display: "flex",
                    gap: "6px",
                    justifyContent: msg.source === "user" ? "flex-end" : "flex-start",
                    alignItems: "center",
                  }}
                >
                  <span>{new Date(msg.timestamp * 1000).toLocaleTimeString()}</span>
                  {msg.trace_id && (
                    <span
                      onClick={() => handleTraceClick(msg.trace_id!)}
                      style={{
                        color: msg.source === "user" ? "rgba(255,255,255,0.8)" : "var(--accent)",
                        cursor: "pointer",
                        textDecoration: "underline",
                        textUnderlineOffset: "2px",
                      }}
                    >
                      trace
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div
          style={{
            display: "flex",
            gap: "8px",
            marginTop: "12px",
          }}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message..."
            rows={1}
            style={{
              flex: 1,
              padding: "10px 14px",
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
              color: "var(--text-primary)",
              fontSize: "13px",
              resize: "none",
              outline: "none",
              fontFamily: "inherit",
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || sending}
            style={{
              padding: "10px 20px",
              background: !input.trim() || sending ? "var(--bg-elevated)" : "var(--accent)",
              color: !input.trim() || sending ? "var(--text-muted)" : "white",
              border: "none",
              borderRadius: "8px",
              cursor: !input.trim() || sending ? "not-allowed" : "pointer",
              fontSize: "13px",
              fontWeight: 500,
              fontFamily: "inherit",
            }}
          >
            {sending ? "..." : "Send"}
          </button>
        </div>
      </div>

      {/* Trace viewer pane */}
      {showTrace && (
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            borderLeft: "1px solid var(--border)",
            paddingLeft: "16px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: "12px",
            }}
          >
            <h2 style={{ fontSize: "14px", fontWeight: 600, color: "var(--text-primary)" }}>
              Trace
            </h2>
            <button
              onClick={() => { setActiveTraceId(null); setTraceData(null); }}
              style={{
                background: "none",
                border: "none",
                color: "var(--text-muted)",
                cursor: "pointer",
                fontSize: "16px",
                padding: "2px 6px",
              }}
            >
              x
            </button>
          </div>
          {traceLoading && (
            <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>Loading trace...</div>
          )}
          {traceData && (
            <div style={{ flex: 1, minHeight: 0 }}>
              <TraceDetail trace={traceData} compact />
            </div>
          )}
          {!traceLoading && !traceData && activeTraceId && (
            <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>
              Failed to load trace
            </div>
          )}
        </div>
      )}
    </div>
  );
}
