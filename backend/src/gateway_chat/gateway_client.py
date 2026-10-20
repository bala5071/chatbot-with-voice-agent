"""The gateway's HTTP API, as this app uses it.

Only the gateway's public API is used: POST /v1/generate with `stream: true`, and a few
GETs. Nothing here knows how the gateway routes, batches or meters; it reports what the
gateway said, including its errors, unchanged.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class Started:
    """The gateway accepted the request; headers name the model serving it."""

    model: str
    downgraded_from: str | None


@dataclass(frozen=True, slots=True)
class Token:
    index: int
    text: str
    # Milliseconds since the gateway received the request, by the gateway's clock.
    t_ms: float


@dataclass(frozen=True, slots=True)
class Done:
    # The gateway's GenerateResponse: id, text, model, usage, timing, cost.
    reply: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Failed:
    # The gateway's HTTP status; None when the gateway could not be reached at all, and 200
    # when it failed after the stream had started.
    status: int | None
    # The gateway's error object: at least `code` and `message`.
    error: dict[str, Any] = field(default_factory=dict)


Event = Started | Token | Done | Failed


class SseParser:
    """Server-sent events, one line at a time. Only `event:` and `data:` are used."""

    def __init__(self) -> None:
        self._event = "message"
        self._data: list[str] = []

    def feed(self, line: str) -> tuple[str, str] | None:
        """The (event, data) completed by this line, if it is the blank line ending one."""
        line = line.rstrip("\r\n")
        if not line:
            if not self._data:
                self._event = "message"
                return None
            done = (self._event, "\n".join(self._data))
            self._event, self._data = "message", []
            return done
        if line.startswith(":"):
            return None
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            self._event = value
        elif name == "data":
            self._data.append(value)
        return None


class GatewayUnavailableError(Exception):
    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"Could not connect to the gateway at {url}. {reason}")
        self.url = url


def _error_of(response: httpx.Response) -> dict[str, Any]:
    """The gateway's error object from a failed response, or a stand-in if it has none."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return dict(body["error"])
    return {
        "code": "gateway_error",
        "message": f"The gateway answered HTTP {response.status_code}: {response.text[:200]}",
    }


class GatewayClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    @property
    def url(self) -> str:
        return str(self._http.base_url).rstrip("/")

    async def get(self, path: str) -> tuple[int, Any]:
        """Status and JSON body of a GET. Raises GatewayUnavailableError if unreachable."""
        try:
            response = await self._http.get(path)
        except httpx.HTTPError as exc:
            if isinstance(exc, httpx.ConnectError):
                raise GatewayUnavailableError(self.url, "Is it running?") from exc
            raise GatewayUnavailableError(self.url, f"{type(exc).__name__}.") from exc
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"error": _error_of(response)}

    async def stream_generate(self, body: dict[str, Any]) -> AsyncGenerator[Event, None]:
        """One streamed generation: Started, Tokens, then Done; or Failed at any point.

        Closing the iterator early closes the connection, which is how the gateway learns
        to cancel the request and free the model.
        """
        try:
            async with self._http.stream(
                "POST", "/v1/generate", json={**body, "stream": True}
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    yield Failed(response.status_code, _error_of(response))
                    return
                yield Started(
                    model=response.headers.get("x-model-used", ""),
                    downgraded_from=response.headers.get("x-downgraded-from"),
                )
                parser = SseParser()
                async for line in response.aiter_lines():
                    event = parser.feed(line)
                    if event is None:
                        continue
                    name, data = event
                    payload = json.loads(data)
                    if name == "token":
                        yield Token(int(payload["index"]), str(payload["token"]), payload["t_ms"])
                    elif name == "done":
                        yield Done(payload)
                        return
                    elif name == "error":
                        yield Failed(200, payload)
                        return
                yield Failed(
                    200,
                    {
                        "code": "stream_ended",
                        "message": "The gateway closed the stream before the reply was done.",
                    },
                )
        except httpx.ConnectError:
            yield Failed(
                None,
                {
                    "code": "gateway_unavailable",
                    "message": f"Could not connect to the gateway at {self.url}. Is it running?",
                },
            )
        except httpx.TimeoutException:
            yield Failed(
                None,
                {"code": "gateway_timeout", "message": "The gateway did not answer in time."},
            )
        except httpx.HTTPError as exc:
            yield Failed(
                None,
                {"code": "gateway_error", "message": f"Lost the gateway: {type(exc).__name__}."},
            )
