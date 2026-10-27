"""``GatewayClient``: the reply, streamed from the gateway's ``POST /v1/chat/completions``.

It speaks the gateway's OpenAI-shaped stream: ``data: {chat.completion.chunk}`` events, then
``data: [DONE]``. An error before output is an HTTP status with an OpenAI error body; an
error after output has started comes as one ``data: {"error": {...}}`` event and the stream
ends without ``[DONE]`` (the gateway's docs/31).

Every failure becomes a ``SpokenError`` (``errors.py``): by status before output, by the
gateway's error code inside the stream. The gateway's message text is never kept, logged or
spoken. Timeouts are on the injected clock: one until the first token, one for the whole
reply, both counted from just before the request is written. httpx's own connect and read
timeouts map to ``TimedOut`` too.

The key is a ``Secret``, revealed only in ``_auth_headers``. The httpx client must not follow
redirects (a redirect would carry the header elsewhere) and must ignore proxy settings from the
environment; ``make_http_client`` builds it that way.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any, TypeVar

import httpx

from voice_agent.clock import Clock
from voice_agent.errors import (
    TimedOut,
    Unavailable,
    error_for_status,
    error_for_stream_code,
)
from voice_agent.interfaces import Message
from voice_agent.secret import Secret

log = logging.getLogger(__name__)

T = TypeVar("T")
PATH = "/v1/chat/completions"


def make_http_client(
    base_url: str, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        transport=transport,
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
    )


def _auth_headers(key: Secret) -> dict[str, str]:
    return {"Authorization": f"Bearer {key.reveal()}"}


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after", "")
    return int(raw) if raw.isdigit() else None


def _error_code(body: bytes) -> str | None:
    try:
        error = json.loads(body).get("error")
    except (ValueError, AttributeError):
        return None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


class GatewayClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        key: Secret,
        clock: Clock,
        *,
        model: str,
        max_tokens: int,
        first_token_timeout_ms: float,
        total_timeout_ms: float,
    ) -> None:
        self._http = http
        self._key = key
        self._clock = clock
        self._model = model
        self._max_tokens = max_tokens
        self._first_token_timeout_ms = first_token_timeout_ms
        self._total_timeout_ms = total_timeout_ms

    def __repr__(self) -> str:
        return f"GatewayClient(url={str(self._http.base_url)!r}, model={self._model!r})"

    def _body(self, messages: Sequence[Message]) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

    async def stream(
        self, messages: Sequence[Message], on_sent: Callable[[], None]
    ) -> AsyncIterator[str]:
        request = self._http.build_request(
            "POST", PATH, json=self._body(messages), headers=_auth_headers(self._key)
        )
        on_sent()
        sent_at = self._clock.now_ms()
        got_token = False

        def remaining() -> float:
            elapsed = self._clock.now_ms() - sent_at
            left = self._total_timeout_ms - elapsed
            if not got_token:
                left = min(left, self._first_token_timeout_ms - elapsed)
            return left

        try:
            response = await self._within(self._http.send(request, stream=True), remaining())
        except httpx.TimeoutException:
            raise TimedOut(None, "http_timeout") from None
        except httpx.HTTPError:
            raise Unavailable(None, "gateway_unreachable") from None
        try:
            if response.status_code != 200:
                body = await self._within(response.aread(), remaining())
                raise error_for_status(
                    response.status_code, _error_code(body), _retry_after(response)
                )
            lines = response.aiter_lines()
            while True:
                try:
                    line = await self._within(anext(lines), remaining())
                except StopAsyncIteration:
                    raise Unavailable(None, "stream_ended") from None
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    return
                try:
                    event = json.loads(data)
                except ValueError:
                    raise Unavailable(None, "malformed_stream") from None
                if not isinstance(event, dict):
                    raise Unavailable(None, "malformed_stream")
                if "error" in event:
                    error = event["error"]
                    code = error.get("code") if isinstance(error, dict) else None
                    raise error_for_stream_code(code if isinstance(code, str) else None)
                text = _delta_text(event)
                if text:
                    got_token = True
                    yield text
        except httpx.TimeoutException:
            raise TimedOut(None, "http_timeout") from None
        except httpx.HTTPError:
            raise Unavailable(None, "gateway_connection_lost") from None
        finally:
            await response.aclose()

    async def _within(self, work: Awaitable[T], timeout_ms: float) -> T:
        """``work``, or ``TimedOut`` if the injected clock passes ``timeout_ms`` first."""
        if timeout_ms <= 0:
            if asyncio.iscoroutine(work):
                work.close()
            raise TimedOut(None, "deadline")
        task = asyncio.ensure_future(work)
        timer = asyncio.ensure_future(self._clock.sleep(timeout_ms))
        try:
            done, _ = await asyncio.wait({task, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            timer.cancel()
        if task in done:
            return task.result()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        raise TimedOut(None, "deadline")


def _delta_text(event: dict[str, Any]) -> str:
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""  # the usage chunk has no choices
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    content = delta.get("content") if isinstance(delta, dict) else None
    return content if isinstance(content, str) else ""
