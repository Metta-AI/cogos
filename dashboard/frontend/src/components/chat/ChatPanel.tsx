"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { getChatMessages, sendChatMessage, type ChatMessage } from "@/lib/api";

interface ChatPanelProps {
  cogentName: string;
}

export function ChatPanel({ cogentName }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "calc(100vh - var(--header-h) - 40px)",
        maxWidth: "800px",
        margin: "0 auto",
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
                maxWidth: "70%",
                padding: "8px 12px",
                borderRadius: msg.source === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                background: msg.source === "user" ? "var(--accent)" : "var(--bg-elevated)",
                color: msg.source === "user" ? "white" : "var(--text-primary)",
                fontSize: "13px",
                lineHeight: "1.4",
                wordBreak: "break-word",
                whiteSpace: "pre-wrap",
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
  );
}
