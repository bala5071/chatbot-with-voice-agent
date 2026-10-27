"""The gateway client against a mock gateway: the request, the stream, and every failure."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tests.helpers import (
    FIRST_TOKEN_MS,
    PLANTED_KEY,
    TOTAL_MS,
    MockGateway,
    chunk,
    collect,
    error_body,
    make_client,
    reply_events,
)
from voice_agent.clock import FakeClock
from voice_agent.errors import (
    Busy,
    Misconfigured,
    NotAuthorized,
    NotPermitted,
    SpokenError,
    TimedOut,
    Unavailable,
)
from voice_agent.gateway_client import make_http_client


async def test_streams_the_reply_and_sends_the_right_request() -> None:
    gateway = MockGateway(events=reply_events("Hello", " there.", " Bye."))
    sent: list[float] = []
    clock = FakeClock(start_ms=42)
    deltas = await collect(make_client(gateway, clock), lambda: sent.append(clock.now_ms()))
    assert deltas == ["Hello", " there.", " Bye."]
    assert sent == [42]
    (request,) = gateway.requests
    assert request.method == "POST"
    assert request.url.path == "/v1/chat/completions"
    body = json.loads(request.content)
    assert body["stream"] is True
    assert body["model"] == "standard"
    assert body["stream_options"] == {"include_usage": True}
    assert body["messages"] == [{"role": "user", "content": "What are your hours?"}]
    # A boolean, so a failure cannot print the header.
    authorized = request.headers["authorization"] == f"Bearer {PLANTED_KEY}"
    assert authorized


GATEWAY_MESSAGE = "gateway said something private"


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "api_key_required", NotAuthorized),
        (401, "invalid_api_key", NotAuthorized),
        (403, "model_not_in_plan", NotPermitted),
        (429, "rate_limited", Busy),
        (429, "budget_exhausted", Busy),
        (429, "queue_full", Busy),
        (500, "internal_error", Unavailable),
        (502, "upstream_unavailable", Unavailable),
        (503, "no_local_provider", Unavailable),
        (504, "request_timeout", Unavailable),
        (404, "unknown_model", Misconfigured),
        (422, "invalid_request", Misconfigured),
    ],
)
async def test_status_maps_to_a_spoken_error(
    status: int, code: str, expected: type[SpokenError]
) -> None:
    gateway = MockGateway(status=status, json_body=error_body(code))
    with pytest.raises(SpokenError) as caught:
        await collect(make_client(gateway, FakeClock()))
    error = caught.value
    assert type(error) is expected
    assert error.status == status
    assert error.code == code
    for text in (error.spoken, str(error), repr(error)):
        assert GATEWAY_MESSAGE not in text


async def test_429_keeps_retry_after() -> None:
    gateway = MockGateway(
        status=429, json_body=error_body("rate_limited"), headers={"Retry-After": "7"}
    )
    with pytest.raises(Busy) as caught:
        await collect(make_client(gateway, FakeClock()))
    assert caught.value.retry_after_s == 7


async def test_a_status_without_an_error_body_still_maps() -> None:
    gateway = MockGateway(status=502, json_body=None)
    with pytest.raises(Unavailable) as caught:
        await collect(make_client(gateway, FakeClock()))
    assert caught.value.code is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("rate_limited", Busy),
        ("queue_full", Busy),
        ("upstream_timeout", Unavailable),
        ("request_timeout", Unavailable),
        ("internal_error", Unavailable),
        ("something_new", Unavailable),
    ],
)
async def test_error_inside_the_stream_maps_by_code(code: str, expected: type[SpokenError]) -> None:
    events = [chunk(role=True), chunk("Partial"), f"data: {json.dumps(error_body(code))}\n\n"]
    seen: list[str] = []

    async def consume() -> None:
        async for delta in make_client(MockGateway(events=events), FakeClock()).stream(
            [], lambda: None
        ):
            seen.append(delta)

    with pytest.raises(SpokenError) as caught:
        await consume()
    assert seen == ["Partial"]
    assert type(caught.value) is expected
    assert caught.value.status is None
    assert GATEWAY_MESSAGE not in str(caught.value)


async def test_stream_ending_without_done_is_unavailable() -> None:
    events = [chunk(role=True), chunk("Partial")]
    with pytest.raises(Unavailable) as caught:
        await collect(make_client(MockGateway(events=events), FakeClock()))
    assert caught.value.code == "stream_ended"


async def test_malformed_event_is_unavailable() -> None:
    events = [chunk(role=True), "data: {not json\n\n"]
    with pytest.raises(Unavailable) as caught:
        await collect(make_client(MockGateway(events=events), FakeClock()))
    assert caught.value.code == "malformed_stream"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.ConnectError("refused"), Unavailable),
        (httpx.ConnectTimeout("slow"), TimedOut),
        (httpx.ReadTimeout("slow"), TimedOut),
        (httpx.RemoteProtocolError("bad"), Unavailable),
    ],
)
async def test_transport_failures_map(exc: Exception, expected: type[SpokenError]) -> None:
    with pytest.raises(SpokenError) as caught:
        await collect(make_client(MockGateway(raise_exc=exc), FakeClock()))
    assert type(caught.value) is expected


async def test_first_token_timeout_on_the_injected_clock() -> None:
    clock = FakeClock()
    gateway = MockGateway(events=reply_events("Late."), hang_after=1)  # role chunk, then silence
    task = asyncio.ensure_future(collect(make_client(gateway, clock)))
    await gateway.hung.wait()
    await clock.wait_for_sleepers(1)
    clock.advance(FIRST_TOKEN_MS - 1)
    assert clock.sleeping == 1
    assert not task.done()
    clock.advance(1)
    with pytest.raises(TimedOut) as caught:
        await task
    assert caught.value.code == "deadline"


async def test_total_timeout_applies_after_the_first_token() -> None:
    clock = FakeClock()
    gateway = MockGateway(events=reply_events("Early", " and late."), hang_after=2)
    task = asyncio.ensure_future(collect(make_client(gateway, clock)))
    await gateway.hung.wait()
    await clock.wait_for_sleepers(1)
    clock.advance(FIRST_TOKEN_MS + 1)  # past the first-token limit: no longer applies
    assert clock.sleeping == 1
    assert not task.done()
    clock.advance(TOTAL_MS - FIRST_TOKEN_MS - 1)
    with pytest.raises(TimedOut):
        await task


async def test_redirects_are_not_followed() -> None:
    gateway = MockGateway(status=307, headers={"Location": "https://elsewhere.example/x"})
    with pytest.raises(Misconfigured):
        await collect(make_client(gateway, FakeClock()))
    assert len(gateway.requests) == 1


def test_the_http_client_ignores_proxy_settings_and_follows_no_redirects() -> None:
    client = make_http_client("http://127.0.0.1:8000")
    assert client.trust_env is False
    assert client.follow_redirects is False
