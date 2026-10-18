import { reply } from "../test/fixtures";
import { chatReducer, initialChat, type AssistantMessage, type ChatState } from "./chat";

function sent(): ChatState {
  return chatReducer(initialChat("c1"), {
    type: "send",
    userId: "u1",
    replyId: "r1",
    text: "Hi",
    tenantId: "acme",
  });
}

function lastReply(state: ChatState): AssistantMessage {
  const last = state.messages.at(-1);
  if (last?.role !== "assistant") throw new Error("no reply");
  return last;
}

describe("chatReducer", () => {
  it("adds the question and a waiting reply", () => {
    const state = sent();
    expect(state.busy).toBe(true);
    expect(state.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(lastReply(state).status).toBe("waiting");
  });

  it("refuses a second send while one is in flight", () => {
    const state = sent();
    const again = chatReducer(state, {
      type: "send",
      userId: "u2",
      replyId: "r2",
      text: "Again",
      tenantId: "acme",
    });
    expect(again).toBe(state);
  });

  it("streams tokens, then settles on the gateway's reply", () => {
    let state = sent();
    state = chatReducer(state, {
      type: "event",
      event: { type: "start", model: "premium", downgradedFrom: "premium2", promptChars: 5 },
    });
    state = chatReducer(state, {
      type: "event",
      event: { type: "token", index: 0, token: "Hel", tMs: 100 },
    });
    state = chatReducer(state, {
      type: "event",
      event: { type: "token", index: 1, token: "lo", tMs: 150 },
    });
    expect(lastReply(state)).toMatchObject({
      status: "streaming",
      text: "Hello",
      model: "premium",
      downgradedFrom: "premium2",
      tokenTimes: [100, 150],
    });
    state = chatReducer(state, { type: "event", event: { type: "done", reply: reply() } });
    expect(state.busy).toBe(false);
    expect(lastReply(state)).toMatchObject({ status: "done", text: "Hello there" });
    // Late events change nothing.
    const after = chatReducer(state, { type: "ended" });
    expect(after).toBe(state);
  });

  it("records an error from the gateway", () => {
    const state = chatReducer(sent(), {
      type: "event",
      event: { type: "error", error: { code: "model_not_in_plan", message: "No", status: 403 } },
    });
    expect(state.busy).toBe(false);
    expect(lastReply(state).error?.code).toBe("model_not_in_plan");
  });

  it("marks stopped, failed and cut-off replies", () => {
    expect(lastReply(chatReducer(sent(), { type: "stopped" })).status).toBe("stopped");
    const failed = lastReply(chatReducer(sent(), { type: "failed", message: "offline" }));
    expect(failed.error).toMatchObject({ code: "network_error", message: "offline" });
    const ended = lastReply(chatReducer(sent(), { type: "ended" }));
    expect(ended.error?.code).toBe("stream_ended");
  });

  it("starts over on reset", () => {
    expect(chatReducer(sent(), { type: "reset", conversationId: "c2" })).toEqual(initialChat("c2"));
  });
});
