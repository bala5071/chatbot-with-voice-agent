import { reply, TENANTS, usage } from "../test/fixtures";
import type { AssistantMessage } from "./chat";
import {
  budgetView,
  errorHeadline,
  formatMs,
  formatUsd,
  knownModels,
  newId,
  percentile,
  routeFromValue,
  routeValue,
  turnStats,
} from "./derive";

function message(over: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: "r",
    role: "assistant",
    tenantId: "acme",
    status: "done",
    text: "",
    model: "premium",
    downgradedFrom: null,
    tokenTimes: [100, 130, 200],
    reply: reply(),
    error: null,
    ...over,
  };
}

describe("percentile", () => {
  it("is nearest-rank", () => {
    expect(percentile([], 50)).toBeNull();
    expect(percentile([30, 10, 20], 50)).toBe(20);
    expect(percentile([1, 2, 3, 4], 50)).toBe(2);
    expect(percentile([1, 2, 3, 4], 99)).toBe(4);
  });
});

describe("turnStats", () => {
  it("is null until the reply is done", () => {
    expect(turnStats(message({ reply: null }))).toBeNull();
  });

  it("reads the gateway's timing and usage", () => {
    expect(turnStats(message({ downgradedFrom: "premium" }))).toEqual({
      model: "premium",
      downgradedFrom: "premium",
      ttftMs: 100,
      totalMs: 300,
      promptTokens: 10,
      completionTokens: 3,
      // Two tokens after the first, over the 200 ms after it.
      decodeTokensPerSecond: 10,
      itlP50Ms: 30,
      costUsd: 0.0005,
    });
  });

  it("has no decode rate for a one-token reply", () => {
    const one = reply({
      usage: { prompt_tokens: 1, cached_tokens: 0, completion_tokens: 1, total_tokens: 2 },
    });
    const stats = turnStats(message({ reply: one, tokenTimes: [100] }));
    expect(stats?.decodeTokensPerSecond).toBeNull();
    expect(stats?.itlP50Ms).toBeNull();
  });
});

describe("formatting", () => {
  it("formats times", () => {
    expect(formatMs(412.4)).toBe("412 ms");
    expect(formatMs(1920)).toBe("1.92 s");
    expect(formatMs(12_340)).toBe("12.3 s");
  });

  it("formats costs", () => {
    expect(formatUsd(0)).toBe("$0");
    expect(formatUsd(0.000123)).toBe("$0.00012");
    expect(formatUsd(1.5)).toBe("$1.50");
  });

  it("names errors, with the status when there is one", () => {
    expect(errorHeadline("model_not_in_plan", 403)).toBe("Not in this tenant's plan (HTTP 403)");
    expect(errorHeadline("gateway_unavailable", null)).toBe("Gateway not reachable");
    expect(errorHeadline("something_new", undefined)).toBe("Request failed");
  });
});

describe("budgetView", () => {
  it("clamps the fraction used", () => {
    expect(budgetView(usage()).fraction).toBe(0.25);
    expect(budgetView(usage({ used_tokens: 2000 })).fraction).toBe(1);
    expect(budgetView(usage({ budget_tokens: 0 })).fraction).toBe(1);
  });
});

describe("routes", () => {
  it("round-trips through a select value", () => {
    for (const route of [
      { kind: "quality", quality: "best" },
      { kind: "model", model: "premium" },
    ] as const) {
      expect(routeFromValue(routeValue(route))).toEqual(route);
    }
    expect(routeFromValue("nonsense")).toEqual({ kind: "quality", quality: "balanced" });
  });

  it("lists every model any tenant may use, in plan order", () => {
    expect(knownModels(TENANTS)).toEqual(["economy", "standard", "premium"]);
    expect(knownModels([])).toEqual([]);
  });
});

it("makes ids the backend accepts", () => {
  const a = newId("conv");
  expect(a).toMatch(/^[A-Za-z0-9_-]+$/);
  expect(newId("conv")).not.toBe(a);
});
