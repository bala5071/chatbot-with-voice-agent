"""The chat backend: the browser talks to this, and this talks to the gateway.

The browser cannot call the gateway directly (it sends no CORS headers), and the gateway
takes one prompt string per request, so this server keeps each conversation's history and
writes it into the prompt. Everything about models, plans, budgets and timing comes from
the gateway's answers.

Run with:  uv run uvicorn gateway_chat.app:create_default_app --factory --port 8100
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from gateway_chat.config import Settings
from gateway_chat.gateway_client import (
    Done,
    Failed,
    GatewayClient,
    GatewayUnavailableError,
    Started,
    Token,
)
from gateway_chat.prompt import Turn, build_prompt
from gateway_chat.sessions import ConversationStore

Quality = Literal["cheapest", "balanced", "best"]

# Connecting should be quick; a reply from a large model on a CPU is not.
_TIMEOUT = httpx.Timeout(10.0, read=300.0)


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=64)
    conversation_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=8000)
    # One of these picks the model, within the tenant's plan; the gateway checks which.
    quality: Quality | None = None
    model: str | None = Field(default=None, min_length=1)
    allow_downgrade: bool = False


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _unreachable(exc: GatewayUnavailableError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": {"code": "gateway_unavailable", "message": str(exc), "url": exc.url}},
    )


def create_app(settings: Settings, http: httpx.AsyncClient | None = None) -> FastAPI:
    """The app. Tests pass `http` (an httpx client wired to a fake gateway)."""
    owned = http is None
    client = http or httpx.AsyncClient(base_url=settings.gateway_url, timeout=_TIMEOUT)
    gateway = GatewayClient(client)
    store = ConversationStore(settings.max_conversations)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owned:
            await client.aclose()

    app = FastAPI(title="Gateway chat", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        try:
            status, body = await gateway.get("/healthz")
        except GatewayUnavailableError:
            return {"status": "ok", "gateway": {"url": gateway.url, "reachable": False}}
        return {
            "status": "ok",
            "gateway": {"url": gateway.url, "reachable": status == 200, "health": body},
        }

    @app.get("/api/models")
    async def models() -> JSONResponse:
        try:
            status, body = await gateway.get("/v1/models")
        except GatewayUnavailableError as exc:
            return _unreachable(exc)
        return JSONResponse(status_code=status, content=body)

    @app.get("/api/tenants")
    async def tenants() -> JSONResponse:
        """Each configured tenant with its plan and usage, as the gateway reports them."""

        async def one(tenant_id: str) -> dict[str, Any]:
            status, body = await gateway.get(f"/v1/tenants/{tenant_id}/usage")
            if status == 200:
                return {"tenant_id": tenant_id, "usage": body, "error": None}
            return {"tenant_id": tenant_id, "usage": None, "error": body.get("error")}

        try:
            found = await asyncio.gather(*(one(t) for t in settings.tenants))
        except GatewayUnavailableError as exc:
            return _unreachable(exc)
        return JSONResponse({"tenants": found})

    @app.get("/api/tenants/{tenant_id}")
    async def tenant(tenant_id: str) -> JSONResponse:
        try:
            status, body = await gateway.get(f"/v1/tenants/{tenant_id}/usage")
        except GatewayUnavailableError as exc:
            return _unreachable(exc)
        return JSONResponse(status_code=status, content=body)

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    async def forget(conversation_id: str) -> None:
        store.forget(conversation_id)

    @app.post("/api/chat")
    async def chat(body: ChatBody) -> StreamingResponse:
        """One turn, answered with server-sent events: start, token..., then done or error.

        Every outcome, including the gateway refusing the request, is an event in a 200
        stream, so the browser has one code path. `error` carries the gateway's status.
        """
        history = store.history(body.conversation_id)
        prompt = build_prompt(settings.system_prompt, history, body.message, settings.history_chars)
        request: dict[str, Any] = {
            "tenant_id": body.tenant_id,
            "prompt": prompt,
            "max_tokens": settings.max_tokens,
            "allow_downgrade": body.allow_downgrade,
        }
        if body.model is not None:
            request["model"] = body.model
        if body.quality is not None:
            request["quality"] = body.quality

        async def events() -> AsyncIterator[str]:
            stream = gateway.stream_generate(request)
            try:
                async for event in stream:
                    if isinstance(event, Started):
                        yield _sse(
                            "start",
                            {
                                "model": event.model,
                                "downgraded_from": event.downgraded_from,
                                "prompt_chars": len(prompt),
                            },
                        )
                    elif isinstance(event, Token):
                        yield _sse(
                            "token", {"index": event.index, "token": event.text, "t_ms": event.t_ms}
                        )
                    elif isinstance(event, Done):
                        store.append(
                            body.conversation_id,
                            Turn("user", body.message),
                            Turn("assistant", str(event.reply.get("text", ""))),
                        )
                        yield _sse("done", event.reply)
                    elif isinstance(event, Failed):
                        yield _sse("error", {"status": event.status, **event.error})
            finally:
                # The browser went away (the stop button): close the gateway stream too.
                await stream.aclose()

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")

    return app


def create_default_app() -> FastAPI:
    return create_app(Settings.from_env(os.environ))
