from __future__ import annotations

import json
from typing import Any

import httpx

from gateway_chat.app import create_app
from gateway_chat.config import Settings
from gateway_chat.gateway_client import SseParser
from tests.fake_gateway import create_fake_gateway


def parse_sse(text: str) -> list[tuple[str, Any]]:
    """Every (event, decoded data) in a complete server-sent-event body."""
    parser = SseParser()
    events = []
    for line in [*text.split("\n"), ""]:
        event = parser.feed(line)
        if event is not None:
            events.append((event[0], json.loads(event[1])))
    return events


class Rig:
    """The chat app wired to the fake gateway, both in process."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.gateway = create_fake_gateway()
        self.gateway_http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.gateway), base_url="http://gateway"
        )
        self.app = create_app(settings or Settings(), http=self.gateway_http)
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://chat"
        )

    @property
    def gateway_requests(self) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = self.gateway.state.requests
        return requests

    async def chat(self, **body: Any) -> list[tuple[str, Any]]:
        defaults = {"tenant_id": "acme", "conversation_id": "c1", "quality": "best"}
        response = await self.http.post("/api/chat", json={**defaults, **body})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        return parse_sse(response.text)

    async def close(self) -> None:
        await self.http.aclose()
        await self.gateway_http.aclose()
