import { rejectionMessage } from "../state/derive";
import { createSseParser, decodeChatEvent } from "./sse";
import type { ChatEvent, ChatRequest, GatewayError, Health, TenantEntry } from "./types";

/** The error object of a failed response from the chat backend. */
async function errorOf(response: Response): Promise<GatewayError> {
  try {
    const body = (await response.json()) as { error?: GatewayError; detail?: unknown };
    if (body.error) return { ...body.error, status: body.error.status ?? response.status };
    if (body.detail !== undefined) {
      return {
        code: "invalid_request",
        message: rejectionMessage(body.detail),
        status: response.status,
        detail: body.detail,
      };
    }
  } catch {
    // Not JSON; fall through.
  }
  return {
    code: "http_error",
    message: `The chat backend answered HTTP ${response.status}.`,
    status: response.status,
  };
}

/**
 * Send one turn and report each event as it arrives. Resolves when the stream ends. Aborting
 * `signal` stops reading and closes the connection; that rejects with an AbortError.
 */
export async function streamChat(
  request: ChatRequest,
  signal: AbortSignal,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok || !response.body) {
    onEvent({ type: "error", error: await errorOf(response) });
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();
  for (;;) {
    const { done, value } = await reader.read();
    const text = done ? decoder.decode() + "\n\n" : decoder.decode(value, { stream: true });
    for (const message of parser.push(text)) {
      const event = decodeChatEvent(message);
      if (event) onEvent(event);
    }
    if (done) return;
  }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error((await errorOf(response)).message);
  return (await response.json()) as T;
}

export async function fetchTenants(): Promise<TenantEntry[]> {
  return (await getJson<{ tenants: TenantEntry[] }>("/api/tenants")).tenants;
}

export function fetchHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}

export async function forgetConversation(conversationId: string): Promise<void> {
  await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
}
