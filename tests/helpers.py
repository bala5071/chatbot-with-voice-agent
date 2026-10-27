"""Test helpers: a mock gateway on httpx's MockTransport, and the leak scanner."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from voice_agent.clock import FakeClock
from voice_agent.gateway_client import GatewayClient, make_http_client
from voice_agent.secret import Secret

# Built from parts so no key-shaped literal sits in the source; used only as a planted value.
PLANTED_KEY = "gwk_" + "plantedTestKey" + "_" + "Zq7" * 8
BASE_URL = "http://127.0.0.1:8000"
FIRST_TOKEN_MS = 1_000.0
TOTAL_MS = 5_000.0


def chunk(content: str | None = None, *, role: bool = False, finish: str | None = None) -> str:
    delta: dict[str, Any] = {}
    if role:
        delta = {"role": "assistant", "content": ""}
    elif content is not None:
        delta = {"content": content}
    body = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "standard",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body)}\n\n"


def usage_chunk() -> str:
    body = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "standard",
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }
    return f"data: {json.dumps(body)}\n\n"


def reply_events(*texts: str) -> list[str]:
    return [
        chunk(role=True),
        *(chunk(t) for t in texts),
        chunk(finish="stop"),
        usage_chunk(),
        "data: [DONE]\n\n",
    ]


def error_body(code: str, message: str = "gateway said something private") -> dict[str, Any]:
    return {"error": {"message": message, "type": "api_error", "param": None, "code": code}}


@dataclass
class MockGateway:
    """Answers each request with ``status`` and ``events``; ``hang_after`` events, it waits
    forever (until the client gives up). Records what it saw, as booleans and shapes only."""

    status: int = 200
    events: Sequence[str] = field(default_factory=lambda: reply_events("Hello."))
    json_body: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    hang_after: int | None = None
    raise_exc: Exception | None = None
    hung: asyncio.Event = field(default_factory=asyncio.Event)
    requests: list[httpx.Request] = field(default_factory=list)

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.status != 200:
            return httpx.Response(self.status, json=self.json_body, headers=self.headers)
        return httpx.Response(
            200, content=self._stream(), headers={"content-type": "text/event-stream"}
        )

    async def _stream(self) -> AsyncIterator[bytes]:
        for index, event in enumerate(self.events):
            if self.hang_after is not None and index == self.hang_after:
                self.hung.set()
                await asyncio.Event().wait()
            yield event.encode()
        if self.hang_after is not None and self.hang_after >= len(self.events):
            self.hung.set()
            await asyncio.Event().wait()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def make_client(gateway: MockGateway, clock: FakeClock, key: str = PLANTED_KEY) -> GatewayClient:
    return GatewayClient(
        make_http_client(BASE_URL, transport=gateway.transport()),
        Secret(key),
        clock,
        model="standard",
        max_tokens=64,
        first_token_timeout_ms=FIRST_TOKEN_MS,
        total_timeout_ms=TOTAL_MS,
    )


async def collect(client: GatewayClient, on_sent: Callable[[], None] | None = None) -> list[str]:
    from voice_agent.interfaces import Message

    return [
        delta
        async for delta in client.stream(
            [Message("user", "What are your hours?")], on_sent or (lambda: None)
        )
    ]


def find_leaks(secret: str, places: Iterable[tuple[str, str]]) -> list[str]:
    """The names of the places whose text contains ``secret``. Never returns the text, so a
    failing assertion cannot print the secret."""
    return [name for name, text in places if secret in text]
