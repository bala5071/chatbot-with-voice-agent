import type { ChatEvent, GatewayError, Reply } from "./types";

export interface SseMessage {
  event: string;
  data: string;
}

/**
 * Server-sent events from text arriving in arbitrary chunks. `push` returns the events
 * that the chunk completed; a line split across chunks is held until its end arrives.
 */
export function createSseParser(): { push: (chunk: string) => SseMessage[] } {
  let buffer = "";
  let event = "message";
  let data: string[] = [];

  return {
    push(chunk: string): SseMessage[] {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      const done: SseMessage[] = [];
      for (const raw of lines) {
        const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
        if (line === "") {
          if (data.length > 0) done.push({ event, data: data.join("\n") });
          event = "message";
          data = [];
        } else if (!line.startsWith(":")) {
          const colon = line.indexOf(":");
          const name = colon === -1 ? line : line.slice(0, colon);
          let value = colon === -1 ? "" : line.slice(colon + 1);
          if (value.startsWith(" ")) value = value.slice(1);
          if (name === "event") event = value;
          else if (name === "data") data.push(value);
        }
      }
      return done;
    },
  };
}

type Json = Record<string, unknown>;

/** A chat event from one SSE message of /api/chat, or null for an event it does not know. */
export function decodeChatEvent(message: SseMessage): ChatEvent | null {
  const data = JSON.parse(message.data) as Json;
  switch (message.event) {
    case "start":
      return {
        type: "start",
        model: String(data.model),
        downgradedFrom: typeof data.downgraded_from === "string" ? data.downgraded_from : null,
        promptChars: Number(data.prompt_chars),
      };
    case "token":
      return {
        type: "token",
        index: Number(data.index),
        token: String(data.token),
        tMs: Number(data.t_ms),
      };
    case "done":
      return { type: "done", reply: data as unknown as Reply };
    case "error":
      return { type: "error", error: data as unknown as GatewayError };
    default:
      return null;
  }
}
