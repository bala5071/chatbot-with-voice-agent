from __future__ import annotations

import httpx
import pytest

from gateway_chat.gateway_client import (
    Done,
    Event,
    Failed,
    GatewayClient,
    GatewayUnavailableError,
    SseParser,
    Started,
    Token,
)
from tests.fake_gateway import create_fake_gateway


def fake_client() -> GatewayClient:
    transport = httpx.ASGITransport(app=create_fake_gateway())
    return GatewayClient(httpx.AsyncClient(transport=transport, base_url="http://gateway"))


def client_answering(handler: httpx.MockTransport) -> GatewayClient:
    return GatewayClient(httpx.AsyncClient(transport=handler, base_url="http://gateway"))


async def collect(client: GatewayClient, **body: object) -> list[Event]:
    return [event async for event in client.stream_generate(body)]


def test_sse_parser_events_and_comments() -> None:
    parser = SseParser()
    lines = [": comment", "event: token", 'data: {"a": 1}', "", "", "data: x", "data: y", ""]
    events = [e for line in lines if (e := parser.feed(line)) is not None]
    assert events == [("token", '{"a": 1}'), ("message", "x\ny")]


async def test_a_streamed_reply() -> None:
    events = await collect(fake_client(), tenant_id="globex", quality="best", prompt="hi")
    assert events[0] == Started(model="standard", downgraded_from=None)
    tokens = [e for e in events if isinstance(e, Token)]
    assert [t.index for t in tokens] == list(range(len(tokens)))
    assert isinstance(events[-1], Done)
    assert events[-1].reply["text"] == "".join(t.text for t in tokens)
    assert events[-1].reply["model"] == "standard"


async def test_a_refusal_keeps_the_gateway_status_and_error() -> None:
    events = await collect(fake_client(), tenant_id="initech", model="premium", prompt="hi")
    [event] = events
    assert isinstance(event, Failed)
    assert event.status == 403
    assert event.error["code"] == "model_not_in_plan"
    assert event.error["allowed_models"] == ["economy"]


async def test_an_error_after_the_stream_started() -> None:
    events = await collect(fake_client(), tenant_id="acme", quality="best", prompt="[[fail-mid]]")
    assert isinstance(events[0], Started)
    assert len([e for e in events if isinstance(e, Token)]) == 3
    assert events[-1] == Failed(
        200, {"code": "backend_error", "message": "Connection lost mid-reply."}
    )


async def test_a_stream_that_just_stops() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = 'event: token\ndata: {"index": 0, "token": "a", "t_ms": 1}\n\n'
        return httpx.Response(200, text=body, headers={"X-Model-Used": "economy"})

    events = await collect(client_answering(httpx.MockTransport(handler)), prompt="x")
    assert events[1] == Token(0, "a", 1)
    assert isinstance(events[-1], Failed)
    assert events[-1].error["code"] == "stream_ended"


async def test_an_error_without_the_gateway_error_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    [event] = await collect(client_answering(httpx.MockTransport(handler)), prompt="x")
    assert isinstance(event, Failed)
    assert event.status == 500
    assert event.error["code"] == "gateway_error"
    assert "HTTP 500" in event.error["message"]


async def test_gateway_not_running() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = client_answering(httpx.MockTransport(handler))
    [event] = await collect(client, prompt="x")
    assert isinstance(event, Failed)
    assert event.status is None
    assert event.error["code"] == "gateway_unavailable"
    with pytest.raises(GatewayUnavailableError, match="http://gateway"):
        await client.get("/healthz")


async def test_get_returns_status_and_body() -> None:
    status, body = await fake_client().get("/v1/tenants/nobody/usage")
    assert status == 404
    assert body["error"]["code"] == "unknown_tenant"
