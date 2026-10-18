// The chat backend's API (backend/src/gateway_chat/app.py). Bodies that come from the gateway
// are relayed unchanged, so their shapes are the gateway's own.

export type Quality = "cheapest" | "balanced" | "best";

/** How the model is chosen, always within the tenant's plan. */
export type Route = { kind: "quality"; quality: Quality } | { kind: "model"; model: string };

/** The gateway's error object, plus the gateway's HTTP status (null: not reached at all). */
export interface GatewayError {
  code: string;
  message: string;
  status?: number | null;
  [key: string]: unknown;
}

export interface UsageTotals {
  requests: number;
  prompt_tokens: number;
  cached_tokens: number;
  completion_tokens: number;
  billed_tokens: number;
  base_cost_usd: number;
  billed_cost_usd: number;
}

export interface TenantUsage {
  tenant_id: string;
  plan: string;
  allowed_models: string[];
  price_multiplier: number;
  period: { start_ms: number; end_ms: number };
  budget_tokens: number;
  used_tokens: number;
  remaining_tokens: number;
  total: UsageTotals;
  by_model: Record<string, UsageTotals>;
}

export interface TenantEntry {
  tenant_id: string;
  usage: TenantUsage | null;
  error: GatewayError | null;
}

export interface Health {
  status: string;
  gateway: { url: string; reachable: boolean; health?: unknown };
}

/** The gateway's GenerateResponse. */
export interface Reply {
  id: string;
  text: string;
  model: string;
  usage: {
    prompt_tokens: number;
    cached_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  timing: { queue_ms: number; ttft_ms: number; total_ms: number };
  cost: { usd: number };
}

export interface ChatRequest {
  tenant_id: string;
  conversation_id: string;
  message: string;
  quality?: Quality;
  model?: string;
  allow_downgrade: boolean;
}

export type ChatEvent =
  | { type: "start"; model: string; downgradedFrom: string | null; promptChars: number }
  | { type: "token"; index: number; token: string; tMs: number }
  | { type: "done"; reply: Reply }
  | { type: "error"; error: GatewayError };
