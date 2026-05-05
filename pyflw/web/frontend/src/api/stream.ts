// WebSocket クライアント (ADR-0011 §(2))。
import type { StreamMessage } from "../types/api";

export function streamSimulation(
  simId: string,
  onMessage: (msg: StreamMessage) => void,
  onError?: (err: Event) => void,
): WebSocket {
  // location.protocol が ``https:`` のとき ``wss:`` を選ぶ。Phase 3 で HTTPS
  // デプロイした際にも追加変更不要なように意図的にこの形にしている。
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/api/v1/simulations/${encodeURIComponent(simId)}/stream`;
  const ws = new WebSocket(url);
  ws.addEventListener("message", (ev: MessageEvent<string>) => {
    try {
      const msg = JSON.parse(ev.data) as StreamMessage;
      onMessage(msg);
    } catch (e) {
      console.error("Invalid WebSocket payload:", e, ev.data);
    }
  });
  if (onError) {
    ws.addEventListener("error", onError);
  }
  return ws;
}
