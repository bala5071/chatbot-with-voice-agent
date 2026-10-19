"""The client against a real gateway, to catch the fake drifting from it.

Skipped unless CHAT_TEST_GATEWAY_URL names a running gateway with its packaged plans. The
gateway's simulated mode is enough, and needs no model:

    # in the gateway repository
    uv run uvicorn gateway.app:create_default_app --factory --port 8000
    # here
    CHAT_TEST_GATEWAY_URL=http://127.0.0.1:8000 uv run pytest -m gateway
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest

from gateway_chat.gateway_client import Done, Failed, GatewayClient, Started, Token
from tests.fake_gateway import create_fake_gateway

URL = os.environ.get("CHAT_TEST_GATEWAY_URL")

pytestmark = [
    pytest.mark.gateway,
    pytest.mark.skipif(not URL, reason="CHAT_TEST_GATEWAY_URL is not set"),
]


@pytest.fixture
async def real() -> AsyncIterator[GatewayClient]:
    assert URL is not None
    async with httpx.AsyncClient(base_url=URL, timeout=120) as http:
        yield GatewayClient(http)


@pytest.fixture
async def fake() -> AsyncIterator[GatewayClient]:
    transport = httpx.ASGITransport(app=create_fake_gateway())
    async with httpx.AsyncClient(transport=transport, base_url="http://fake") as http:
        yield GatewayClient(http)


async def test_a_streamed_reply_has_the_same_shape(real: GatewayClient) -> None:
    events = [
        e
        async for e in real.stream_generate(
            {"tenant_id": "globex", "quality": "best", "prompt": "Say hi.", "max_tokens": 8}
        )
    ]
    assert events[0] == Started(model="standard", downgraded_from=None)
    assert all(isinstance(e, Token) for e in events[1:-1])
    assert isinstance(events[-1], Done)
    reply = events[-1].reply
    assert set(reply) == {"id", "text", "model", "usage", "timing", "cost"}
    assert set(reply["usage"]) == {
        "prompt_tokens",
        "cached_tokens",
        "completion_tokens",
        "total_tokens",
    }
    assert set(reply["timing"]) == {"queue_ms", "ttft_ms", "total_ms"}


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"tenant_id": "initech", "model": "premium"}, 403, "model_not_in_plan"),
        ({"tenant_id": "nobody", "quality": "best"}, 404, "unknown_tenant"),
        ({"quality": "best"}, 401, "tenant_required"),
    ],
)
async def test_refusals_match(
    real: GatewayClient, fake: GatewayClient, body: dict[str, str], status: int, code: str
) -> None:
    for client in (real, fake):
        [event] = [e async for e in client.stream_generate({**body, "prompt": "hi"})]
        assert isinstance(event, Failed)
        assert (event.status, event.error["code"]) == (status, code)


async def test_usage_has_the_same_fields(real: GatewayClient, fake: GatewayClient) -> None:
    (real_status, real_body), (fake_status, fake_body) = [
        await c.get("/v1/tenants/globex/usage") for c in (real, fake)
    ]
    assert real_status == fake_status == 200
    assert set(real_body) == set(fake_body)
    assert set(real_body["total"]) == set(fake_body["total"])
    assert real_body["allowed_models"] == fake_body["allowed_models"]


async def test_the_plan_refusal_is_the_same_body(real: GatewayClient, fake: GatewayClient) -> None:
    body = {"tenant_id": "initech", "model": "premium", "prompt": "hi"}
    [real_event] = [e async for e in real.stream_generate(body)]
    [fake_event] = [e async for e in fake.stream_generate(body)]
    assert real_event == fake_event
