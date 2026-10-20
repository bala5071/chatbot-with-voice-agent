import type { Quality, Route, TenantEntry, TenantUsage } from "../api/types";
import type { AssistantMessage, Message } from "./chat";

/** Nearest-rank percentile, the method the gateway uses; null for no values. */
export function percentile(values: readonly number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.max(1, Math.ceil((p / 100) * sorted.length));
  return sorted[rank - 1] ?? null;
}

export interface TurnStats {
  model: string;
  downgradedFrom: string | null;
  ttftMs: number;
  totalMs: number;
  promptTokens: number;
  completionTokens: number;
  /** Output tokens per second after the first one; null with fewer than two tokens. */
  decodeTokensPerSecond: number | null;
  /** Median gap between streamed pieces, as the gateway timed them. */
  itlP50Ms: number | null;
  costUsd: number;
}

/** What the gateway reported about a finished reply; null until it has finished. */
export function turnStats(message: AssistantMessage): TurnStats | null {
  const reply = message.reply;
  if (!reply) return null;
  const gaps = message.tokenTimes.slice(1).map((t, i) => t - (message.tokenTimes[i] ?? t));
  const decodeMs = reply.timing.total_ms - reply.timing.ttft_ms;
  const after = reply.usage.completion_tokens - 1;
  return {
    model: reply.model,
    downgradedFrom: message.downgradedFrom,
    ttftMs: reply.timing.ttft_ms,
    totalMs: reply.timing.total_ms,
    promptTokens: reply.usage.prompt_tokens,
    completionTokens: reply.usage.completion_tokens,
    decodeTokensPerSecond: after > 0 && decodeMs > 0 ? after / (decodeMs / 1000) : null,
    itlP50Ms: percentile(gaps, 50),
    costUsd: reply.cost.usd,
  };
}

export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

export function formatUsd(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toPrecision(2)}`;
  return `$${usd.toFixed(2)}`;
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

export interface BudgetView {
  used: number;
  budget: number;
  remaining: number;
  /** Share of the budget used, 0 to 1. */
  fraction: number;
}

export function budgetView(usage: TenantUsage): BudgetView {
  const fraction = usage.budget_tokens > 0 ? usage.used_tokens / usage.budget_tokens : 1;
  return {
    used: usage.used_tokens,
    budget: usage.budget_tokens,
    remaining: usage.remaining_tokens,
    fraction: Math.min(1, Math.max(0, fraction)),
  };
}

/** A short line explaining an error the gateway or backend reported. */
export function errorHeadline(code: string, status: number | null | undefined): string {
  const headlines: Record<string, string> = {
    model_not_in_plan: "Not in this tenant's plan",
    unknown_tenant: "Unknown tenant",
    invalid_request: "Not accepted",
    budget_exhausted: "Token budget used up",
    queue_full: "Model overloaded",
    request_timeout: "The model took too long",
    backend_unavailable: "Model server not reachable",
    backend_error: "Model server failed",
    gateway_unavailable: "Gateway not reachable",
    gateway_timeout: "Gateway did not answer",
    stream_ended: "Reply cut off",
    network_error: "Connection to the chat backend lost",
  };
  const headline = headlines[code] ?? "Request failed";
  return status ? `${headline} (HTTP ${status})` : headline;
}

/** The longest message the chat backend accepts. */
export const MAX_MESSAGE_CHARS = 8000;

/**
 * The user messages sent as a different tenant from the message before them. The backend
 * keeps each tenant's history apart, so the page marks where a new tenant's history starts.
 */
export function tenantSwitches(messages: readonly Message[]): Set<string> {
  const switches = new Set<string>();
  let previous: string | null = null;
  for (const message of messages) {
    if (message.role === "user" && previous !== null && message.tenantId !== previous) {
      switches.add(message.id);
    }
    previous = message.tenantId;
  }
  return switches;
}

/** A readable line for a request the chat backend itself rejected (FastAPI's 422 detail). */
export function rejectionMessage(detail: unknown): string {
  const fallback = "The chat backend rejected the request.";
  if (!Array.isArray(detail) || detail.length === 0) return fallback;
  return detail
    .map((item: unknown) => {
      const { loc, msg } = (item ?? {}) as { loc?: unknown; msg?: unknown };
      const field = Array.isArray(loc) && loc.length > 0 ? String(loc.at(-1)) : "request";
      return `${field}: ${typeof msg === "string" ? msg : "invalid"}`;
    })
    .join("; ");
}

const QUALITIES: readonly Quality[] = ["cheapest", "balanced", "best"];

/** A route as a <select> value: "quality:best" or "model:premium". */
export function routeValue(route: Route): string {
  return route.kind === "quality" ? `quality:${route.quality}` : `model:${route.model}`;
}

export function routeFromValue(value: string): Route {
  const [kind, name = ""] = value.split(":", 2);
  if (kind === "quality" && (QUALITIES as readonly string[]).includes(name)) {
    return { kind: "quality", quality: name as Quality };
  }
  if (kind === "model" && name) return { kind: "model", model: name };
  return { kind: "quality", quality: "balanced" };
}

/** Every model any listed tenant may use, in the order the plans list them (cheapest first). */
export function knownModels(entries: readonly TenantEntry[]): string[] {
  const models: string[] = [];
  for (const entry of entries) {
    for (const model of entry.usage?.allowed_models ?? []) {
      if (!models.includes(model)) models.push(model);
    }
  }
  return models;
}

let counter = 0;

/** An id for a message or conversation; letters, digits and dashes only. */
export function newId(prefix: string): string {
  counter += 1;
  return `${prefix}-${Date.now().toString(36)}-${counter.toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
