import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import type { ChatRequest } from "./api/types";
import { reply, TENANTS } from "./test/fixtures";

function sse(events: [string, unknown][]): Response {
  const text = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  return new Response(text, { headers: { "Content-Type": "text/event-stream" } });
}

/** A fake chat backend; `answer` decides what /api/chat streams back. */
function stubBackend(answer: (request: ChatRequest) => Response) {
  const requests: ChatRequest[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.endsWith("/api/tenants")) return Promise.resolve(Response.json({ tenants: TENANTS }));
    if (url.endsWith("/api/health")) {
      return Promise.resolve(
        Response.json({ status: "ok", gateway: { url: "http://gw:8000", reachable: true } }),
      );
    }
    if (url.endsWith("/api/chat")) {
      const request = JSON.parse(init?.body as string) as ChatRequest;
      requests.push(request);
      return Promise.resolve(answer(request));
    }
    return Promise.resolve(new Response(null, { status: 204 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return requests;
}

describe("App", () => {
  it("sends a turn and shows the gateway's answer with its numbers", async () => {
    const requests = stubBackend(() =>
      sse([
        ["start", { model: "premium", downgraded_from: null, prompt_chars: 10 }],
        ["token", { index: 0, token: "Hello ", t_ms: 100 }],
        ["token", { index: 1, token: "there", t_ms: 140 }],
        ["done", reply()],
      ]),
    );
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText("Gateway at http://gw:8000");
    await user.click(await screen.findByRole("radio", { name: /acme/ }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Hi{Enter}");

    const answer = await screen.findByRole("article", { name: "Reply" });
    await within(answer).findByText("Hello there");
    expect(within(answer).getByText("premium")).toBeInTheDocument();
    expect(within(answer).getByText("First token")).toBeInTheDocument();
    expect(within(answer).getByText("100 ms")).toBeInTheDocument();
    expect(requests).toEqual([
      expect.objectContaining({
        tenant_id: "acme",
        message: "Hi",
        quality: "best",
        allow_downgrade: false,
      }),
    ]);
  });

  it("sends a specific model and shows the gateway's refusal", async () => {
    const requests = stubBackend(() =>
      sse([
        [
          "error",
          {
            status: 403,
            code: "model_not_in_plan",
            message: "Tenant 'initech' is on the 'free' plan, which does not include 'premium'.",
          },
        ],
      ]),
    );
    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole("radio", { name: /initech/ });
    await user.selectOptions(screen.getByRole("combobox", { name: "Model choice" }), "premium");
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Hi{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Not in this tenant's plan (HTTP 403)");
    expect(requests[0]).toMatchObject({ tenant_id: "initech", model: "premium" });
    expect(requests[0]).not.toHaveProperty("quality");
  });
});
