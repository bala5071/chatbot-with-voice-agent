import type { Reply, TenantEntry, TenantUsage } from "../api/types";

// Hand-made values for tests only. None of these numbers was measured.

export function usage(over: Partial<TenantUsage> = {}): TenantUsage {
  const totals = {
    requests: 0,
    prompt_tokens: 0,
    cached_tokens: 0,
    completion_tokens: 0,
    billed_tokens: 0,
    base_cost_usd: 0,
    billed_cost_usd: 0,
  };
  return {
    tenant_id: "acme",
    plan: "enterprise",
    allowed_models: ["economy", "standard", "premium"],
    price_multiplier: 1,
    period: { start_ms: 0, end_ms: 1 },
    budget_tokens: 1000,
    used_tokens: 250,
    remaining_tokens: 750,
    total: totals,
    by_model: {},
    ...over,
  };
}

export const TENANTS: TenantEntry[] = [
  {
    tenant_id: "initech",
    usage: usage({ tenant_id: "initech", plan: "free", allowed_models: ["economy"] }),
    error: null,
  },
  { tenant_id: "acme", usage: usage(), error: null },
];

export function reply(over: Partial<Reply> = {}): Reply {
  return {
    id: "req-1",
    text: "Hello there",
    model: "premium",
    usage: { prompt_tokens: 10, cached_tokens: 0, completion_tokens: 3, total_tokens: 13 },
    timing: { queue_ms: 0, ttft_ms: 100, total_ms: 300 },
    cost: { usd: 0.0005 },
    ...over,
  };
}
