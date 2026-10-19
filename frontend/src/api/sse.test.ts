import { createSseParser, decodeChatEvent } from "./sse";

describe("createSseParser", () => {
  it("joins lines split across chunks", () => {
    const parser = createSseParser();
    expect(parser.push("event: tok")).toEqual([]);
    expect(parser.push('en\ndata: {"a"')).toEqual([]);
    expect(parser.push(": 1}\n\nevent: done\r\ndata: {}\r\n\r\n")).toEqual([
      { event: "token", data: '{"a": 1}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("skips comments and blank events, and joins data lines", () => {
    const parser = createSseParser();
    expect(parser.push(": ping\n\n\ndata: a\ndata: b\n\n")).toEqual([
      { event: "message", data: "a\nb" },
    ]);
  });
});

describe("decodeChatEvent", () => {
  it("decodes each event the backend sends", () => {
    expect(
      decodeChatEvent({
        event: "start",
        data: '{"model": "premium", "downgraded_from": null, "prompt_chars": 12}',
      }),
    ).toEqual({ type: "start", model: "premium", downgradedFrom: null, promptChars: 12 });
    expect(
      decodeChatEvent({ event: "token", data: '{"index": 2, "token": "hi ", "t_ms": 41.5}' }),
    ).toEqual({ type: "token", index: 2, token: "hi ", tMs: 41.5 });
    expect(
      decodeChatEvent({ event: "error", data: '{"status": 403, "code": "x", "message": "m"}' }),
    ).toEqual({ type: "error", error: { status: 403, code: "x", message: "m" } });
    expect(decodeChatEvent({ event: "done", data: '{"text": "t"}' })).toEqual({
      type: "done",
      reply: { text: "t" },
    });
  });

  it("ignores unknown events", () => {
    expect(decodeChatEvent({ event: "ping", data: "{}" })).toBeNull();
  });
});
