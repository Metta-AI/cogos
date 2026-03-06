"use client";
import { useEffect, useRef, useState, useCallback } from "react";

interface WsMessage {
  type: string;
  data: unknown;
}

export function useWebSocket(cogentName: string) {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);

  const connect = useCallback(() => {
    const apiKey =
      typeof window !== "undefined"
        ? localStorage.getItem("cogent-api-key")
        : null;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/ws/cogents/${cogentName}${apiKey ? `?key=${apiKey}` : ""}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      retriesRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WsMessage;
        setLastMessage(msg);
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Exponential backoff: 1s, 2s, 4s, 8s, ... max 30s
      const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30000);
      retriesRef.current++;
      setTimeout(connect, delay);
    };

    ws.onerror = () => ws.close();
  }, [cogentName]);

  useEffect(() => {
    if (!cogentName) return;
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect, cogentName]);

  return { connected, lastMessage };
}
